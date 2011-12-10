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
import shutil
import errno
import stat
import thread
import threading
import time
import random

import tsumufs
from extendedattributes import extendedattribute
from metrics import benchmark


class CacheManager(tsumufs.Debuggable):
  '''
  Class designed to handle management of the cache. All caching
  operations (and decaching operations) are performed here.
  '''

  _fileLocks = {}           # A hash of paths to locks to serialize
                            # access to files in the cache.

  _cacheSpec = {}           # A hash of paths to bools to remember the policy of
                            # whether files or parent directories (recursively)

  @benchmark
  def __init__(self):
    # Install our custom exception handler so that any exceptions are
    # output to the syslog rather than to /dev/null.
    sys.excepthook = tsumufs.syslogExceptHook

    try:
      os.stat(tsumufs.cachePoint)

    except OSError, e:
      if e.errno == errno.ENOENT:
        self._debug('Cache point %s was not found -- creating'
                    % tsumufs.cachePoint)

        try:
          os.mkdir(tsumufs.cachePoint)

        except OSError, e:
          self._debug('Unable to create cache point: %s (exiting)'
                      % os.strerror(e.errno))
          raise e

      elif e.errno == errno.EACCES:
        self._debug('Cache point %s is unavailable: %s (exiting)'
                    % (tsumufs.cachePoint,
                       os.strerror(e.errno)))
        raise e

  @benchmark
  def _checkForFSDisconnect(self, exception, opcodes):
    '''
    '''

    if 'use-fs' in opcodes:
      if exception.errno in (errno.EIO, errno.ESTALE):
        self._debug(('Caught errno %s; fs invalid -- entering disconnected '
                     'mode.') %
                    errno.errorcode[exception.errno])

        tsumufs.fsMount.unmount()
        tsumufs.fsAvailable.clear()

  @benchmark
  def statFile(self, fusepath):
    '''
    Return the stat referenced by fusepath.

    This method locks the file for reading, returns the stat result
    and unlocks the file.

    Returns:
      posix.stat_result

    Raises:
      OSError if there was a problem getting the stat.
    '''
    self.lockFile(fusepath)

    try:
      opcodes = self._genCacheOpcodes(fusepath, for_stat=True)
      self._debug('Opcodes are: %s' % str(opcodes))

      self._validateCache(fusepath, opcodes)

      if 'enoent' in opcodes:
        raise OSError(errno.ENOENT, fusepath, os.strerror(errno.ENOENT))

      self._debug('Stating %s' % fusepath)
      stats = tsumufs.fsOverlay.stat(fusepath)

      self._debug('Returning %s as stats.' % repr(stats))
      return stats

    finally:
      self.unlockFile(fusepath)

  @benchmark
  def du(self, fusepath):
    self.lockFile(fusepath)

    self._debug('Du %s' % fusepath)
    try:
      opcodes = self._genCacheOpcodes(fusepath, for_stat=True)
      self._debug('Opcodes are: %s' % str(opcodes))

      self._validateCache(fusepath, opcodes)

      if 'enoent' in opcodes:
        raise OSError(errno.ENOENT, fusepath, os.strerror(errno.ENOENT))

      return tsumufs.fsOverlay.du(fusepath)

    finally:
      self.unlockFile(fusepath)

  @benchmark
  def fakeOpen(self, fusepath, flags, mode=None, uid=None, gid=None):
    '''
    Attempt to open a file on the local disk.

    Returns:
      None

    Raises:
      OSError on problems opening the file.
    '''

    # Several things to worry about here:
    #
    # In normal open cases where we just want to open the file and not create
    # it, we can just assume the normal read routines, and open from cache if
    # possible.
    #
    # Flags that will give us trouble:
    #
    #   O_CREAT            - Open and create if not there already, no error if
    #                        exists.
    #
    #   O_CREAT | O_EXCL   - Open, create, and error out if the file exists or
    #                        if the path contains a symlink. Error used is
    #                        EEXIST.
    #
    #   O_TRUNC            - Open an existing file, truncate the contents.
    #

    self.lockFile(fusepath)

    try:
      opcodes = self._genCacheOpcodes(fusepath)

      if flags & os.O_CREAT:
        if 'enoent' in opcodes:
          self._debug('O_CREAT and enoent in opcodes. Modifying.')
          opcodes.remove('enoent')
          if 'use-fs' in opcodes:
            opcodes.remove('use-fs')
          opcodes.append('use-cache')
          self._debug('Opcodes are now %s' % opcodes)

      try:
        self._validateCache(fusepath, opcodes)
      except OSError, e:
        if e.errno != errno.ENOENT:
          raise

        if flags & os.O_CREAT:
          self._debug('Skipping over ENOENT since we want O_CREAT')
          pass
        else:
          self._debug('Couldn\'t find %s -- raising ENOENT' % fusepath)
          raise

      self._debug('Attempting open of %s.' % fusepath)

      try:
        self._debug('Opening file')
        if mode:
          fp = tsumufs.fsOverlay.open(fusepath, flags, uid, gid,
                                      tsumufs.defaultCacheMode | stat.S_IFREG,
                                      usefs=('use-fs' in opcodes))
        else:
          fp = tsumufs.fsOverlay.open(fusepath, flags, uid, gid,
                                      usefs=('use-fs' in opcodes))

      except OSError, e:
        self._checkForFSDisconnect(e, opcodes)
        raise

      self._debug('Closing file.')
      fp.close(release=False)

    finally:
      self._debug('Unlocking file.')
      self.unlockFile(fusepath)
      self._debug('Method complete.')

  @benchmark
  def getDirents(self, fusepath):
    '''
    Return the dirents from a directory's contents if cached.
    '''

    try:
      self.lockFile(fusepath)

      opcodes = self._genCacheOpcodes(fusepath)
      self._validateCache(fusepath, opcodes)

      if 'enoent' in opcodes:
        raise OSError(errno.ENOENT, os.strerror(errno.ENOENT))

      dirents = tsumufs.fsOverlay.listdir(fusepath)

    finally:
      self.unlockFile(fusepath)

    for doc in dirents:
      # If fs not available and file not cached to disk, do not display it
      if (not tsumufs.fsAvailable.isSet()
          and not self.isCachedToDisk(os.path.join(fusepath, doc.filename))):
        continue

      yield doc

  @benchmark
  def _flagsToStdioMode(self, flags):
    '''
    Convert flags to stupidio's mode.
    '''

    if flags & os.O_RDWR:
      if flags & os.O_APPEND:
        result = 'a+'
      else:
        result = 'w+'

    elif flags & os.O_WRONLY:
      if flags & os.O_APPEND:
        result = 'a'
      else:
        result = 'w'

    else: # O_RDONLY
      result = 'r'

    return result

  @benchmark
  def releaseFile(self, fusepath, flags):
    try:
      self.lockFile(fusepath)

      opcodes = self._genCacheOpcodes(fusepath)

      # Open a file in write mode and close it to raise
      # the update of the stats in the database.
      tsumufs.fsOverlay.open(fusepath, flags,
                             usefs=('use-fs' in opcodes)).close()

      return ('use-fs' not in opcodes)
    finally:
      self.unlockFile(fusepath)

  @benchmark
  def readFile(self, fusepath, offset, length, flags, mode=0700):
    '''
    Read a chunk of data from the file referred to by path.

    This method acts very much like the typical idiom:

      fp = open(file, mode)
      fp.seek(offset)
      result = fp.read(length)
      return result

    Except it works in respect to the cache and the fs mount. If the
    file is available from fs and should be cached to disk, it will
    be cached and then read from there.

    Otherwise, fs reads are done directly.

    Returns:
      The data requested.

    Raises:
      OSError on error reading the data.
    '''

    self.lockFile(fusepath)

    try:
      opcodes = self._genCacheOpcodes(fusepath)
      self._validateCache(fusepath, opcodes)

      self._debug('Reading file contents from %s [ofs: %d, len: %d]'
                  % (fusepath, offset, length))

      # TODO(jtg): Validate permissions here

      fp = tsumufs.fsOverlay.open(fusepath, flags, mode=mode,
                                  usefs=('use-fs' in opcodes))

      fp.seek(0)
      fp.seek(offset)
      result = fp.read(length)
      fp.close(release=False)

      self._debug('Read %s' % repr(result))
      return result

    finally:
      self.unlockFile(fusepath)
      
  @benchmark
  def writeFile(self, fusepath, offset, buf, flags, mode=None):
    '''
    Write a chunk of data to the file referred to by fusepath.

    This method acts very much like the typical idiom:

      fp = open(file, mode)
      fp.seek(offset)
      result = fp.write(buf)
      return result

    Except that all writes go diractly to the cache first, and a synclog entry
    is created.

    Returns:
      The number of bytes written.

    Raises:
      OSError on error writing the data.
      IOError on error writing the data.
    '''

    self.lockFile(fusepath)

    try:
      opcodes = self._genCacheOpcodes(fusepath)
      self._validateCache(fusepath, opcodes)

      self._debug('Writing to file %s at offset %d with buffer length of %d '
                  'and mode %s' % (fusepath, offset, len(buf), mode))

      # TODO(jtg): Validate permissions here, too

      fp = tsumufs.fsOverlay.open(fusepath, flags, mode=mode,
                                  usefs=('use-fs' in opcodes))

      if offset >= 0:
        fp.seek(offset)
      else:
        fp.seek(0, 2)

      fp.write(buf)
      fp.close(release=False)

      return ('use-fs' not in opcodes)

    finally:
      self.unlockFile(fusepath)

  @benchmark
  def truncateFile(self, fusepath, size):
    '''
    Unconditionally truncate the file. Don't check to see if the user has
    access.
    '''

    try:
      self.lockFile(fusepath)

      opcodes = self._genCacheOpcodes(fusepath)
      self._validateCache(fusepath, opcodes)

      self._debug('Truncating %s to %d bytes.' % (fusepath, size))

      fp = tsumufs.fsOverlay.open(fusepath, os.O_RDWR,
                                  usefs=('use-fs' in opcodes))

      fp.truncate(size)
      fp.close(release=False)

      return ('use-fs' not in opcodes)

    finally:
      self.unlockFile(fusepath)

  @benchmark
  def readLink(self, fusepath):
    '''
    Return the target of a symlink.
    '''

    self.lockFile(fusepath)

    try:
      opcodes = self._genCacheOpcodes(fusepath)
      self._validateCache(fusepath, opcodes)
      realpath = self._generatePath(fusepath, opcodes)

      self._debug('Reading link from %s' % realpath)

      return os.readlink(realpath)
    finally:
      self.unlockFile(fusepath)

  @benchmark
  def makeSymlink(self, target, fusepath, uid, gid):
    '''
    Create a new symlink with the target specified.

    Returns:
      None

    Raises:
      OSError, IOError
    '''

    self.lockFile(fusepath)

    try:
      opcodes = self._genCacheOpcodes(fusepath)

      # Skip enoents -- we're creating a file.
      try:
        self._validateCache(fusepath, opcodes)
      except (IOError, OSError), e:
        if e.errno != errno.ENOENT:
          raise

      tsumufs.fsOverlay.symlink(target, fusepath, uid=uid, gid=gid,
                                usefs=('use-fs' in opcodes))

      return ('use-fs' not in opcodes)
    finally:
      self.unlockFile(fusepath)

  @benchmark
  def makeDir(self, fusepath, mode, uid, gid):
    self.lockFile(fusepath)

    try:
      opcodes = self._genCacheOpcodes(fusepath)

      # Skip enoents -- we're creating a dir.
      try:
        self._validateCache(fusepath, opcodes)
      except (IOError, OSError), e:
        if e.errno != errno.ENOENT:
          raise

      self._debug("Making directory %s" % fusepath)

      tsumufs.fsOverlay.mkdir(fusepath, mode, uid=uid, gid=gid,
                              usefs=('use-fs' in opcodes))

      return ('use-fs' not in opcodes)
    finally:
      self.unlockFile(fusepath)

  @benchmark
  def makeNode(self, fusepath, mode, dev):
    self.lockFile(fusepath)

    try:
      opcodes = self._genCacheOpcodes(fusepath)

      # TODO: implement this !
      return ('use-fs' not in opcodes)

    finally:
      self.unlockFile(fusepath)

  @benchmark
  def chmod(self, fusepath, mode):
    '''
    Chmod a file.

    Returns:
      None

    Raises:
      OSError, IOError
    '''

    self.lockFile(fusepath)

    self._debug("chmod %s %d" % (fusepath, mode))
    try:
      opcodes = self._genCacheOpcodes(fusepath)
      self._validateCache(fusepath, opcodes)

      tsumufs.fsOverlay.chmod(fusepath, mode, usefs=('use-fs' in opcodes))

      return ('use-fs' not in opcodes)
    finally:
      self.unlockFile(fusepath)

  @benchmark
  def chown(self, fusepath, uid, gid):
    '''
    Chown a file.

    Returns:
      None

    Raises:
      OSError, IOError
    '''

    self.lockFile(fusepath)

    self._debug("chown %s %d:%d" % (fusepath, uid, gid))
    try:
      opcodes = self._genCacheOpcodes(fusepath)
      self._validateCache(fusepath, opcodes)

      tsumufs.fsOverlay.chown(fusepath, uid, gid, usefs=('use-fs' in opcodes))

      return ('use-fs' not in opcodes)
    finally:
      self.unlockFile(fusepath)

  @benchmark
  def getxattr(self, fusepath, key):
    '''
    Return the 'key' extended attribute of 'fusepath'

    This method locks the file for reading, look for the attribute
    and unlocks the file.

    Returns:
      string

    Raises:
      OSError if there was a problem getting the extended attribute.
    '''
    self.lockFile(fusepath)

    try:
      opcodes = self._genCacheOpcodes(fusepath, for_stat=True)
      self._debug(' Opcodes are: %s' % str(opcodes))

      self._validateCache(fusepath, opcodes)

      if 'enoent' in opcodes:
        raise OSError(errno.ENOENT, os.strerror(errno.ENOENT))

      self._debug('Looking for the "%s" extended attribute on %s' % (key, fusepath))
      value = tsumufs.fsOverlay.getxattr(fusepath, key)

      self._debug('Returning extended attribute %s.' % repr(value))
      return value

    finally:
      self.unlockFile(fusepath)

  @benchmark
  def setxattr(self, fusepath, key, value):
    '''
    Set an extended attribute
    '''
    self.lockFile(fusepath)

    try:
      opcodes = self._genCacheOpcodes(fusepath)
      self._validateCache(fusepath, opcodes)

      if not tsumufs.fsOverlay.setxattr(fusepath, key, value, usefs=('use-fs' in opcodes)):
        self._debug("There is no need to add an entry in the synclog")
        return False

      return ('use-fs' not in opcodes)
    finally:
      self.unlockFile(fusepath)

  @benchmark
  def utime(self, fusepath, times):
    '''
    Change time of a file.

    Returns:
      None

    Raises:
      OSError, IOError
    '''

    self.lockFile(fusepath)

    self._debug("utime %s " % fusepath)
    try:
      opcodes = self._genCacheOpcodes(fusepath)
      self._validateCache(fusepath, opcodes)

      tsumufs.fsOverlay.utime(fusepath, times, usefs=('use-fs' in opcodes))

      return ('use-fs' not in opcodes)
    finally:
      self.unlockFile(fusepath)

  @benchmark
  def rename(self, fusepath, newpath):
    '''
    Rename a file.

    Returns:
      None

    Raises:
      OSError, IOError
    '''

    # TODO:
    # If some files are located in the subtree of this directory,
    # lock the path to avoid access to this files while the directory
    # is being renamed.

    self.lockFile(fusepath)
    self.lockFile(newpath)

    try:
      srcopcodes = self._genCacheOpcodes(fusepath)
      self._validateCache(fusepath, srcopcodes)

      try:
        destopcodes = self._genCacheOpcodes(newpath)
        self._validateCache(newpath, destopcodes)
      except OSError, e:
        if e.errno != errno.ENOENT:
          # In case of ENOENT, destpath is not create yet.
          raise

      self._debug('Renaming %s -> %s ' % (fusepath, newpath))

      # TODO:
      # In the 'rename' case, we probably should check src and dest
      # opcodes to raise a specific behavior on the synclog if both
      # src and dest paths have not same caching policy. In this case,
      # the following call to the fsOverlay probably will not work.
      usefs = (('use-fs' in srcopcodes) or ('use-fs' in destopcodes))

      tsumufs.fsOverlay.rename(fusepath, newpath, usefs=usefs)

      return not usefs
    finally:
      self.unlockFile(fusepath)
      self.unlockFile(newpath)

  @benchmark
  def access(self, uid, fusepath, mode):
    '''
    Test for access to a path.

    Returns:
      True upon successful check, otherwise False. Don't alter _recurse. That's
      used internally.

    Raises:
      OSError upon access problems.
    '''

    self.lockFile(fusepath)

    try:
      opcodes = self._genCacheOpcodes(fusepath)
      self._validateCache(fusepath, opcodes)

      # TODO(cleanup): make the above chunk of code into a decorator for crying
      # out loud. We do this in every public method and it adds confusion. =o(

      # Root owns everything
      if uid == 0:
        self._debug('Root -- returning 0')
        return 0

      # Recursively go down the path from longest to shortest, checking access
      # perms on each directory as we go down.
      if fusepath != '/':
        self.access(uid, os.path.dirname(fusepath), os.X_OK)

      file_stat = self.statFile(fusepath)

      mode_string = ''
      if mode & os.R_OK:
        mode_string += 'R_OK|'
      if mode & os.W_OK:
        mode_string += 'W_OK|'
      if mode & os.X_OK:
        mode_string += 'X_OK|'
      if mode == os.F_OK:
        mode_string = 'F_OK|'
      mode_string = mode_string[:-1]

      self._debug('access(%s, %s) -> (uid, gid, mode) = (%d, %d, %o)' %
                  (repr(fusepath), mode_string,
                   file_stat.st_uid, file_stat.st_gid, file_stat.st_mode))

      # Catch the case where the user only wants to check if the file exists.
      if mode == os.F_OK:
        self._debug('User just wanted to verify %s existed -- returning 0.' %
                    fusepath)
        return 0

      # Check user bits first
      if uid == file_stat.st_uid:
        if ((file_stat.st_mode & stat.S_IRWXU) >> 6) & mode == mode:
          self._debug('Allowing for user bits.')
          return 0

      # Then group bits
      if file_stat.st_gid in tsumufs.getGidsForUid(uid):
        if ((file_stat.st_mode & stat.S_IRWXG) >> 3) & mode == mode:
          self._debug('Allowing for group bits.')
          return 0

      # Finally assume other bits
      if (file_stat.st_mode & stat.S_IRWXO) & mode == mode:
        self._debug('Allowing for other bits.')
        return 0

      self._debug('No access allowed.')
      raise OSError(errno.EACCES, os.strerror(errno.EACCES))

    finally:
      self.unlockFile(fusepath)

  @benchmark
  def _cacheDir(self, fusepath):
    '''
    Cache the directory referenced by path.

    If the directory should not be cached to disk (as specified in the
    cachespec) then only the contents of the directory hash table will
    be stored in the _cachedFiles hash.

    Returns:
      None

    Raises:
      OSError - when an error operating on the filesystem occurs.
    '''

    self.lockFile(fusepath)
    
    try:
      fspath    = tsumufs.fsPathOf(fusepath)
      cachepath = tsumufs.cachePathOf(fusepath)

      self._debug('fspath = %s' % fspath)
      self._debug('cachepath = %s' % cachepath)

      if fusepath == '/':
        self._debug('Asking to cache root -- skipping the cache to '
                    'disk operation, but caching data in memory.')

      else:
        try:
          os.mkdir(cachepath)
        except OSError, e:
          # Skip EEXIST errors -- if it already exists, it may have files in it
          # already. Simply copy the stat and chown it again, then cache the
          # listdir operation as well.

          if e.errno != errno.EEXIST:
            raise

      # If activated, populating database will compare the filesystem dirents
      # to the database dirents, and add to database any files that could be
      # created bypassing the CouchedFilesystem api, directly on the filesystem.
      # The performance overhead raised by this operation increase when the number
      # of file to add to database is higher.
      if tsumufs.populateDb:
        try:
          self._debug('Discovering directory %s contents and populate database.' % fusepath)
          dirents = [ doc.filename for doc in tsumufs.fsOverlay.listdir(fusepath) ]

          for filename in os.listdir(fspath):
            if filename not in dirents:
              tsumufs.fsOverlay.populate(os.path.join(fusepath, filename))

        except OSError, e:
          self._debug('Cannot list directory %s (%s)' % (fusepath, e.strerror))

    finally:
      self.unlockFile(fusepath)

  @benchmark
  def _cacheFile(self, fusepath):
    '''
    Cache the file referenced by path.

    This method locks the file for reading, determines what type it
    is, and attempts to cache it. Note that if there was an issue
    reading from the fsMount, this method will mark the fs mount as
    being unavailble.

    Note: The touch cache isn't implemented here at the moment. As a
    result, the entire cache is considered permacache for now.

    Note: fs error checking and disable are not handled here for the
    moment. Any errors that would ordinarily shut down the fs mount
    are just reported as normal OSErrors, aside from ENOENT.

    Returns:
      Nothing.

    Raises:
      OSError if there was an issue attempting to copy the file
      across to cache.
    '''

    # TODO(jtg): Add support for storing the UID/GID

    self.lockFile(fusepath)

    try:
      fspath = tsumufs.fsPathOf(fusepath)
      cachepath = tsumufs.cachePathOf(fusepath)

      document = tsumufs.fsOverlay[fusepath]

      if stat.S_ISDIR(document.mode):
        # Caching a directory to disk -- call cacheDir instead.
        self._debug('Request to cache a directory -- calling _cacheDir')
        self._cacheDir(fusepath)

      else:
        self._debug('Caching file %s to disk.' % fusepath)

        if (stat.S_ISREG(document.mode)  or
            stat.S_ISFIFO(document.mode) or
            stat.S_ISSOCK(document.mode) or
            stat.S_ISCHR(document.mode)  or
            stat.S_ISBLK(document.mode)):

          try:
              shutil.copyfileobj(tsumufs.fsMount.open(fusepath, os.O_RDONLY | os.O_BINARY),
                                 open(cachepath, "wb"))
          except AttributeError, e:
              shutil.copyfileobj(tsumufs.fsMount.open(fusepath, os.O_RDONLY),
                                 open(cachepath, "w"))

        elif stat.S_ISLNK(document.mode):
          dest = os.readlink(fspath)

          try:
            os.unlink(cachepath)
          except OSError, e:
            if e.errno != errno.ENOENT:
              raise

          os.symlink(dest, cachepath)
          #os.lchown(cachepath, curstat.st_uid, curstat.st_gid)
          #os.lutimes(cachepath, (curstat.st_atime, curstat.st_mtime))

      tsumufs.fsOverlay.setCachedRevision(document.id, document.rev, document.stats.st_mtime)

    finally:
      self.unlockFile(fusepath)

  @benchmark
  def removeCachedFile(self, fusepath, removeperm=False):
    '''
    Remove the cached file referenced by fusepath from the cache.

    This method locks the file, determines what type it is, and
    attempts to decache it.

    Note: The touch cache isn't implemented here at the moment. As a
    result, the entire cache is considered permacache for now.

    Returns:
      None

    Raises:
      OSError if there was an issue attempting to remove the file
      from cache.
    '''

    self.lockFile(fusepath)

    try:
      opcodes = self._genCacheOpcodes(fusepath)
      document = tsumufs.fsOverlay[fusepath]

      if stat.S_ISDIR(document.mode):
        # Firstly test if the directory is empty on the fs because some
        # files that it contains could not be cached to disk. Many programs
        # use to try to remove a directory in order to know if it's required
        # to primary remove files in this directory. Without this workaround,
        # the cached copy of the directory will be removed, and the 'rmdir'
        # system call will fail on the fs directory, when replicated on the
        # filesystem by the syncThread.
        try:
          tsumufs.fsOverlay.listdir(fusepath).next()
          raise OSError(errno.ENOTEMPTY, os.strerror(errno.ENOTEMPTY))

        except StopIteration, e:
          tsumufs.fsOverlay.rmdir(fusepath,
                                  nodb=not removeperm,
                                  usefs=(removeperm and ('use-fs' in opcodes)))

      else:
        tsumufs.fsOverlay.unlink(fusepath,
                                 nodb=not removeperm,
                                 usefs=(removeperm and ('use-fs' in opcodes)))

      try:
        tsumufs.fsOverlay.removeCachedRevision(document.id)
      except KeyError, e:
        # Document never cached to disk
        pass

      return ('use-fs' not in opcodes)
    finally:
      self.unlockFile(fusepath)

  @benchmark
  def _shouldCacheFile(self, fusepath):
    '''
    Method to determine if a file referenced by fusepath should be
    cached, as aoccording to the cachespec.

    Note: If a file is not explicitly listed, but any parent directory
    above the file is, the policy is inherited.

    Returns:
      Boolean. True if the file should be cached.

    Raises:
      None
    '''

    # special case
    if fusepath == "/":
      return True

    path = fusepath
    while path != "/":
      if self._cacheSpec.has_key(path):
        self._debug('caching of %s is %s because of policy on %s'
                    % (fusepath, self._cacheSpec[path], path))
        return self._cacheSpec[path]
      # not found explicity, so inherit policy from parent dir
      (path, base) = os.path.split(path)

    # return default policy
    self._debug('default caching policy on %s' % fusepath)

    # TODO: Verify that we can remove the following test, because
    #       it raise a database access not managed by a cache.
    #
    # if tsumufs.syncLog.isUnlinkedFile(fusepath):
    #   return False
    # else:
    #   return True
    return True

  @benchmark
  def _validateCache(self, fusepath, opcodes=None):
    '''
    Validate that the cached copies of fusepath on local disk are the same as
    the copies upstream, based upon the opcodes geenrated by _genCacheOpcodes.

    Returns:
      None

    Raises:
      Nothing
    '''

    if opcodes == None:
      opcodes = self._genCacheOpcodes(fusepath)

    self._debug('Opcodes are: %s' % opcodes)

    for opcode in opcodes:
      if opcode == 'remove-cache':
        self._debug('Removing cached file %s' % fusepath)
        self.removeCachedFile(fusepath)
      if opcode == 'cache-file':
        self._debug('Updating cache of file %s' % fusepath)
        self._cacheFile(fusepath)
      if opcode == 'merge-conflict':
        # TODO: handle a merge-conflict?
        self._debug('Merge/conflict on %s' % fusepath)

  @benchmark
  def _generatePath(self, fusepath, opcodes=None):
    '''
    Return the path to use for all file operations, based upon the current state
    of the world generated by _genCacheOpcodes.

    Returns:
      None

    Raises:
      Nothing
    '''

    if opcodes == None:
      opcodes = self._genCacheOpcodes(fusepath)

    self._debug('Opcodes are: %s' % opcodes)

    for opcode in opcodes:
      if opcode == 'enoent':
        self._debug('ENOENT on %s' % fusepath)
        raise OSError(errno.ENOENT, os.strerror(errno.ENOENT))
      if opcode == 'use-fs':
        fspath = tsumufs.fsPathOf(fusepath)
        self._debug('Returning fs path for %s -> %s' % (fusepath, fspath))
        return fspath
      if opcode == 'use-cache':
        cachepath = tsumufs.cachePathOf(fusepath)
        self._debug('Returning cache path for %s -> %s' % (fusepath, cachepath))
        return cachepath

  @benchmark
  def _genCacheOpcodes(self, fusepath, for_stat=False):
    '''
    Method encapsulating cache operations and determination of whether
    or not to use a cached copy, an fs copy, update the cache, or
    raise an enoent.

    The string opcodes are as follows:
      enoent         - caller should raise an OSError with ENOENT as the
                       error code.
      use-fs         - caller should use the fs filename for file
                       operations.
      use-cache      - caller should use the cache filename for file
                       operations.
      cache-file     - caller should cache the fs file to disk and
                       overwrite the local copy unconditionally.
      remove-cache   - caller should remove the cached copy
                       unconditionally.
      merge-conflict - undefined at the moment?

    Returns:
      A tuple containing strings.

    Raises:
      Nothing
    '''

    # do the test below exactly once to improve performance, reduce
    # a few minor race conditions and to improve readability
    isCached = self.isCachedToDisk(fusepath)
    shouldCache = self._shouldCacheFile(fusepath)
    fsAvail = tsumufs.fsAvailable.isSet()

    self._debug('fusepath %s, isCached %s, shouldCache %s, fsAvail %s'
                % (fusepath, isCached, shouldCache, fsAvail))

    # if not cachedFile and not fsAvailable raise -ENOENT
    if not isCached and not fsAvail:
      self._debug('File not cached, no fs -- enoent')
      return ['enoent']

    # if not cachedFile and not shouldCache
    if not isCached and not shouldCache:
      if fsAvail:
        if tsumufs.syncLog.isUnlinkedFile(fusepath):
          self._debug('File previously unlinked -- returning use cache.')
          return ['use-cache']
      
        else:
          self._debug('File not cached, should not cache -- use fs.')
          return ['use-fs']

    # if not cachedFile and     shouldCache
    if not isCached and shouldCache:
      if fsAvail:
        if for_stat:
          self._debug('Returning use-fs, as this is for stat.')
          return ['use-fs']

        self._debug(('File not cached, should cache, fs avail '
                     '-- cache file, use cache.'))
        return ['cache-file', 'use-cache']
      else:
        self._debug('File not cached, should cache, no fs -- enoent')
        return ['enoent']

    # if     cachedFile and not shouldCache
    if isCached and not shouldCache:
      if fsAvail:
        self._debug(('File cached, should not cache, fs avail '
                     '-- remove cache, use fs'))
        return ['remove-cache', 'use-fs']
      else:
        self._debug(('File cached, should not cache, no fs '
                     '-- remove cache, enoent'))
        return ['remove-cache', 'enoent']

    # if     cachedFile and     shouldCache
    if isCached and shouldCache:
      if fsAvail:
        if self._fsDataChanged(fusepath):
          if tsumufs.syncLog.isFileDirty(fusepath):
            self._debug('Merge conflict detected.')
            return ['merge-conflict', 'use-fs']

          else:
#            With the databse, no matter with using fs or cache for getting stats
#            if for_stat:
#              self._debug('Returning cache-file, use-fs, as this is for stat.')
#              return ['cache-file', 'use-fs']

            self._debug(('Cached, should cache, fs avail, fs changed, '
                         'cache clean -- recache, use cache'))
            return ['cache-file', 'use-cache']

    self._debug('Using cache by default, as no other cases matched.')
    return ['use-cache']

  @benchmark
  def _fsDataChanged(self, fusepath):
    '''
    Check to see if the fs data has changed since our last cache of the file.

    Returns:
      Boolean true or false.

    Raises:
      Any error that might occur during an os.lstat(), aside from ENOENT.
    '''

    self.lockFile(fusepath)

    try:
      document = tsumufs.fsOverlay[fusepath]
      doc_rev, doc_mtime = document.rev, document.stats.st_mtime
      cached_rev, cached_mtime = tsumufs.fsOverlay.getCachedRevision(document.id)

      self._debug('%s changed ? Document revision (%s,%s), cached revision (%s,%s).'
                  % (fusepath, doc_rev, doc_mtime, cached_rev, cached_mtime))

      return cached_rev < doc_rev and cached_mtime != doc_mtime

    except OSError, e:
      if e.errno == errno.ENOENT:
        return False
      else:
        raise

    except KeyError, e:
      # Stats never cached
      return True

    finally:
      self.unlockFile(fusepath)

  @benchmark
  def isCachedToDisk(self, fusepath):
    '''
    Check to see if the file referenced by fusepath is cached to
    disk.

    Fusepath is expected to be an absolute path into the filesystem from
    the view seen from FUSE. Ie: all "absolute paths" are actually
    relative to the tsumufs mountpoint root.

    Returns:
      Boolean: True if the file is cached. False otherwise.

    Raises:
      OSError if there was an issue statting the file in question.
    '''

    # Lock the file for access
    self.lockFile(fusepath)

    try:
      try:
        # TODO: check the file in the cached revisions,
        #       instead of stating the fs.
        statgoo = os.lstat(tsumufs.cachePathOf(fusepath))

      except OSError, e:
        if e.errno == errno.ENOENT:
          return False
        else:
          self._debug('_isCachedToDisk: Caught OSError: errno %d: %s'
                      % (e.errno, e.strerror))
          raise

      return True
    finally:
      self.unlockFile(fusepath)

  @benchmark
  def lockFile(self, fusepath):
    '''
    Lock the file for access exclusively.

    This prevents multiple FUSE threads from clobbering
    one-another. Note that this method blocks until a
    previously-locked file is unlocked.

    Returns:
      None

    Raises:
      None
    '''

#     tb = self._getCaller()
#     self._debug('Locking file %s (from: %s(%d): in %s <%d>).'
#                 % (fusepath, tb[0], tb[1], tb[2], thread.get_ident()))

    try:
      lock = self._fileLocks[fusepath]
    except KeyError:
      lock = self._fileLocks.setdefault(fusepath, threading.RLock())

    lock.acquire()

  @benchmark
  def unlockFile(self, fusepath):
    '''
    Unlock the file for access.

    The inverse of lockFile. Releases a lock if one had been
    previously acquired.

    Returns:
      None

    Raises:
      None
    '''

#     tb = self._getCaller()
#     self._debug('Unlocking file %s (from: %s(%d): in %s <%d>).'
#                 % (fusepath, tb[0], tb[1], tb[2], thread.get_ident()))

    self._fileLocks[fusepath].release()

  @benchmark
  def saveCachePolicy(self, filename):
    f = open(filename, 'w')
    for k,v in self._cacheSpec.iteritems():
      f.write("%s:%s\n" % (k,v))
    f.close()

  @benchmark
  def loadCachePolicy(self, filename):
    f = open(filename, 'r')
    for line in f.readlines():
      k,v = line.strip().split(':')
      self._cacheSpec[k] = v
    f.close()


@extendedattribute('any', 'tsumufs.in-cache')
def xattr_inCache(type_, path, value=None):
  if value:
    return -errno.EOPNOTSUPP

  if tsumufs.cacheManager.isCachedToDisk(path):
    return '1'
  return '0'

@extendedattribute('any', 'tsumufs.dirty')
def xattr_isDirty(type_, path, value=None):
  if value:
    return -errno.EOPNOTSUPP

  if tsumufs.syncLog.isFileDirty(path, recursive=True):
    return '1'
  return '0'

@extendedattribute('any', 'tsumufs.should-cache')
def xattr_shouldCache(type_, path, value=None):

  if value:
    # set the value
    if value == '-':
      tsumufs.cacheManager._cacheSpec[path] = False
    elif value == '+':
      tsumufs.cacheManager._cacheSpec[path] = True
    elif value == '=':
      if tsumufs.cacheManager._cacheSpec.has_key(path):
        del tsumufs.cacheManager._cacheSpec[path]
    else:
      return -errno.EOPNOTSUPP
    return 0 # set is successfull

  if tsumufs.cacheManager._cacheSpec.has_key(path):
    if tsumufs.cacheManager._cacheSpec[path]:
      return '+'
    else:
      return '-'

  # not explicity named, so use our lookup code
  if tsumufs.cacheManager._shouldCacheFile(path):
    return '= (+)'
  return '= (-)'
