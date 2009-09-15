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

'''TsumuFS, a FS-based caching filesystem.'''

import os
import errno
import sys
import stat
import syslog
import thread
import threading
import dataregion

import tsumufs


class FSMountError(Exception):
  pass


class FSMount(tsumufs.Debuggable):
  '''
  Represents the FS mount iself.

  This object is responsible for accessing files and data in the FS
  mount. It is also responsible for setting the connectedEvent to
  False in case of an FS access error.
  '''

  _fileLocks = {}

  def __init__(self):
    pass

  def lockFile(self, filename):
    '''
    Method to lock a file. Blocks if the file is already locked.

    Args:
      filename: The complete pathname to the file to lock.

    Returns:
      A boolean value.
    '''


    try:
      lock = self._fileLocks[filename]
    except KeyError:
      lock = self._fileLocks.setdefault(filename, threading.RLock())

    lock.acquire()

  def unlockFile(self, filename):
    '''
    Method to unlock a file.

    Args:
      filename: The complete pathname to the file to unlock.

    Returns:
      A boolean value.
    '''

#       tb = self._getCaller()
#       self._debug('Unlocking file %s (from: %s(%d): in %s <%d>).'
#                   % (filename, tb[0], tb[1], tb[2], thread.get_ident()))

    self._fileLocks[filename].release()


  def fsCheckOK(self):
    '''
    Method to verify that the FS server is available and mounting
    '''
    if self.pingServerOK() and os.path.ismount(tsumufs.fsMountPoint):
      tsumufs.fsAvailable.set()  
      return True
    else:
      tsumufs.fsAvailable.clear()
      return False

  def readFileRegion(self, filename, start, end):
    '''
    Method to read a region of a file from the FS mount. Additionally
    adds the inode to filename mapping to the InodeMap singleton.

    Args:
      filename: the complete pathname to the file to read from.
      start: the beginning offset to read from.
      end: the ending offset to read from.

    Returns:
      A string containing the data read.

    Raises:
      FSMountError: An error occurred during an FS call which is
        unrecoverable.
      RangeError: The start and end provided are invalid.
      IOError: Usually relating to permissions issues on the file.
    '''

    try:
      self.lockFile(filename)

      try:
        fspath = tsumufs.fsPathOf(filename)

        fp = open(fspath, 'r')
        fp.seek(start)
        result = fp.read(end - start)
        fp.close()

        return result

      except OSError, e:
        if e.errno in (errno.EIO, errno.ESTALE):
          self._debug('Got %s while reading a region from %s.' %
                      (str(e), filename))
          self._debug('Triggering a disconnect.')

          tsumufs.fsAvailable.clear()
          tsumufs.fsAvailable.notifyAll()
          raise tsumufs.FSMountError()
        else:
          raise

    finally:
      self.unlockFile(filename)

  def writeFileRegion(self, filename, start, end, data):
    '''
    Method to write a region to a file on the FS mount. Additionally
    adds the resulting inode to filename mapping to the InodeMap
    singleton.

    Args:
      filename: the complete pathname to the file to write to.
      start: the beginning offset to write to.
      end: the ending offset to write to.
      data: the data to write.

    Raises:
      FSMountError: An error occurred during an FS call.
      RangeError: The start and end provided are invalid.
      OSError: Usually relating to permissions on the file.
    '''

    if end - start > len(data):
      raise dataregion.RangeError('The length of data specified in start and '
                                  'end does not match the data length.')

    try:
      self.lockFile(filename)

      try:
        fspath = tsumufs.fsPathOf(filename)

        fp = open(fspath, 'r+')
        fp.seek(start)
        fp.write(data)
        fp.close()

      except OSError, e:
        if e.errno in (errno.EIO, errno.ESTALE):
          self._debug('Got %s while writing a region to %s.' %
                      (str(e), filename))
          self._debug('Triggering a disconnect.')

          tsumufs.fsAvailable.clear()
          tsumufs.fsAvailable.notifyAll() # TODO: AttributeError

          raise tsumufs.FSMountError()
        else:
          raise

    finally:
      self.unlockFile(filename)

  def truncateFile(self, fusepath, newsize):
    '''
    Truncate a file to newsize.
    '''

    try:
      self.lockFile(fusepath)

      try:
        fspath = tsumufs.fsPathOf(fusepath)

        fp = open(fspath, 'r+')
        fp.truncate(newsize)
        fp.close()

      except OSError, e:
        if e.errno in (errno.EIO, errno.ESTALE):
          self._debug('Got %s while writing a region to %s.' %
                      (str(e), fspath))
          self._debug('Triggering a disconnect.')

          tsumufs.fsAvailable.clear()
          tsumufs.fsAvailable.notifyAll()

          raise tsumufs.FSMountError()
        else:
          raise

    finally:
      self.unlockFile(fusepath)

  def mount(self):
    '''
    Quick and dirty method to actually mount the real FS connection
    somewhere else on the filesystem. For now, this just sheNonells out to
    the mount(8) command to do its dirty work.
    '''

    try:
      os.stat(tsumufs.fsMountPoint)
    except OSError, e:
      if e.errno == errno.ENOENT:
        self._debug('Mount point %s was not found -- creating'
                   % tsumufs.fsMountPoint)
        try:
          os.mkdir(tsumufs.fsMountPoint)
        except OSError, e:
          self._debug('Unable to create mount point: %s'
                     % os.strerror(e.errno))
          return False
      elif e.errno == errno.EACCES:
        self._debug('Mount point %s unavailable: %s'
                   % (tsumufs.fsMountPoint,
                      os.strerror(e.errno)))
        return False

    try:
      cmd = tsumufs.fsMountCmd
      if tsumufs.mountOptions != None:
        cmd += ' -o ' + tsumufs.mountOptions
      cmd += ' ' + tsumufs.mountSource + ' ' + tsumufs.fsMountPoint

      self._debug(cmd)
      rc = os.system(cmd) >> 8
    except OSError, e:
      self._debug('Mount of FS failed: %s.' % os.strerror(e.errno))
      return False
    else:
      if rc != 0:
        self._debug('Mount of FS failed -- mount returned nonzero: %s' % rc)
        return False
      else:
        self._debug('Mount of FS succeeded.')
        return True

  def unmount(self):
    '''
    Quick and dirty method to actually UNmount the real FS connection
    somewhere else on the filesystem.
    '''

    self._debug('Unmounting FS mount from %s' %
               tsumufs.fsMountPoint)
    rc = os.system('%s %s' % (tsumufs.fsUnmountCmd, tsumufs.fsMountPoint))

    if rc != 0:
      self._debug('Unmount of FS failed.')
      return False
    else:
      self._debug('Unmount of FS succeeded.')
      return True

    self._debug('Invalidating name to inode map')
    tsumufs.NameToInodeMap.invalidate()
