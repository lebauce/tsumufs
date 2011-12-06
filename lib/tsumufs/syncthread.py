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
import shutil
import sys
import time
import threading
import errno
import stat
import traceback
import fuse

import tsumufs
from extendedattributes import extendedattribute

from ufo.filesystem import DocumentHelper
from ufo.user import user
import ufo.acl as acl

CONFLICT_PREAMBLE = '''
# New changeset at %(timestamp)d
set = ChangeSet(%(timestamp)d)
'''

CONFLICT_POSTAMBLE = '''
try:
  changesets.append(set)
except NameError:
  changesets = [set]
changesets

'''

def lockfile(func):
  def lockfile_handle(self, item, *args, **kw):
    try:
      tsumufs.cacheManager.lockFile(item.filename)
      return func(self, item, *args, **kw)
    finally:
      tsumufs.cacheManager.unlockFile(item.filename)

  return lockfile_handle

class SyncThread(tsumufs.Debuggable, threading.Thread):
  '''
  Thread to handle cache and fs mount management.
  '''

  def __init__(self):
    self._debug('Initializing.')

    # Install our custom exception handler so that any exceptions are
    # output to the syslog rather than to /dev/null.
    sys.excepthook = tsumufs.syslogExceptHook

    self._debug('Setting up thread state.')
    threading.Thread.__init__(self, name='SyncThread')

    self._debug('Initialization complete.')

  def _attemptMount(self):
    self._debug('Attempting to mount fs.')

    self._debug('Checking for fs server availability')
    if not tsumufs.fsMount.pingServerOK():
      self._debug('fs ping failed.')
      return False

    self._debug('fs ping successful.')

    self._debug('Checking if fs is ready.')
    if tsumufs.fsMount.fsMountCheckOK():
      self._debug('fs is already ready.')
      return True

    self._debug('Attempting mount.')

    try:
      result = tsumufs.fsMount.mount()
    except:
      self._debug('Exception: %s' + traceback.format_exc())
      self._debug('fs mount failed.')
      tsumufs.fsAvailable.clear()
      return False

    if result:
      self._debug('fs mount complete.')
      tsumufs.fsAvailable.set()
      return True
    else:
      self._debug('Unable to mount fs.')
      tsumufs.fsAvailable.clear()
      return False

  def _propagateNew(self, item, change):
    fusepath = item.filename
    cachepath = tsumufs.cachePathOf(fusepath)

    try:
      document = tsumufs.fsOverlay[fusepath]
      os.lstat(cachepath)
    except OSError, e:
      if e.errno == errno.ENOENT:
        # The file may have been deleted while we
        # were waiting for the lock
        return False

    try:
      tsumufs.fsMount.lstat(fusepath)
    except (OSError, IOError), e:
      if e.errno != errno.ENOENT:
        raise

    if item.file_type != 'dir':
      if item.file_type == 'symlink':
        tsumufs.fsMount.symlink(os.readlink(cachepath), fusepath, document=document)
      else:
        tsumufs.fsMount.copy(open(cachepath, "r"),
                             fusepath, document=document)
          
      tsumufs.fsMount.chmod(fusepath, document.mode)

    else:
      tsumufs.fsMount.mkdir(fusepath, document.mode, document=document)

    try:
      tsumufs.fsMount.chown(fusepath, document.uid, document.gid)
    except:
      pass

    return False

  def _propagateLink(self, item, change):
    # TODO(jtg): Add in hardlink support

    return False

  def _propagateUnlink(self, item, change):
    # TODO(conflicts): Conflict if the file type or inode have changed
    fusepath = item.filename

    if item.file_type != 'dir':
      tsumufs.fsMount.unlink(fusepath)
    else:
      tsumufs.fsMount.rmdir(fusepath)

    return False

  def _propagateChange(self, item, change):
    # Rules:
    #   1. On conflict fs always wins.
    #   2. Loser data always appended as a list of changes in
    #      ${mount}/._${file}.changes
    #   3. We're no better than fs

    # Steps:
    #   1. Stat both files, and verify the file type is identical.
    #   2. Read in the regions from fs.
    #   3. Compare the regions between the changes and fs.
    #   4. If any changes differ, the entire set is conflicted.
    #      4a. Create a conflict change file and write out the changes
    #          that differ.
    #      4b. Create a 'new' change in the synclog for the conflict
    #          change file.
    #      4c. Erase the cached file on disk.
    #      4d. Invalidate dirent cache for the file's containing dir.
    #      4e. Invalidate the stat cache fo that file.
    #   5. Otherwise:
    #      4a. Iterate over each change and write it out to fs.

    fusepath = item.filename
    self._debug('Fuse path is %s' % fusepath)

    document   = tsumufs.fsOverlay[fusepath]
    cache_stat = document.get_stats()
    fs_stat    = tsumufs.fsMount.lstat(fusepath)

    self._debug('Validating data hasn\'t changed on fs. %s %s' % (fs_stat, cache_stat))
    if stat.S_IFMT(fs_stat.st_mode) != stat.S_IFMT(cache_stat.st_mode):
      self._debug('File type has completely changed -- conflicted.')
      return True

    else:
      # Iterate over each region, and verify the changes
      for region in change.getDataChanges():
        self._debug('Reading region %s,%s' % (region.start, region.end))
        data = tsumufs.fsMount.readFileRegion(fusepath,
                                              region.start,
                                              region.end)

        if len(data) < region.end - region.start:
          data += '\x00' * ((region.end - region.start) - len(data))

        if region.data != data:
          self._debug('Region has changed -- entire changeset conflicted.')
          self._debug('Data read was %s' % repr(data))
          self._debug('Wanted %s' % repr(region.data))
          return True

    self._debug('No conflicts detected.')

    # propagate changes
    for region in change.getDataChanges():
      data = tsumufs.cacheManager.readFile(fusepath,
                                           region.start,
                                           region.end - region.start,
                                           os.O_RDONLY)

      # Pad the region with nulls if we get a short read (EOF before the end of
      # the real file. It means we ran into a truncate issue and that the file
      # is shorter than it was originally -- we'll propagate the truncate down
      # the line.
      if len(data) < region.end - region.start:
        data += '\x00' * ((region.end - region.start) - len(data))

      self._debug('Writing to %s at [%d-%d] %s'
                  % (fusepath, region.start,
                     region.end, repr(data)))

      target = tsumufs.fsMount.open(fusepath, os.O_RDWR)
      target.seek(region.start)
      target.write(data)
      target.close()

    # Propagate truncations
    if (cache_stat.st_size < fs_stat.st_size):
      tsumufs.fsMount.ftruncate(fusepath, cache_stat.st_size)

    # Propagate metadatas
    modechange, uidchange, gidchange, timeschange, acls, xattrschange = change.getMetaDataChanges()
    if modechange:
      tsumufs.fsMount.chmod(fusepath, document.mode)
    if timeschange:
      tsumufs.fsMount.utime(fusepath, (cache_stat.st_atime, cache_stat.st_mtime))
    if uidchange and gidchange:
      tsumufs.fsMount.chown(fusepath, document.uid, document.gid)
    if acls:
      tsumufs.fsMount.set_acl(fusepath, document.posix_acl)

      # We do not want to set the extended attribute a second time
      xattrschange.remove("system.posix_acl_access")

    for name in xattrschange:
      try:
        tsumufs.fsMount.setxattr(fusepath, name, document.xattrs[name])
      except OSError, e:
        self._debug("Failed to propagate extended attribute %s : %s" % (name, os.strerror(e.errno)))

    return False

  def _propagateRename(self, item, change):
    # TODO(conflicts): Verify inode numbers here
    tsumufs.fsMount.rename(item.old_fname, item.new_fname)

    return False

  def _writeChangeSet(self, item, change):
    # TODO(refactor): Make SyncItem generate the patch set string instead.

    if item.type != 'rename':
      fusepath = item.filename
    else:
      fusepath = item.old_fname

    if fusepath[0] == '/':
      conflictpath = fusepath[1:]
    else:
      conflictpath = fusepath

    conflictpath = conflictpath.replace('/', '-')
    conflictpath = os.path.join(tsumufs.conflictDir, conflictpath)
    self._debug('Using %s as the conflictpath.' % conflictpath)

    try:
      tsumufs.cacheManager.lockFile(fusepath)
      isNewFile = True
      fd = None

      try:
        self._debug('Attempting open of %s' % conflictpath)
        tsumufs.cacheManager.fakeOpen(conflictpath,
                                      os.O_CREAT|os.O_APPEND|os.O_RDWR,
                                      0700 | stat.S_IFREG);
        fd = os.open(tsumufs.cachePathOf(conflictpath),
                     os.O_CREAT|os.O_APPEND|os.O_RDWR,
                     0700 | stat.S_IFREG)
        isNewFile = True
      except OSError, e:
        if e.errno != errno.EEXIST:
          raise

        isNewFile = False

        self._debug('File existed -- reopening as O_APPEND' % conflictpath)
        tsumufs.cacheManager.fakeOpen(conflictpath,
                                      os.O_APPEND|os.O_RDWR|os.O_EXCL,
                                      0700 | stat.S_IFREG);
        fd = os.open(tsumufs.cachePathOf(conflictpath),
                     os.O_APPEND|os.O_RDWR|os.O_EXCL,
                     0700 | stat.S_IFREG)

      fp = os.fdopen(fd, 'r+')
      startPos = fp.tell()
      fp.close()

      # Write the changeset preamble
      self._debug('Writing preamble.')
      tsumufs.cacheManager.writeFile(conflictpath, -1,
                                     CONFLICT_PREAMBLE %
                                     { 'timestamp': time.time() },
                                     os.O_APPEND|os.O_RDWR)

      if item.type == 'new':
        # TODO(conflicts): Write the entire file to the changeset as one large
        # patch.
        self._debug('New file -- don\'t know what to do -- skipping.')
        pass

      if item.type == 'change':
        # TODO(conflicts): propagate metadata changes as well.
        # TODO(conflicts): propagate truncates!

        # Write changes to file
        self._debug('Writing changes to conflict file.')
        for region in change.getDataChanges():
          data = tsumufs.cacheManager.readFile(fusepath,
                                               region.start,
                                               region.end - region.start,
                                               os.O_RDONLY)
          tsumufs.cacheManager.writeFile(conflictpath, -1,
                                         'set.addChange(type_="patch", start=%d, end=%d, data=%s)' %
                                         (region.start, region.end, repr(data)),
                                         os.O_APPEND|os.O_RDWR)

      if item.type == 'link':
        # TODO(conflicts): Implement links.
        self._debug('Link file -- don\'t know what to do -- skipping.')
        pass

      if item.type == 'unlink':
        fp.write('set.addUnlink()')

      if item.type == 'symlink':
        # TODO(conflicts): Implement symlinks.
        self._debug('Symlink file -- don\'t know what to do -- skipping.')
        pass

      if item.type == 'rename':
        self._debug('Rename file -- don\'t know what to do -- skipping.')
        pass

      self._debug('Writing postamble.')
      tsumufs.cacheManager.writeFile(conflictpath, -1, CONFLICT_POSTAMBLE,
                                     os.O_APPEND|os.O_RDWR)

      self._debug('Getting file size.')
      fp = open(tsumufs.cachePathOf(conflictpath), 'r+')
      fp.seek(0, 2)
      endPos = fp.tell()
      fp.close()

      if isNewFile:
        self._debug('Conflictfile was new -- adding to synclog.')
        tsumufs.syncLog.addNew('file', filename=conflictpath)

#        document = tsumufs.cacheManager.statFile(fusepath)
#        tsumufs.fsOverlay.open(conflictpath, create=True,
#                               uid=document.uid, gid=document.gid, 
#                               mode=0700 | stat.S_IFREG)

      else:
        self._debug('Conflictfile was preexisting -- adding change.')
        tsumufs.syncLog.addChange(conflictpath,
                                  startPos, endPos,
                                  '\x00' * (endPos - startPos))
    finally:
      tsumufs.cacheManager.unlockFile(fusepath)

  def _validateConflictDir(self, conflicted_path):
    try:
      try:
        tsumufs.cacheManager.lockFile(tsumufs.conflictDir)

        try:
          tsumufs.cacheManager.statFile(tsumufs.conflictDir)

        except (IOError, OSError), e:
          if e.errno != errno.ENOENT:
            raise

          self._debug('Conflict dir missing -- creating.')
          tsumufs.cacheManager.makeDir(tsumufs.conflictDir, 0700,
                                       tsumufs.context['uid'], tsumufs.context['gid'])

          self._debug('Adding to synclog.')
          tsumufs.syncLog.addNew('dir', filename=tsumufs.conflictDir)

        else:
          self._debug('Conflict dir already existed -- not recreating.')

      except Exception, e:
        exc_info = sys.exc_info()

        self._debug('*** Unhandled exception occurred')
        self._debug('***     Type: %s' % str(exc_info[0]))
        self._debug('***    Value: %s' % str(exc_info[1]))
        self._debug('*** Traceback:')

        for line in traceback.extract_tb(exc_info[2]):
          self._debug('***    %s(%d) in %s: %s' % line)

    finally:
      tsumufs.cacheManager.unlockFile(tsumufs.conflictDir)

  def _handleConflicts(self, item, change):
    if item.type != 'rename':
      fusepath = item.filename
    else:
      fusepath = item.old_fname

    self._debug('Validating %s exists.' % tsumufs.conflictDir)
    self._validateConflictDir(fusepath)

    self._debug('Writing changeset to conflict file.')
    self._writeChangeSet(item, change)

    self._debug('De-caching file %s.' % fusepath)
    tsumufs.cacheManager.removeCachedFile(fusepath)

  def _handleChange(self, item, change):
    type_ = item.type
    change_types = { 'new': self._propagateNew,
                     'link': self._propagateLink,
                     'unlink': self._propagateUnlink,
                     'change': self._propagateChange,
                     'rename': self._propagateRename }

    self._debug('Calling propogation method %s' % change_types[type_].__name__)

    found_conflicts = change_types[type_].__call__(item, change)

    if found_conflicts:
      self._debug('Found conflicts. Running handler.')
      self._handleConflicts(item, change)
    else:
      self._debug('No conflicts detected. Merged successfully.')

  def _replicationHeartbeat():
    if tsumufs.fsOverlay.startReplication():
      tsumufs.remoteReplication.set()
    else:
      tsumufs.remoteReplication.clear()
    self.dbHeartbeat.start()

  def run(self):
    # Set up a 'heartbeat' timer for the replication
    # from the remote server to the client
    tsumufs.fsOverlay.startReplication()
    self.dbHeartbeat = threading.Timer(30.0, self._replicationHeartbeat)

    try:
      while not tsumufs.unmounted.isSet():
        self._debug('TsumuFS not unmounted yet.')

        while (not tsumufs.fsMount.fsMountCheckOK()
               and not tsumufs.unmounted.isSet()):
          self._debug('FS unavailable')

          if not tsumufs.forceDisconnect.isSet():
            self._debug('Trying to mount fs')

            self._attemptMount()
            time.sleep(5)

          else:
            self._debug(('...because user forced disconnect. '
                         'Not attempting mount.'))
            time.sleep(5)

        while (tsumufs.syncPause.isSet()
               and not tsumufs.unmounted.isSet()):
          self._debug('User requested sync pause. Sleeping.')
          time.sleep(5)

        while (tsumufs.fsMount.fsMountCheckOK()
               and not tsumufs.unmounted.isSet()
               and not tsumufs.syncPause.isSet()):

          self._debug('Checking for items to sync.')
          for (item, change) in tsumufs.syncLog.popChanges():

            self._debug('Got one: %s' % repr(item))

            if tsumufs.syncPause.isSet():
              self._debug('... but user requested sync pause.')
              tsumufs.syncLog.finishedWithChange(item, remove_item=False)
              break

            try:
              tsumufs.syncWork.set()

              try:
                # Handle the change
                self._debug('Handling change.')
                self._handleChange(item, change)

                # Mark the change as complete.
                self._debug('Marking change %s as complete.' % repr(item))

                tsumufs.syncLog.finishedWithChange(item)
                tsumufs.syncWork.clear()

              except Exception, e:
                exc_info = sys.exc_info()

                self._debug('*** Unhandled exception occurred')
                self._debug('***     Type: %s' % str(exc_info[0]))
                self._debug('***    Value: %s' % str(exc_info[1]))
                self._debug('*** Traceback:')

                for line in traceback.extract_tb(exc_info[2]):
                  self._debug('***    %s(%d) in %s: %s' % line)

                raise e

            except Exception, e:
              self._debug('Caught an IOError in the middle of handling a change: '
                          '%s' % str(e))

              self._debug('Disconnecting from fs.')
              tsumufs.fsAvailable.clear()
              tsumufs.fsMount.unmount()

              self._debug('Not removing change from the synclog, but finishing.')
              tsumufs.syncLog.finishedWithChange(item, remove_item=False)

              break

      self._debug('Shutdown requested.')
      self._debug('Unmounting fs.')

      try:
        tsumufs.fsMount.unmount()
      except:
        self._debug('Unable to unmount fs -- caught an exception.')
        tsumufs.syslogCurrentException()
      else:
        self._debug('fs unmount complete.')

      self._debug('Syncing changes to disk.')

      try:
        tsumufs.syncLog.checkpoint()
      except Exception, e:
        self._debug('Unable to commit changes -- caught an exception.')
        tsumufs.syslogCurrentException()

      self._debug('SyncThread shutdown complete.')

    except Exception, e:
      tsumufs.syslogCurrentException()

    self.dbHeartbeat.cancel()

    # This fails probably because of the /couchdb in the
    # URL of the remote CouchDB server
    # if tsumufs.remoteReplication.isSet():
    #   tsumufs.fsOverlay.stopReplication()


@extendedattribute('root', 'tsumufs.pause-sync')
def xattr_pauseSync(type_, path, value=None):
  try:
    if value != None:
      if value == '0':
        tsumufs.syncPause.clear()
      elif value == '1':
        tsumufs.syncPause.set()
      else:
        return -errno.EOPNOTSUPP
      return

    if tsumufs.syncPause.isSet():
      return '1'

    return '0'
  except:
    return -errno.EOPNOTSUPP

@extendedattribute('root', 'tsumufs.force-disconnect')
def xattr_forceDisconnect(type_, path, value=None):
  try:
    if value != None:
      if value == '0':
        tsumufs.forceDisconnect.clear()
      elif value == '1':
        tsumufs.forceDisconnect.set()
        tsumufs.fsMount.unmount()
        tsumufs.fsAvailable.clear()
      else:
        return -errno.EOPNOTSUPP
      return

    if tsumufs.forceDisconnect.isSet():
      return '1'

    return '0'
  except:
    return -errno.EOPNOTSUPP

@extendedattribute('root', 'tsumufs.connected')
def xattr_connected(type_, path, value=None):
  if value != None:
    return -errno.EOPNOTSUPP

  if tsumufs.fsAvailable.isSet():
    return '1'

  return '0'
