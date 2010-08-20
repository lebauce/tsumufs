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

'''TsumuFS, a fs-based caching filesystem.'''

import os
import errno
import threading
import cPickle
import magic

import tsumufs
from extendedattributes import extendedattribute


class PermissionsOverlay(tsumufs.Debuggable):
  '''
  Class that provides management for permissions of files in the cache.
  '''

  _lock = None

  overlay = {}     # A hash of inode numbers to FilePermission
                   # objects. This is used to mimic the proper file
                   # permissions on disk while the local filesystem
                   # cannot actually provide these without screwing up
                   # the SyncThread. As a result, we store this to disk
                   # in a serialized format alongside the synclog.

  _magic = None    # LibMagic object for mimetypes support

  _cacheDb = None  # Database object

  _cacheDbTables = { "file"    : [ "inode", "filename", "directory", "uid", "gid", "mode", "type" ],
                     "extattr" : [ "id" ] }

  _getTablesQuery = "SELECT name FROM sqlite_master WHERE type='table'"

  def __init__(self):
    self._lock = threading.Lock()

    try:
      fp = open(tsumufs.permsPath, 'rb')
      self.overlay = cPickle.load(fp)
      fp.close()
    except IOError, e:
      if e.errno != errno.ENOENT:
        raise

    self._cacheDb = tsumufs.DatabaseHelper(tsumufs.cacheDbPath)
    existingTables = self._cacheDb.execute(self._getTablesQuery)

    # Check all required tables
    tables = self._cacheDbTables.keys()[:]
    for table in existingTables:
      tables.remove(table[0])

    if tables:
      self._debug('Following tables not found: %s. Initializing database.'
                  % str(tables))
      self._initilizeCacheDatabase()

    self._magic = magic.open(magic.MAGIC_MIME)
    self._magic.load()

  def _initilizeCacheDatabase(self):
    """
    Build database from scratch, create empty required tables.
    Dynamically build the script according to objects attrs.
    """

    for table in self._cacheDbTables:
      try:
        self._cacheDb.execute("DROP TABLE '%s'" % table)
      except:
        # Table does not exists
        pass

    createDbScript = ""
    for table in self._cacheDbTables:
      createDbScript = createDbScript + ("create table %s(" % table)

      for field in self._cacheDbTables[table]:
        createDbScript = createDbScript + ("%s" % field)

        if field != self._cacheDbTables[table][-1]:
          createDbScript = createDbScript + ','

      createDbScript = createDbScript + ");\n"

    self._cacheDb.execute(createDbScript, script=True)

  def __str__(self):
    return '<PermissionsOverlay %s>' % str(self.overlay)

  def _checkpoint(self):
    '''
    Checkpoint the permissions overlay to disk.
    '''

    fp = open(tsumufs.permsPath, 'wb')
    cPickle.dump(self.overlay, fp)
    fp.close()

  def _getFileInum(self, fusepath):
    '''
    Return the inode number of the file specified in the cache.

    Returns:
      The inode number.

    Raises:
      OSError
    '''

    cachepath = tsumufs.cachePathOf(fusepath)
    inum = os.lstat(cachepath).st_ino

    return inum

  def getPerms(self, fusepath):
    '''
    Return a FilePermission object that contains the uid, gid, and mode of the
    file in the cache. Expects a fusepath and converts that to a cachepath
    directly by itself.

    Returns:
      A FilePermission instance.

    Raises:
      KeyError, OSError
    '''

    try:
      self._lock.acquire()

      inum = self._getFileInum(fusepath)
      return self.overlay[inum]

    finally:
      self._lock.release()

  def getPermsFromQuery(self, query):
    '''
    Return a result tuple according to query.

    Returns:
      Tuple.
    '''

    # TODO:
    # Returning a FilePermission object list,
    # Do not use sql queries, use a filtering struct to represent
    # which FilePermission objects we want among all.
    return self._cacheDb.execute(query)

  def setPerms(self, fusepath, uid, gid, mode):
    '''
    Store a new FilePermission object, indexed by it's inode number.

    Returns:
      Nothing

    Raises:
      Nothing
    '''

    try:
      self._lock.acquire()
      inum = self._getFileInum(fusepath)
      mimetype = str(self._magic.file(tsumufs.cachePathOf(fusepath)).split(";")[0])

      if self.overlay.has_key(inum):
        query = "UPDATE file SET uid=%d, gid=%d, mode=%d, type='%s' WHERE inode=%d" % \
                (uid, gid, mode, mimetype, inum)
      else:
        query = "INSERT INTO file VALUES (%d, '%s','%s',%d,%d,%d,'%s')" % \
                (inum, os.path.basename(fusepath), os.path.dirname(fusepath),
                 uid, gid, mode, mimetype)

      perms = tsumufs.FilePermission()
      perms.uid = uid
      perms.gid = gid
      perms.mode = mode

      self.overlay[inum] = perms
      self._checkpoint()

      self._cacheDb.execute(query, commit=True)

    finally:
      self._lock.release()

  def removePerms(self, inum):
    '''
    Remove a FilePermission object from the overlay, based upon it's inode
    number.

    Returns:
      Nothing

    Raises:
      KeyError
    '''

    try:
      self._lock.acquire()

      del self.overlay[inum]
      self._checkpoint()

      self._cacheDb.execute("DELETE FROM file WHERE inode=%d" % inum)

    finally:
      self._lock.release()

  def hasPerms(self, fusepath):
    '''
    Check if overlay has fusepath key.

    Returns:
      Boolean
    '''
    return self.overlay.has_key(fusepath)

@extendedattribute('root', 'tsumufs.perms-overlay')
def xattr_permsOverlay(type_, path, value=None):
  if not value:
    return repr(PermissionsOverlay.overlay)

  return -errno.EOPNOTSUPP
