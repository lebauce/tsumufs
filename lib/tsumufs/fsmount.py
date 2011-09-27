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
import errno
import sys
import stat
import thread
import threading
import dataregion

import tsumufs


class FSMountError(Exception):
  pass


class FSMount(tsumufs.Debuggable):
  '''

  This object is responsible for accessing files and data in the File System
  mount. It is also responsible for setting the connectedEvent to
  False in case of an File System access error.
  '''

  _fileLocks = {}

  def __init__(self):
    pass

  def lockFile(self, filename):
    '''
    Method to lock a file. Blocks if the file is already locked.

    Args:
      filename: The full pathname of the file to lock.

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
      filename: The full pathname of the file to unlock.

    Returns:
      A boolean value.
    '''

#       tb = self._getCaller()
#       self._debug('Unlocking file %s (from: %s(%d): in %s <%d>).'
#                   % (filename, tb[0], tb[1], tb[2], thread.get_ident()))

    self._fileLocks[filename].release()

  def fsMountCheckOK(self):
    '''
    Method to verify that the File System server is available and mounted
    '''

    if self.pingServerOK() and os.path.ismount(tsumufs.fsMountPoint):
      tsumufs.fsAvailable.set()
      return True

    tsumufs.fsAvailable.clear()
    return False

  def readFileRegion(self, filename, start, end):
    '''
    Method to read a region of a file from the File System mount. Additionally
    adds the inode to filename mapping to the InodeMap singleton.

    Args:
      filename: the complete pathname to the file to read from.
      start: the beginning offset to read from.
      end: the ending offset to read from.

    Returns:
      A string containing the data read.

    Raises:
      file systemMountError: An error occurred during an File system call which is
        unrecoverable.
      RangeError: The start and end provided are invalid.
      IOError: Usually relating to permissions issues on the file.
    '''

    try:
      self.lockFile(filename)

      try:
        fp = self.open(filename, os.O_RDONLY)
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
          # tsumufs.fsAvailable.notifyAll()
          raise tsumufs.FSMountError()
        else:
          raise

    finally:
      self.unlockFile(filename)

  def writeFileRegion(self, filename, start, end, data):
    '''
    Method to write a region to a file on the file system mount. Additionally
    adds the resulting inode to filename mapping to the InodeMap
    singleton.

    Args:
      filename: the complete pathname to the file to write to.
      start: the beginning offset to write to.
      end: the ending offset to write to.
      data: the data to write.

    Raises:
      FSMountError: An error occurred during an file system call.
      RangeError: The start and end provided are invalid.
      OSError: Usually relating to permissions on the file.
    '''

    if end - start > len(data):
      raise dataregion.RangeError('The length of data specified in start and '
                                  'end does not match the data length.')

    try:
      self.lockFile(filename)

      try:
        fp = self.open(filename, os.O_APPEND)
        fp.seek(start)
        fp.write(data)
        fp.close()

      except OSError, e:
        if e.errno in (errno.EIO, errno.ESTALE):
          self._debug('Got %s while writing a region to %s.' %
                      (str(e), filename))
          self._debug('Triggering a disconnect.')

          tsumufs.fsAvailable.clear()
          # tsumufs.fsAvailable.notifyAll() # TODO: AttributeError

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
        self.ftruncate(fusepath, newsize)

      except OSError, e:
        if e.errno in (errno.EIO, errno.ESTALE):
          self._debug('Got %s while writing a region to %s.' %
                      (str(e), fspath))
          self._debug('Triggering a disconnect.')

          tsumufs.fsAvailable.clear()
          # tsumufs.fsAvailable.notifyAll()

          raise tsumufs.FSMountError()
        else:
          raise

    finally:
      self.unlockFile(fusepath)

  def mount(self):
    '''
    Quick and dirty method to actually mount the real file system connection
    somewhere else on the filesystem. For now, this just sheNonells out to
    the mount(8) command to do its dirty work.
    '''

    cmd = tsumufs.fsMountCmd
    if cmd == None:
        self._debug('Mount of file system managed by peer')
        return False

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
      if tsumufs.mountOptions != None:
        cmd += ' -o ' + tsumufs.mountOptions

      self._debug('Mount method: %s.' % tsumufs.fsMountMethod)
      if tsumufs.fsMountMethod == "default":
        cmd += ' ' + tsumufs.mountSource + ' ' + tsumufs.fsMountPoint

      elif tsumufs.fsMountMethod == "fstab":
        cmd = tsumufs.fsMountCmd + ' ' + tsumufs.fsMountPoint

      elif tsumufs.fsMountMethod == "sudo":
        cmd = '/usr/bin/sudo -u root ' + cmd + ' ' + tsumufs.mountSource + ' ' + tsumufs.fsMountPoint

      elif tsumufs.fsMountMethod == "autofs":
        self._debug('Returning True as mount method is autofs.')
        return True

      else:
        raise Exception("Unknown mount method '%s'", tsumufs.fsMountMethod)

      self._debug(cmd)
      rc = os.system(cmd) >> 8
    except OSError, e:
      self._debug('Mount of file system failed: %s.' % os.strerror(e.errno))
      return False
    else:
      if rc != 0:
        self._debug('Mount of file system failed -- mount returned nonzero: %s' % rc)
        return False
      else:
        self._debug('Mount of file system succeeded.')
        return True

  def unmount(self):
    '''
    Quick and dirty method to actually UNmount the real file system connection
    somewhere else on the filesystem.
    '''

    cmd = tsumufs.fsUnmountCmd
    if cmd == None:
        self._debug('Umount of file system managed by peer')
        return False

    self._debug('Unmounting file system mount from %s' %
               tsumufs.fsMountPoint)
    rc = os.system('%s %s' % (cmd, tsumufs.fsMountPoint))

    if rc != 0:
      self._debug('Unmount of file system failed.')
      return False
    else:
      self._debug('Unmount of file system succeeded.')
      return True

