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

  @ViewField.define('cachedrevision')
  def by_fileid(doc):
      if doc['doctype'] == "CachedRevisionDocument":
          yield doc['fileid'], doc


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

  _couchedLocal = None              # Couched filesystem object for read/write access
                                    # to the cached filesystem.

  _couchedRemote = None             # Couched filesystem object for read/write access
                                    # to the remote filesystem.

  _localRevisions = None            # Revisions of the cached copies of documents.

  _cachedMetaDatas = CacheDict(60)  # Dict to keep database docs in memory during
  _cachedRevisions = CacheDict(60)  # a system call sequence to avoid database
                                    # access overheads.

  def __init__(self):
    self.replicationTaskId = 0
    self._couchedLocal = CouchedFileSystem(tsumufs.cachePoint,
                                           tsumufs.dbName,
                                           db_metadatas=True)
    self._couchedRemote = CouchedFileSystem(tsumufs.fsMountPoint,
                                            tsumufs.dbName)

    # Override _get method to cache documents or use cached copy
    self._couchedLocal._get = self._get

    self._localRevisions = DocumentHelper(CachedRevisionDocument, tsumufs.dbName,
                                          batch=True)

  def __str__(self):
    return ('<FileSystemOverlay %d cached metadatas, %s cached revisions, : %s, %s >'
            % (len(self._cachedMetaDatas), len(self._cachedRevisions),
               self._cachedMetaDatas, self._cachedRevisions))

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
                                                       spnego=tsumufs.spnego, reverse=True, continuous=True,
                                                       filter="replication/nodesigndocs")
      self.replicationTaskId = result["_local_id"]
      return self.replicationTaskId

    except tsumufs.DocumentException, e:
      self._debug('Unable to replicate changes from remote couchdb: %s'
                  % str(e))

  def stopReplication(self):
    if self.replicationTaskId:
      try:
        self._couchedLocal.doc_helper.replicate(tsumufs.dbName, tsumufs.dbRemote,
                                                spnego=tsumufs.spnego, reverse=True, continuous=True,
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
        revision = self._localRevisions.by_fileid(key=fileid, pk=True).revision

        self._debug('Caching revision in memory (%s -> %s)' % (fileid, revision))
        self._cachedRevisions.cache(fileid, revision)

      return self._cachedRevisions.get(fileid)

    except DocumentException, e:
      raise KeyError(e.message)

    finally:
      self._cachedRevisions.release()

  def setCachedRevision(self, fileid, revision):
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

        self._localRevisions.update(cacherev)

      except DocumentException, e:
        self._localRevisions.create(fileid=fileid, revision=revision)

      # Update the in-memory cached copy
      self._cachedRevisions.cache(fileid, revision)

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

      self._localRevisions.delete(self._localRevisions.by_fileid(key=fileid,
                                                                 pk=True))
      # Remove the in-memory cached copy
      self._cachedRevisions.invalidate(fileid)

    except DocumentException, e:
      raise KeyError(e.message)

    finally:
      self._cachedRevisions.release()

  def cachedListDirWrapper(self, path):
    '''
    Wrapper method to cache in memory all documents returned
    by a call to 'listdir' to database.
    '''

    for doc in self._couchedLocal.listdir(path):
      try:
        self._cachedMetaDatas.acquire()
        self._cachedMetaDatas.cache(os.path.join(doc.dirpath, doc.filename), doc)
      finally:
        self._cachedMetaDatas.release()

      yield doc

  def cachedFileOpWrapper(self, couchedfs, function, *args, **kws):
    '''
    Wrapper method to cache in memory modified document in
    database by a CouchedFile instance, and cache the new
    revision if the update has been done in the cache.
    '''

    try:
      self._cachedMetaDatas.acquire()

      documents = function.__call__(*args, **kws)

      if documents:
        for doc in documents:
          self._cachedMetaDatas.cache(os.path.join(doc.dirpath, doc.filename), doc)
          self.setCachedRevision(doc.id, doc.rev)

        # If use-fs mode, replicating changes to remote database.
        if couchedfs == self._couchedRemote:
          doc_ids = [ doc.id for doc in documents ]

          try:
            self._debug('Replicating %d documents: %s' % (len(doc_ids), ", ".join(doc_ids)))
            self._couchedLocal.doc_helper.replicate(tsumufs.dbName, tsumufs.dbRemote,
                                                    spnego=tsumufs.spnego, doc_ids=doc_ids)
          except tsumufs.DocumentException, e:
            self._debug('Unable to replicate changes to remote db: %s'
                        % str(e))

    finally:
      self._cachedMetaDatas.release()

  def _get(self, path):
    '''
    Wrapper method to use cached copy of document.
    When the copy is too old, the document is acceded
    on the databse and cached in memory.
    '''

    # The root directory does not exists in the database
    if os.path.abspath(path) == '/':
      return RootSyncDocument(os.lstat(tsumufs.cachePathOf(path)))

    try:
      self._cachedMetaDatas.acquire()

      if self._cachedMetaDatas.isObsolete(path):
        try:
          document = self._couchedLocal.doc_helper.by_path(key=path, pk=True)

        except DocumentException, e:
          self._cachedMetaDatas.cache(path, None)
          raise OSError(errno.ENOENT, os.strerror(errno.ENOENT))

        self._debug('Caching document in memory (%s -> %s)' % (path, document.rev))
        self._cachedMetaDatas.cache(path, document)

      if self._cachedMetaDatas.get(path):
        return self._cachedMetaDatas.get(path)

      raise OSError(errno.ENOENT, os.strerror(errno.ENOENT))

    finally:
      self._cachedMetaDatas.release()

  def __getitem__(self, fusepath):
    '''
    Accessor to get SyncDocument instance referenced
    by fusepath, it contains all metadatas of a file.
    '''
    return self._couchedLocal[fusepath]

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

      This wrapper also switch from _couchedLocal to _couchedRemote
      according to the 'usefs' keyword, and replicate documents
      on the remote databse when necessary.
      '''

      try:
        self._cachedMetaDatas.acquire()

        self._debug('Calling \'%s\', args %s, kws %s' % (attr, args, kws))

        if ((kws.has_key('usefs') and kws.pop('usefs')) or attr in ('populate')):
          couchedfs = self._couchedRemote
        else:
          couchedfs = self._couchedLocal

        # Return a single element without caching
        if attr in ('stat'):
          return getattr(couchedfs, attr).__call__(*args, **kws)

        # Return a CouchedFile object, and caching its document
        elif attr in ('open'):
          path = args[0]
          flags = args[1]

          couchedfile = getattr(couchedfs, attr).__call__(*args, **kws)

          # If it is a new file, cache in memory the new document
          # and mark the file as cached with its revision.
          if flags & os.O_CREAT:
            self._cachedMetaDatas.cache(path, couchedfile.document)
            self.setCachedRevision(couchedfile.document.id, couchedfile.document.rev)

          # Override the close method to be able to cache
          # the updated document if the file has been modified.
          function = couchedfile.close
          couchedfile.close = lambda *args, **kwd: \
                                self.cachedFileOpWrapper(couchedfs,
                                                         function,
                                                         *args, **kwd)
          return couchedfile

        # Remove a document
        elif attr in ('unlink', 'rmdir'):
          getattr(couchedfs, attr).__call__(*args, **kws)

          # Invalidate the cached copy if exists
          path = args[0]
          if self._cachedMetaDatas.has_key(path):
            self._cachedMetaDatas.invalidate(path)

          # If use-fs mode, deleting manually the document on remote database.
          if couchedfs == self._couchedRemote:
            try:
              # It's a pity... Replication of documents by id do not handle
              # the document deletion. Only the full replication handle it,
              # we need to have a look on replication of sequence numbers.
              remote = tsumufs.DocumentHelper(tsumufs.SyncDocument, tsumufs.dbName,
                                              tsumufs.dbRemote, spnego=tsumufs.spnego)

              self._debug('Deleting document %s on %s' % (path, tsumufs.dbRemote))
              remote.delete(remote.by_path(key=path, pk=True))

            except tsumufs.DocumentException, e:
              self._debug('Unable to replicate changes to remote couchdb: %s'
                          % str(e))

        # Create/update some documents
        else:
          updated = getattr(couchedfs, attr).__call__(*args, **kws)

          rename = False
          for doc in updated:
            # Cache document into memory
            self._cachedMetaDatas.cache(os.path.join(doc.dirpath, doc.filename), doc)

            # Invalidate old copies if the path changed
            if attr in ('rename'):
              # rename(self, old, new)
              old = args[0]
              new = args[1]

              if not rename:
                oldkey = old
                rename = True
              else:
                oldkey = os.path.join(doc.dirpath.replace(new, old, 1),
                                      doc.filename)

              if self._cachedMetaDatas.has_key(oldkey):
                self._cachedMetaDatas.invalidate(oldkey)

            if attr not in ('populate'):
              # Cache the new document revision
              self.setCachedRevision(doc.id, doc.rev)

          # If use-fs mode, replicating changes to remote database.
          if couchedfs == self._couchedRemote:
            doc_ids = [ doc.id for doc in updated ]

            try:
              self._debug('Replicating %d documents: %s' % (len(doc_ids), ", ".join(doc_ids)))
              self._couchedLocal.doc_helper.replicate(tsumufs.dbName, tsumufs.dbRemote,
                                                      spnego=tsumufs.spnego, doc_ids=doc_ids)
            except tsumufs.DocumentException, e:
              self._debug('Unable to replicate changes to remote db: %s'
                          % str(e))

      finally:
        self._cachedMetaDatas.release()

    # Yield some documents
    if attr in ('listdir'):
      return self.cachedListDirWrapper

    elif hasattr(self._couchedLocal, attr):
      return cachedSysCallWrapper

    # Raise attribute error
    else:
      return getattr(self._couchedLocal, attr)


class RootSyncDocument(SyncDocument):
  '''
  Class that represent root directory document.
  '''

  def __init__(self, stats):
    fixedfields = { 'filename' : "/",
                    'dirpath'  : "",
                    'uid'      : tsumufs.rootUID,
                    'gid'      : tsumufs.rootGID,
                    'mode'     : tsumufs.rootMode | stat.S_IFDIR,
                    'type'     : "application/x-directory",
                    'stats'    : stats }

    super(RootSyncDocument, self).__init__(**fixedfields)

    self['_id'] = "00000000000000000000000000000000"
    self['_rev'] = "0-0123456789abcdef0123456789abcdef"


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
