# -*- coding: utf-8 -*-

# Copyright (C) 2008  Google, Inc. All Rights Reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

'''TsumuFS is a disconnected, offline caching filesystem.'''

import os
import stat
import time
import errno
import exceptions
import threading
import new

import tsumufs
from extendedattributes import extendedattribute

from ufo.filesystem import SyncDocument, CouchedFileSystem
from ufo.utils import CacheDict
from ufo.database import *


class CachedRevisionDocument(UTF8Document):
  '''
  CouchDb document to represent a document revision
  of a file in the cache.
  '''

  doctype  = TextField(default="CachedRevisionDocument")
  fileid   = TextField()
  revision = TextField()
  mtime    = FloatField()

  by_fileid = ViewField('cachedrevision',
    language='javascript',
    map_fun="function (doc) {"
              "if (doc.doctype === 'CachedRevisionDocument') {" \
                "emit(doc.fileid, doc);" \
              "}" \
            "}")


class FileSystemOverlay(tsumufs.Debuggable):
  '''
  The CouchedFileSytem api from the python-ufo library is middleware
  that handle system calls on a mount point and manage the metadatas
  of the filesystem himself in a CouchDb database. This is useful
  for browsing the filesystem contents by file attributes instead of
  by browsing the filesystem tree.

  FileSystemOverlay handles all features of the CouchedFileSytem
  api, and override most of then to provides the in-memory caching
  of the database results documents. This is convenient to fix the
  overhead caused by the http requests to the CouchDb server

  It also schedule read/write access to local/remote filesystem
  in function to the 'usefs' parameter.
  '''

  _localRevisions = None            # Revisions of the cached copies of documents.

  def __init__(self):
    self.replicationTaskId = 0

    # Couched filesystem object for read/write access
    # to the cached filesystem.
    self._couchedLocal = CouchedFileSystem(tsumufs.cachePoint,
                                           tsumufs.dbName,
                                           db_metadatas=True)

    self._localRevisions = DocumentHelper(CachedRevisionDocument, tsumufs.dbName,
                                          batch=True)

  def startReplication(self):
    '''
    Start the replication from the remote database to the client.
    Starting an already running replication just returns the id
    of the existing task.
    If the connection to the remote CouchDB closes, the tasks stays
    alive and replication will resume when the server comes back.
    '''
    try:
      result = self._couchedLocal.doc_helper.replicate(tsumufs.dbName, tsumufs.dbRemote,
                                                       auth=tsumufs.auth, reverse=True, continuous=True,
                                                       filter="replication/nodesigndocs")
      self.replicationTaskId = result["_local_id"]

      result = self._couchedLocal.doc_helper.replicate(tsumufs.dbName, tsumufs.dbRemote,
                                                       auth=tsumufs.auth, continuous=True,
                                                       filter="replication/onlymeta")
      self.metaReplicationTaskId = result["_local_id"]

      return self.replicationTaskId

    except tsumufs.DocumentException, e:
      self._debug('Unable to replicate changes from remote couchdb: %s'
                  % str(e))

  def stopReplication(self):
    if self.replicationTaskId:
      try:
        self._couchedLocal.doc_helper.replicate(tsumufs.dbName, tsumufs.dbRemote,
                                                auth=tsumufs.auth, reverse=True, continuous=True,
                                                cancel=True)
        self.replicationTaskId = 0
      except:
        self._debug("Unable to stop replication task %s" % self.replicationTaskId)

  def checkpoint(self):
    '''
    Ensure the modified database entries are written to disk.
    '''

    self._localRevisions.commit()

  def getCachedRevision(self, fileid):
    '''
    Get the last cached revision number of a file.

    Returns:
      A revision string

    Raises:
      KeyError
    '''

    try:
      self._cachedRevisions.acquire()

      # Use the in-memory cached copy of the revision if exists,
      # otherwise get revision from database and cache it.
      if self._cachedRevisions.isObsolete(fileid):
        cached = self._localRevisions.by_fileid(key=fileid, pk=True)
        revision, mtime = cached.revision, cached.mtime

        self._debug('Caching revision in memory (%s -> %s, %s)' % (fileid, revision, mtime))
        self._cachedRevisions.cache(fileid, (revision, mtime))

      return self._cachedRevisions.get(fileid)

    except DocumentException, e:
      raise KeyError(e.message)

    finally:
      self._cachedRevisions.release()

  def setCachedRevision(self, fileid, revision, mtime):
    '''
    Update or create the last cached revision number of a file.

    Returns:
      Nothing

    Raises:
      Nothing
    '''

    try:
      self._cachedRevisions.acquire()

      try:
        cacherev = self._localRevisions.by_fileid(key=fileid, pk=True)
        cacherev.revision = revision
        cacherev.mtime = mtime

        self._localRevisions.update(cacherev)

      except DocumentException, e:
        self._localRevisions.create(fileid=fileid, revision=revision, mtime=mtime)

      # Update the in-memory cached copy
      self._cachedRevisions.cache(fileid, (revision, mtime))

    finally:
      self._cachedRevisions.release()

  def removeCachedRevision(self, fileid):
    '''
    Remove the last cached revision number of a file.

    Returns:
      Nothing

    Raises:
      KeyError
    '''

    try:
      self._cachedRevisions.acquire()

      local = self._localRevisions.by_fileid(key=fileid,
                                             pk=True)

      self._localRevisions.delete(local)
      # Remove the in-memory cached copy
      self._cachedRevisions.invalidate(fileid)

      return local.fileid, local.revision

    except DocumentException, e:
      raise KeyError(e.message)

    finally:
      self._cachedRevisions.release()

  def cachedFileOpWrapper(self, couchedfs, function, *args, **kws):
    '''
    Wrapper method to cache in memory modified document in
    database by a CouchedFile instance, and cache the new
    revision if the update has been done in the cache.
    '''

    documents = function.__call__(*args, **kws)

    if documents:
      for doc in documents:
        self.setCachedRevision(doc.id, doc.rev, doc.stats.st_mtime)

  def __getitem__(self, fusepath):
    '''
    Accessor to get SyncDocument instance referenced
    by fusepath, it contains all metadatas of a file.
    '''
    return self._get(fusepath)

  def __getattr__(self, attr):
    '''
    Call the correspoding wrapper method to handle
    the in-memory caching of the CouchedFilesytem results.
    '''

    def cachedSysCallWrapper(*args, **kws):
      '''
      Wrapper method that manage the in-memory cache of documents.
      For each type of call to CouchedFilesytem api, some cached
      copy are created/update/removed.

      This wrapper also switch from _couchedLocal to remote
      according to the 'usefs' keyword, and replicate documents
      on the remote databse when necessary.
      '''

      self._debug('Calling \'%s\', args %s, kws %s' % (attr, args, kws))

      if ((kws.has_key('usefs') and kws.pop('usefs')) or attr in ('populate',)):
        couchedfs = tsumufs.fsMount
      else:
        couchedfs = self._couchedLocal

      member = getattr(couchedfs, attr)
      op = getattr(member, "op", "read")

      # Return a CouchedFile object, and caching its document
      if attr in ('open'):
        path = args[0]
        flags = args[1]

        couchedfile = member(*args, **kws)

        # If it is a new file, cache in memory the new document
        # and mark the file as cached with its revision.
        if flags & os.O_CREAT:
          self.setCachedRevision(couchedfile.document.id,
                                 couchedfile.document.rev,
                                 couchedfile.document.stats.st_mtime)

        # Override the close method to be able to cache
        # the updated document if the file has been modified.
        function = couchedfile.close
        couchedfile.close = lambda *args, **kwd: \
                              self.cachedFileOpWrapper(couchedfs,
                                                       function,
                                                       *args, **kwd)
        return couchedfile

      # Create/update some documents
      elif op in ('update', 'create'):
        updated = member(*args, **kws)

        rename = False
        for doc in updated:
          if attr not in ('populate'):
            # Cache the new document revision
            self.setCachedRevision(doc.id, doc.rev, doc.stats.st_mtime)

        return updated

      else:
        return member(*args, **kws)

    if hasattr(self._couchedLocal, attr) and \
         type(getattr(self._couchedLocal, attr)) == new.instancemethod:
      return cachedSysCallWrapper

    # Raise attribute error
    else:
      return getattr(self._couchedLocal, attr)


@extendedattribute('root', 'tsumufs.fs-overlay')
def xattr_fsOverlay(type_, path, value=None):
  if not value:
    return repr(FileSystemOverlay)

  return -errno.EOPNOTSUPP

@extendedattribute('any', 'tsumufs.is-owner')
def xattr_isOwner(type_, path, value=None):
  if not value:
    # TODO: do not use os.getuid()
    return str(int(int(tsumufs.fsOverlay[path].uid) == int(os.getuid())))

  return -errno.EOPNOTSUPP

