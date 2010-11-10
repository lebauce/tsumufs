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
import os.path
import sys
import stat
import time
import errno
import threading

import fuse

import tsumufs
from extendedattributes import extendedattribute
from metrics import benchmark

from ufo.database import DocumentHelper


class SyncConflictError(Exception):
  '''
  Class to represent a syncronization conflict.
  '''
  pass


class QueueValidationError(Exception):
  '''
  Class to represent a SyncLog queue validation error.
  '''
  pass

# syncqueue:
#  ( #<SyncItem{ type: 'new,
#      ftype: 'file|'dir|'socket|'fifo|'dev,
#      dtype: 'char|'block,
#      major: uint32,
#      minor: uint32,
#      filename: "..." },
#    { type: 'link,
#      inode: uint64,
#      filename: "..." },
#    { type: 'unlink,
#      filename: "..." },
#    { type: 'change,
#      inode: unit64 },
#    { type: 'rename,
#      old_fname: "...",
#      new_fname: "..." },
#    ... )


class SyncLog(tsumufs.Debuggable):
  '''
  Class that implements a queue for storing synclog entries in. Used
  primarily by the SyncThread class.
  '''

  _syncDocuments = None
  _syncChanges   = None
  _fileChanges   = None
  _changesSeqs   = None

  _lock          = threading.RLock()


  @benchmark
  def __init__(self):
    self._syncDocuments = DocumentHelper(tsumufs.SyncDocument,
                                         tsumufs.dbName,
                                         batch=True)
    self._syncChanges   = DocumentHelper(tsumufs.SyncChangeDocument,
                                         tsumufs.dbName,
                                         batch=True)
    self._fileChanges   = DocumentHelper(tsumufs.FileChangeDocument,
                                         tsumufs.dbName,
                                         batch=True)
    self._changesSeqs   = DocumentHelper(tsumufs.ChangesSequenceDocument,
                                         tsumufs.dbName,
                                         batch=True)

  def checkpoint(self):
    '''
    Checkpoint the synclog to disk.
    '''

    self._syncChanges.commit()

  @benchmark
  def isNewFile(self, fusepath):
    '''
    Check to see if fusepath is a file the user created locally.

    Returns:
      Boolean

    Raises:
      Nothing
    '''

    try:
      self._lock.acquire()

      self._syncChanges.by_filename_and_type(key=[fusepath, 'new'], pk=True)
      return True

    except tsumufs.DocumentException, e:
      return False

    finally:
      self._lock.release()

  @benchmark
  def isUnlinkedFile(self, fusepath):
    '''
    Check to see if fusepath is a file that was unlinked previously.

    Returns:
      Boolean

    Raises:
      Nothing
    '''

    try:
      self._lock.acquire()
      is_unlinked = False

      for change in self._syncChanges.by_date():
        if change.filename == fusepath:
          if change.type == 'unlink':
            is_unlinked = True
          else:
            is_unlinked = False

      return is_unlinked

    finally:
      self._lock.release()

  @benchmark
  def isFileDirty(self, fusepath):
    '''
    Check to see if the cached copy of a file is dirty.

    Note that this does a shortcut test -- if the file in local cache exists and
    the file on fs does not, then we assume the cached copy is
    dirty. Otherwise, we have to check against the synclog to see what's changed
    (if at all).

    Returns:
      Boolean true or false.

    Raises:
      Any error that might occur during an os.lstat(), aside from ENOENT.
    '''

    try:
      self._lock.acquire()

      self._syncChanges.by_filename(key=fusepath, pk=True)
      return True

    except tsumufs.DocumentException, e:
      return False

    finally:
      self._lock.release()

  @benchmark
  def addNew(self, type_, **params):
    '''
    Add a change for a new file to the queue.

    Args:
      type: A string of one one of the following: 'file', 'dir',
        'symlink', 'socket', 'fifo', or 'dev'.
      params: A hash of parameters used to complete the data
        structure. If type is set to 'dev', this structure must have
        the following members: dev_type (set to one of 'char' or
        'block'), and major and minor, representing the major and minor
        numbers of the device being created.

    Raises:
      TypeError: When data passed in params is invalid or missing.
    '''

    self._debug('addNew path %s' % params['filename'])
    try:
      self._lock.acquire()

      params['file_type'] = type_
      self._appendToSyncQueue('new', **params)

    finally:
      self._lock.release()

  @benchmark
  def addLink(self, filename):

    self._debug('addLink path %s' % filename)
    try:
      self._lock.acquire()

      self._appendToSyncQueue('link', filename=filename)

    finally:
      self._lock.release()

  @benchmark
  def addUnlink(self, filename, type_):
    '''
    Add a change to unlink a file. Additionally removes all previous changes in
    the queue for that filename.

    Args:
      filename: the filename to unlink.

    Raises:
      Nothing.
    '''

    self._debug('addUnlink path %s' % filename)
    try:
      self._lock.acquire()

      # Walk the queue backwards (newest to oldest) and remove any changes
      # relating to this filename. We can mutate the list because going
      # backwards, index numbers don't change after deletion (IOW, we're always
      # deleting the tail).

      is_new_file = self.isNewFile(filename)

      if self.isFileDirty(filename):
        for change in self._syncChanges.by_date(descending=True):
          if change.type in ('new', 'change', 'link'):
            if change.filename == filename:
              # Remove the possible associated file change
              try:
                filechange = self._fileChanges.by_syncchangeid(key=change.id, pk=True)

                filechange.clearDataChanges()
                self._fileChanges.delete(filechange)

              except tsumufs.DocumentException, e:
                self._debug('No filechange found for %s to delete' % filename)

              # Remove the change
              self._removeFromSyncQueue(change)

          if change.type in ('rename'):
            if change.new_fname == filename:
              # Okay, follow the rename back to remove previous changes. Leave
              # the rename in place because the destination filename is a change
              # we want to keep.
              filename = change.old_fname

              # TODO(jtg): Do we really need to keep these renames? Unlinking
              # the final destination filename in the line of renames is akin to
              # just unlinking the original file in the first place. Ie:
              #
              #      file -> file' -> file'' -> unlinked
              #
              # After each successive rename, the previous file ceases to
              # exist. Once the final unlink is called, the previous sucessive
              # names no longer matter. Technically we could replace all of the
              # renames with a single unlink of the original filename and
              # achieve the same result.

              # Remove the rename change until bugs detected
              self._removeFromSyncQueue(change)

      # Now add an additional syncitem to the queue to represent the unlink if
      # it wasn't a file that was created on the cache by the user.
      if not is_new_file:
        self._appendToSyncQueue('unlink', file_type=type_, filename=filename)

    finally:
      self._lock.release()

  @benchmark
  def addChange(self, fname, start, end, data):

    self._debug('addChange path %s' % fname)
    try:
      self._lock.acquire()

      try:
        syncchange = self._syncChanges.by_filename_and_type(key=[fname, 'change'],
                                                            pk=True)
        filechange = self._fileChanges.by_syncchangeid(key=syncchange.id, pk=True)

      except tsumufs.DocumentException, e:
        syncchange = self._appendToSyncQueue('change', filename=fname)
        filechange = self._fileChanges.create(syncchangeid=syncchange.id)

      filechange.addDataChange(start, end, data)

    finally:
      self._lock.release()

  @benchmark
  def addMetadataChange(self, fname, mode=False, uid=False, gid=False, times=False):
    '''
    Metadata changes are synced automatically when there is a SyncItem change
    for the file. So all we need to do here is represent the metadata changes
    with a SyncItem and an empty InodeChange.
    '''

    self._debug('addMetaDataChange path %s' % fname)
    try:
      self._lock.acquire()

      try:
        syncchange = self._syncChanges.by_filename_and_type(key=[fname, 'change'],
                                                            pk=True)
        filechange = self._fileChanges.by_syncchangeid(key=syncchange.id, pk=True)

      except tsumufs.DocumentException, e:
        syncchange = self._appendToSyncQueue('change', filename=fname)
        filechange = self._fileChanges.create(syncchangeid=syncchange.id)

      filechange.addMetaDataChange(mode=mode, uid=uid, gid=gid, times=times)
      self._fileChanges.update(filechange)

    finally:
      self._lock.release()

  @benchmark
  def truncateChanges(self, fusepath, size):

    self._debug('truncateChanges path %s' % fusepath)
    try:
      self._lock.acquire()

      for change in self._syncChanges.by_filename_and_type(key=[fusepath, 'change']):
        try:
          filechange = self._fileChanges.by_syncchangeid(key=change.id, pk=True)

          self._debug('Truncating data in %s' % repr(change))
          filechange.truncateLength(size)

        except tsumufs.DocumentException, e:
          self._debug('No filechange found for %s to truncate' % fusepath)
          pass

    finally:
      self._lock.release()

  @benchmark
  def addRename(self, old, new):

    self._debug('addRename old %s, new %s' % (old, new))
    try:
      self._lock.acquire()

      if self.isNewFile(old):
        changes = []

        # Change the filename of all sync changes corresponding to this file
        # TODO: only rename the filename of sync changes made after the 'new'
        for change in self._syncChanges.by_filename(key=old):
          change.filename = new
          changes.append(change)

        # If the renamed document is a directory, change the filename of all
        # sync changes corresponding to files located in the directory subtree.
        # TODO: only rename the filename of sync changes made after the 'new'
        renamed = tsumufs.fsOverlay[new]
        if stat.S_ISDIR(renamed.mode):
          for change in self._syncChanges.by_dir_prefix(key=old):
            change.filename = change.filename.replace(old, new, 1)
            changes.append(change)

        self._syncChanges.update(changes)

      else:
        self._appendToSyncQueue('rename', old_fname=old, new_fname=new)

    finally:
      self._lock.release()

  @benchmark
  def popChanges(self):
    # Firstly retrieve the number of the last consumed changes sequence
    try:
      last_seq = self._changesSeqs.by_consumer(key="tsumufs-sync-thread", pk=True)
    except tsumufs.DocumentException, e:
      last_seq = self._changesSeqs.create(consumer="tsumufs-sync-thread",
                                          seq_number=0)

    self._debug('Waiting for changes since seq %d' % last_seq.seq_number)

    for event in self._syncChanges.changes(feed="continuous",
                                           since=last_seq.seq_number,
                                           timeout=5000):
      if not event.has_key('id'):
        continue

      if event.get('deleted'):
        continue

      filechange = None
      syncitem   = self._syncChanges.by_id(key=event['id'], pk=True)

      self._debug('Syncitem retrieved from a new change; %s' % syncitem)

      # Grab the associated inode changes if there are any.
      if syncitem.type == 'change':
        try:
          # Acquire the lock to be sure that the FileChange associated with
          # this SyncChange has been created.
          self._lock.acquire()

          filechange = self._fileChanges.by_syncchangeid(key=syncitem.id, pk=True)
        except tsumufs.DocumentException, e:
          self._debug('No filechange found for %s' % syncitem.filename)

        finally:
          self._lock.release()

      # Ensure the appropriate locks are locked
      if syncitem.type in ('new', 'link', 'unlink', 'change'):
        tsumufs.cacheManager.lockFile(syncitem.filename)
        tsumufs.fsMount.lockFile(syncitem.filename)

      elif syncitem.type in ('rename'):
        tsumufs.cacheManager.lockFile(syncitem.new_fname)
        tsumufs.fsMount.lockFile(syncitem.new_fname)
        tsumufs.cacheManager.lockFile(syncitem.old_fname)
        tsumufs.fsMount.lockFile(syncitem.old_fname)

      syncitem.seq_number = event['seq']
      self._debug('Yielding (syncchange, filechange), seq %d: (%s,%s)'
                  % (event['seq'], syncitem, str(filechange)))

      yield (syncitem, filechange)

  @benchmark
  def finishedWithChange(self, syncitem, remove_item=True):
    self._lock.acquire()

    try:
      # Ensure the appropriate locks are unlocked
      if syncitem.type in ('new', 'link', 'unlink', 'change'):
        tsumufs.cacheManager.unlockFile(syncitem.filename)
        tsumufs.fsMount.unlockFile(syncitem.filename)

      elif syncitem.type in ('rename'):
        tsumufs.cacheManager.unlockFile(syncitem.new_fname)
        tsumufs.fsMount.unlockFile(syncitem.new_fname)
        tsumufs.cacheManager.unlockFile(syncitem.old_fname)
        tsumufs.fsMount.unlockFile(syncitem.old_fname)

      # Replicate the change to remote database,
      # remove the item from the synclog.
      if remove_item:
        if syncitem.type == 'unlink':
          try:
            # It's a pity... Replication of documents by id do not handle
            # the document deletion. Only the full replication handle it,
            # we need to have a look on replication of sequence numbers.
            remote = tsumufs.DocumentHelper(tsumufs.SyncDocument, tsumufs.dbName,
                                            *tsumufs.dbRemote.split(':'))

            self._debug('Deleting document %s' % (syncitem.id))
            remote.delete(remote.by_path(key=syncitem.filename, pk=True))

          except tsumufs.DocumentException, e:
            self._debug('Unable to replicate changes to remote couchdb: %s'
                        % str(e))

        else:
          if syncitem.type == 'change':
            try:
              change = self._fileChanges.by_syncchangeid(key=syncitem.id, pk=True)

              change.clearDataChanges()
              self._fileChanges.delete(change)

            except tsumufs.DocumentException, e:
              self._debug('No filechange found for %s' % syncitem.filename)

            docs = [ tsumufs.fsOverlay[syncitem.filename].id ]

          elif syncitem.type == 'new':
            docs = [ tsumufs.fsOverlay[syncitem.filename].id ]

          elif syncitem.type == 'rename':
            renamed = tsumufs.fsOverlay[syncitem.new_fname]

            docs = [ renamed.id ]
            if stat.S_ISDIR(renamed.mode):
              doc_helper = tsumufs.fsOverlay._couchedLocal.doc_helper
              for doc in doc_helper.by_dir_prefix(key=syncitem.new_fname):
                docs.append(doc.id)

          elif syncitem.type == 'link':
            # TODO: implements this
            docs = []

          try:
            self._debug('Replicating %d documents: %s' % (len(docs), ", ".join(docs)))
            self._syncDocuments.replicate("http://%s/%s" % (tsumufs.dbRemote, tsumufs.dbName),
                                          doc_ids=docs)

          except tsumufs.DocumentException, e:
            self._debug('Unable to replicate changes to remote db: %s'
                        % str(e))

        self._debug('Last sequence number %s' % syncitem.seq_number)
        last_seq = self._changesSeqs.by_consumer(key="tsumufs-sync-thread", pk=True)
        last_seq.seq_number = syncitem.seq_number
        self._changesSeqs.update(last_seq)

        self._removeFromSyncQueue(syncitem)

    finally:
      self._lock.release()

  def _appendToSyncQueue(self, type, **params):
    params['type'] = type
    params['date'] = time.time()

    change = self._syncChanges.create(**params)

    return change

  def _removeFromSyncQueue(self, change):
    self._syncChanges.delete(change)


# hash of inode changes:
#   { <inode number>: { data: ( { data: "...",
#                                 start: <start position>,
#                                 end: <end position>,
#                                 length: <length of data> },
#                               ... ),
#                       ctime: time_t uint64,
#                       mtime: time_t uint64,
#                       uid: uint32,
#                       gid: uint32,
#                       symlink_dest_path: "..." },
#     ... }


@extendedattribute('root', 'tsumufs.synclog-contents')
def xattr_synclogContents(type_, path, value=None):
  if value:
    return -errno.EOPNOTSUPP

  return str(tsumufs.syncLog)
