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
import errno
import stat
import statvfs
import time
import traceback
import getpass

import fuse
from fuse import Fuse

import tsumufs
from extendedattributes import extendedattribute
from metrics import benchmark

import ufo.auth as auth
from ufo.user import User
from couchdb.mapping import Document, DictField, TextField, Mapping
from ufo.database import DocumentHelper, ChangesSequenceDocument, ChangesFiltersDocument, ReplicationFiltersDocument
from tsumufs.filesystemoverlay import CachedRevisionDocument
from tsumufs.dataregion import DataRegionDocument
from tsumufs.syncitem import SyncChangeDocument
from tsumufs.inodechange import FileChangeDocument
from ufo.sharing import FriendDocument
from ufo.filesystem import SyncDocument
from ufo.notify import NotificationDocument
from ufo.views import SortedByTypeSyncDocument, BuddySharesSyncDocument, MySharesSyncDocument, FriendSyncDocument, TaggedSyncDocument


class FuseThread(tsumufs.Debuggable, Fuse):
  '''
  Class that implements the prototype design of the TsumuFS
  filesystem. This class provides the main interface to Fuse. Note
  that this class is not a thread, yet it is considered as one in the
  design docs.
  '''

  def __init__(self, *args, **kw):
    '''
    Initializer. Prepares the object for initial use.
    '''

    Fuse.__init__(self, *args, **kw)

    self.parseCommandLine()

    tsumufs.fuseThread = self

    self._debug('Creating design documents')
    try:
        self.createDesignDocuments()
    except:
      exc_info = sys.exc_info()

      self._debug('*** Unhandled exception occurred')
      self._debug('***     Type: %s' % str(exc_info[0]))
      self._debug('***    Value: %s' % str(exc_info[1]))
      self._debug('*** Traceback:')

      for line in traceback.extract_tb(exc_info[2]):
        self._debug('***    %s(%d) in %s: %s' % line)

      raise

    self.multithreaded = 1

    self._debug('Initializing cachemanager object.')
    try:
      tsumufs.cacheManager = tsumufs.CacheManager()
    except:
      exc_info = sys.exc_info()

      self._debug('*** Unhandled exception occurred')
      self._debug('***     Type: %s' % str(exc_info[0]))
      self._debug('***    Value: %s' % str(exc_info[1]))
      self._debug('*** Traceback:')

      for line in traceback.extract_tb(exc_info[2]):
        self._debug('***    %s(%d) in %s: %s' % line)

      raise

    self._debug('Initializing permissions overlay object.')
    try:
      tsumufs.fsOverlay = tsumufs.FileSystemOverlay()
    except:
      exc_info = sys.exc_info()

      self._debug('*** Unhandled exception occurred')
      self._debug('***     Type: %s' % str(exc_info[0]))
      self._debug('***    Value: %s' % str(exc_info[1]))
      self._debug('*** Traceback:')

      for line in traceback.extract_tb(exc_info[2]):
        self._debug('***    %s(%d) in %s: %s' % line)

      raise

    # Setup the fsMount object for both sync and mount threads to
    # access raw fs with.
    self._debug('Initializing fsMount proxy.')
    try:
      if tsumufs.fsType in ['nfs', 'nfs4']:
          from nfsmount import NFSMount
          tsumufs.fsMount = NFSMount()
      elif tsumufs.fsType == 'samba':
          from sambamount import SAMBAMount
          tsumufs.fsMount = SAMBAMount()
      elif tsumufs.fsType == 'sshfs':
          from sshfsmount import SSHFSMount
          tsumufs.fsMount = SSHFSMount()
      elif tsumufs.fsType == 'webdav':
          from davmount import DAVMount
          tsumufs.fsMount = DAVMount(tsumufs.mountSource, tsumufs.auth)
    except:
      # TODO(jtg): Erm... WHY can't we call tsumufs.syslogExceptHook here? O.o
      exc_info = sys.exc_info()

      self._debug('*** Unhandled exception occurred')
      self._debug('***     Type: %s' % str(exc_info[0]))
      self._debug('***    Value: %s' % str(exc_info[1]))
      self._debug('*** Traceback:')

      for line in traceback.extract_tb(exc_info[2]):
        self._debug('***    %s(%d) in %s: %s' % line)

      raise

    self._debug('Loading SyncQueue.')
    try:
      tsumufs.syncLog = tsumufs.SyncLog()
    except:
      # TODO(jtg): Same as above... We should really fix this.
      exc_info = sys.exc_info()

      self._debug('*** Unhandled exception occurred')
      self._debug('***     Type: %s' % str(exc_info[0]))
      self._debug('***    Value: %s' % str(exc_info[1]))
      self._debug('*** Traceback:')

      for line in traceback.extract_tb(exc_info[2]):
        self._debug('***    %s(%d) in %s: %s' % line)

      raise

    self._debug('Initializing viewsmanager object.')
    try:
      tsumufs.viewsManager = tsumufs.ViewsManager()
    except:
      exc_info = sys.exc_info()

      self._debug('*** Unhandled exception occurred')
      self._debug('***     Type: %s' % str(exc_info[0]))
      self._debug('***    Value: %s' % str(exc_info[1]))
      self._debug('*** Traceback:')

      for line in traceback.extract_tb(exc_info[2]):
        self._debug('***    %s(%d) in %s: %s' % line)

      return None

    tsumufs.user = User(tsumufs.dbName, tsumufs.user)

  def fsinit(self):
    '''
    Method callback that is called when FUSE's initial startup has
    completed, and the initialization of our client filesystem should
    start.

    Basic setup is done in here, such as instanciation of new objects
    and the startup of threads.
    '''

    # Initialize our threads
    self._debug('Initializing sync thread.')
    try:
      self._syncThread = tsumufs.SyncThread()
    except:
      # TODO(jtg): Same as above... We should really fix this.
      exc_info = sys.exc_info()

      self._debug('*** Unhandled exception occurred')
      self._debug('***     Type: %s' % str(exc_info[0]))
      self._debug('***    Value: %s' % str(exc_info[1]))
      self._debug('*** Traceback:')

      for line in traceback.extract_tb(exc_info[2]):
        self._debug('***    %s(%d) in %s: %s' % line)

      return False

    # Start the threads
    self._debug('Starting sync thread.')
    self._syncThread.start()

    self._debug('fsinit complete.')
    return True

  def createDesignDocuments(self):
    # Sync the design documents for the client's datatypes
    for doc_class in [ CachedRevisionDocument, DataRegionDocument, SyncChangeDocument,
                       FileChangeDocument, ChangesSequenceDocument, ChangesSequenceDocument,
                       SyncDocument, FriendDocument, NotificationDocument,
                       SortedByTypeSyncDocument, BuddySharesSyncDocument, FriendSyncDocument,
                       MySharesSyncDocument, TaggedSyncDocument ]:
        helper = DocumentHelper(doc_class, tsumufs.dbName)
        helper.sync()

    if not helper.database.get("_design/changes"):
        changesfilters = ChangesFiltersDocument()
        changesfilters._data['_id'] = "_design/changes"
        changesfilters.store(helper.database)

    if not helper.database.get("_design/replication"):
        repfilters = ReplicationFiltersDocument()
        repfilters._data['_id'] = "_design/replication"
        repfilters.store(helper.database)

  def main(self, args=None):
    '''
    Mainline of the FUSE client filesystem. This directly overrides
    the Fuse.main() method to allow us to manually shutdown things
    after the FUSE event loop has finished.
    '''

    class FuseFileWrapper(tsumufs.FuseFile):
      '''
      Inner class to wrap the FuseFile class with the reference to this thread,
      allowing us to get at the GetContext() call. Essentially we're creating a
      closure here. Ugly, but it's the only way to get the uid and gid into the
      FuseFile thread.

      Idea borrowed directly from Robie Basak in his email to fuse-dev, which is
      visible at <http://www.nabble.com/Python%3A-Pass-parameters-to-file_class-to18301066.html#a20066429>.
      '''

      def __new__(cls, path, *args, **kwargs):
        kwargs.update(self.GetContext())

        klass = tsumufs.getManager(path).getFileClass(path) or tsumufs.FuseFile

        return klass(path, *args, **kwargs)

      def __init__(self2, *args, **kwargs):
        kwargs.update(self.GetContext())
        tsumufs.FuseFile.__init__(self2, *args, **kwargs)

    self.file_class = FuseFileWrapper

    self._debug('Trying fsinit()')
    if self.fsinit():
      result = Fuse.main(self, args)

      self._debug('Fuse main event loop exite')

      self._debug('Setting event and condition states.')
      tsumufs.unmounted.set()

      self._debug('Waiting for the sync thread to finish.')
      self._syncThread.join()

      self._debug('Shutdown complete.')
      self._debug("---BEGIN-GEN-BENCHMARK-REPORT---")

      metrics=""
      for key in tsumufs.metrics._metrics.keys():
        self._debug(" %s: %s " % (str(key) , str(tsumufs.metrics._metrics[key])))
      self._debug("---END-GEN-BENCHMARK-REPORT---")

    else:
      self._debug('fsinit() failed...')
      result = False

    return result

  def parseCommandLine(self):
    '''
    Parse the command line arguments into a usable set of
    variables. This sets the following instance variables:

        progName:
            The name of the program as reflected in sys.argv[0].

        mountOptions:
            The mount options passed verbatim from mount(8), in a
            comma separated list of key=value pairs, stored as a
            hash.

        mountSource:
            The fs path to mount from.

        mountPoint:
            The local path to mount TsumuFS on.

    If the argument list is too short, or the -o option is missing
    arguments, this method will immediately exit the program with a
    code of 1.
    '''

    # Setup our option parser to not be retarded.
    self.parser = fuse.FuseOptParse(standard_mods=False,
                                    fetch_mp=False,
                                    dash_s_do='undef')

    # Add in the named options we care about.
    self.parser.add_option(mountopt='fstype',
                           dest='fsType',
                           default='nfs4',
                           help=('Set the type of the undelying filesystem'))
    self.parser.add_option(mountopt='fsbasedir',
                           dest='fsBaseDir',
                           default='/var/lib/tsumufs/fs',
                           help=('Set the fs mount base directory [default: '
                                 '%default]'))
    self.parser.add_option(mountopt='fsmountpoint',
                           dest='fsMountPoint',
                           default=None,
                           help=('Set the directory name of the fs mount '
                                 'point [default: calculated based upon the '
                                 'source]'))
    self.parser.add_option(mountopt='fsmountcmd',
                           dest='fsMountCmd',
                           default=None,
                           help=('Set the fs mount command '
                                 '[default: %default]'))
    self.parser.add_option(mountopt='fsunmountcmd',
                           dest='fsUnmountCmd',
                           default=None,
                           help=('Set the fs unmount command '
                                 '[default: %default]'))
    self.parser.add_option(mountopt='fsmountmethod',
                           dest='fsMountMethod',
                           default='default',
                           help=('Set the fs mount method '
                                 '[default: %default]'))
    self.parser.add_option(mountopt='cachebasedir',
                           dest='cacheBaseDir',
                           default='/var/cache/tsumufs',
                           help=('Set the base directory for cache storage '
                                 '[default: %default]'))
    self.parser.add_option(mountopt='cachespecdir',
                           dest='cacheSpecDir',
                           default='/var/lib/tsumufs/cachespec',
                           help=('Set the base directory for cachespec '
                                 'storage [default: %default]'))
    self.parser.add_option(mountopt='cachepoint',
                           dest='cachePoint',
                           default=None,
                           help=('Set the directory name for cache storage '
                                 '[default: calculated]'))
    self.parser.add_option(mountopt='dbname',
                           dest='dbName',
                           default='tsumufs',
                           help=('Set the database name for fs metadatas'
                                 '[default: tsumufs]'))
    self.parser.add_option(mountopt='dbremote',
                           dest='dbRemote',
                           default=None,
                           help=('Set the directory name for cache storage'))
    self.parser.add_option(mountopt='viewspoint',
                           dest='viewsPoint',
                           default='',
                           help=('Set the relative views folders path'))
    self.parser.add_option(mountopt='rootuid',
                           dest='rootUID',
                           default=0,
                           help=('Set the overlay root directory owner uid '
                                 '[default: superuser]'))
    self.parser.add_option(mountopt='rootgid',
                           dest='rootGID',
                           default=0,
                           help=('Set the overlay root directory owner gid '
                                 '[default: superuser]'))
    self.parser.add_option(mountopt='rootmode',
                           dest='rootMode',
                           default=0555,
                           help=('Set the overlay root directory mode '
                                 '[default: 0555 (r-xr-xr-x)]'))
    self.parser.add_option(mountopt='fsname',
                           dest='fsName',
                           default='TsumuFS',
                           help=('Set the name of the fuse filesystem'))

    self.parser.add_option('-S',
                           dest='mountSource',
                           default=None,
                           help=('Set the fs source uri [default: %default]'))
    self.parser.add_option('-O',
                           dest='mountOptions',
                           default=None,
                           help=('A comma-separated list of key-value '
                                 'pairs that adjust how the fs mount '
                                 'point is mounted. [default: '
                                 '%default]'))

    self.parser.add_option('-f',
                           action='callback',
                           callback=lambda *args: self.fuse_args.setmod('foreground'),
                           help=('Prevents TsumuFS from forking into '
                                 'the background.'))
    self.parser.add_option('-D', '--fuse-debug',
                           action='callback',
                           callback=lambda *args: self.fuse_args.add('debug'),
                           help=('Turns on fuse-python debugging. '
                                 'Only useful if you also specify '
                                 '-f. Typically only useful to '
                                 'developers.'))
    self.parser.add_option('-a',
                           action='callback',
                           callback=lambda *args: self.fuse_args.add('fsname=/tmp/tsumufs-test-nfs-dir'),
                           help=('Fuse will work on bigger regions than 4Kbytes'))

    self.parser.add_option('-t', '--auth',
                           dest='auth',
                           default='webauth',
                           help='Specify authentication method for remote access. [default: %default]')
    self.parser.add_option('-c', '--cookie',
                           dest='cookie',
                           default=None,
                           help='Specify authentication cookie for remote access. [default: %default]')
    self.parser.add_option('--del-cookie',
                           dest='delcookie',
                           action='store_true',
                           default=False,
                           help='Delete cookie file after authentication. [default: %default]')
    self.parser.add_option('-u', '--user',
                           dest='user',
                           default=getpass.getuser(),
                           help='Specify user name for authentication. [default: %default]')
    self.parser.add_option('-p', '--passwd',
                           dest='passwd',
                           default='',
                           help='Specify password for authentication. [default: %default]')

    self.parser.add_option('-d', '--debug',
                           dest='debugMode',
                           action='store_true',
                           help='Enable debug messages. [default: %default]')
    self.parser.add_option('-l', '--debug-level',
                           dest='debugLevel',
                           type='int',
                           action='store',
                           help=('The debug level at which to output'
                                 'data. [default: 0]'))
    self.parser.add_option('-b', '--populate-db',
                           dest='populateDb',
                           action='store_true',
                           help='Enable the populating of the database. [default: %default]')

    # GO!
    self.parse(values=tsumufs, errex=1)

    # Verify we have a source and destination to mount.
    if len(self.cmdline[1]) != 1:
      sys.stderr.write(('%s: invalid number of arguments provided: '
                       'expecting source.\n') %
                       tsumufs.progName)
      sys.exit(1)

    # Pull out the mount point
    tsumufs.mountPoint = self.cmdline[1][0]

    # Make sure the source and point don't contain trailing slashes.
    if tsumufs.mountSource and tsumufs.mountSource[-1] == '/':
      tsumufs.mountSource = tsumufs.mountSource[:-1]
    if tsumufs.mountPoint[-1] == '/':
      tsumufs.mountPoint = tsumufs.mountPoint[:-1]

    # Make sure the mountPoint is a fully qualified pathname.
    if os.path.isabs(tsumufs.mountPoint):
      tsumufs.mountPoint = os.path.join(os.getcwd(), tsumufs.mountPoint)

    # Make sure the viewPoint is a fully qualified pathname.
    if not tsumufs.viewsPoint or tsumufs.viewsPoint[0] != '/':
      tsumufs.viewsPoint = os.path.join("/", tsumufs.viewsPoint)

    # Shove the proper mountPoint into FUSE's mouth.
    self.fuse_args.mountpoint = tsumufs.mountPoint

    # Finally, calculate the runtime paths if they weren't specified already.
    if tsumufs.fsMountPoint == None:
      tsumufs.fsMountPoint = os.path.join(tsumufs.fsBaseDir,
                                          tsumufs.mountPoint.replace('/', '-'))

    if tsumufs.cachePoint == None:
      tsumufs.cachePoint = os.path.join(tsumufs.cacheBaseDir,
                                        tsumufs.mountPoint.replace(':' + os.sep, '').replace(os.sep, '-'))

    # Available on Windows(pywinfuse), MacOsX (macfuse)
    self.fsname = tsumufs.fsName

    self._debug('user is %s' % tsumufs.user)
    self._debug('fsType is %s' % tsumufs.fsType)
    self._debug('fsName is %s' % tsumufs.fsName)
    self._debug('mountPoint is %s' % tsumufs.mountPoint)
    self._debug('fsMountPoint is %s' % tsumufs.fsMountPoint)
    self._debug('fsMountCmd is %s' % tsumufs.fsMountCmd)
    self._debug('cacheBaseDir is %s' % tsumufs.cacheBaseDir)
    self._debug('cachePoint is %s' % tsumufs.cachePoint)
    self._debug('dbName is %s' % tsumufs.dbName)
    self._debug('dbRemote is %s' % tsumufs.dbRemote)
    self._debug('auth is %s' % tsumufs.auth)
    self._debug('viewsPoint is %s' % tsumufs.viewsPoint)
    self._debug('rootMode is %d' % tsumufs.rootMode)
    self._debug('rootUID is %d' % tsumufs.rootUID)
    self._debug('rootGID is %d' % tsumufs.rootGID)
    self._debug('mountOptions is %s' % tsumufs.mountOptions)

    if tsumufs.auth == "webauth":
        if tsumufs.cookie:
            self._debug("Getting credentials from cookie")
            tsumufs.auth = auth.WebAuthAuthenticator(cookie=open(tsumufs.cookie).read())

            if tsumufs.delcookie:
                os.remove(tsumufs.cookie)
            del tsumufs.cookie

        else:
            self._debug("Getting credentials from the user infos %s:%s:" % (tsumufs.user, tsumufs.passwd))
            tsumufs.auth = auth.WebAuthAuthenticator(tsumufs.user, tsumufs.passwd)
            del tsumufs.passwd

    elif tsumufs.auth == "spnego":
        tsumufs.auth = auth.SPNEGOAuthenticator()

  ######################################################################
  # Filesystem operations and system calls below here

  @benchmark
  def getattr(self, path):
    '''
    Callback which is called into when a stat() is performed on the
    user side of things.

    Returns:
      A stat result object, the same as an os.lstat() call.

    Raises:
      None
    '''

    self._debug('opcode: getattr (%d) | self: %s | path: %s'
                % (self.GetContext()['pid'], repr(self), path))

    try:
      result = tsumufs.getManager(path).statFile(path)

      self._debug('Returning (%d, %d, %o)' %
                  (result.st_uid, result.st_gid, result.st_mode))

      return result

    except OSError, e:
      self._debug('getattr: Caught OSError: %d: %s'
                  % (e.errno, e.strerror))
      return -e.errno

    except Exception, e:
      exc_info = sys.exc_info()

      self._debug('*** Unhandled exception occurred')
      self._debug('***     Type: %s' % str(exc_info[0]))
      self._debug('***    Value: %s' % str(exc_info[1]))
      self._debug('*** Traceback:')

      for line in traceback.extract_tb(exc_info[2]):
        self._debug('***    %s(%d) in %s: %s' % line)

  @benchmark
  def setxattr(self, path, name, value, size):
    '''
    Callback that is called into when a setxattr() call is
    performed. This sets the value of an extended attribute, if that
    attribute is non-readonly. If the attribute isn't a valid name, or
    is read-only, this method returns -errno.EOPNOTSUPP.

    Returns:
      None, or -EOPNOTSUPP on error.
    '''

    self._debug('opcode: setxattr | path: %s' % path)

    mode = tsumufs.getManager(path).statFile(path).st_mode

    if path == '/':
      type_ = 'root'
    elif stat.S_ISDIR(mode):
      type_ = 'dir'
    else:
      type_ = 'file'

    try:
      return tsumufs.ExtendedAttributes.setXAttr(type_, path, name, value)
    except KeyError, e:
      self._debug('Request for extended attribute that is not present in the '
                  'dictionary: <%s, %s, %s>'
                  % (repr(type_), repr(path), repr(name)))

    try:
      context = self.GetContext()

      tsumufs.getManager(path).access(context['uid'], path, os.W_OK)

      if tsumufs.getManager(path).setxattr(path, name, value):
        tsumufs.syncLog.addMetadataChange(path, xattrs=[name], acls=(name == "system.posix_acl_access"))

      return 0

    except Exception, e:
      return -errno.EOPNOTSUPP

  @benchmark
  def removexattr(self, path, name):
    '''
    Callback that is called into when a setxattr() call is
    performed. This removes an extended attribute, if that
    attribute is non-readonly. If the attribute isn't a valid name, or
    is read-only, this method returns -errno.EOPNOTSUPP.

    Returns:
      None, or -EOPNOTSUPP on error.
    '''

    self._debug('opcode: removexattr | path: %s | name: %s' % (path, name))

    mode = tsumufs.getManager(path).statFile(path).st_mode

    if path == '/':
      type_ = 'root'
    elif stat.S_ISDIR(mode):
      type_ = 'dir'
    else:
      type_ = 'file'

    try:
      return tsumufs.ExtendedAttributes.removeXAttr(type_, path, name)
    except KeyError, e:
      self._debug('Request for extended attribute that is not present in the '
                  'dictionary: <%s, %s, %s>'
                  % (repr(type_), repr(path), repr(name)))

    try:
      context = self.GetContext()

      tsumufs.getManager(path).access(context['uid'], path, os.W_OK)

      if tsumufs.getManager(path).setxattr(path, name, None):
        tsumufs.syncLog.addMetadataChange(path, xattrs=[name], acls=(name == "system.posix_acl_access"))

        return 0

    except Exception, e:
      return -errno.EOPNOTSUPP

  @benchmark
  def getxattr(self, path, name, size):
    '''
    Callback that is called to get a specific extended attribute size
    or value by name.

    Returns:
      The size of the value (including the null terminator) if size is
        set to 0.
      The string the extended attribute contains if size > 0
      -EOPNOTSUPP if the name is invalid.
    '''
    self._debug('opcode: getxattr | path: %s | name: %s | size: %d'
                % (path, name, size))

    name = name.lower()

    try:
      if name.startswith("security."):
        return -errno.ENODATA

      xattr = tsumufs.getManager(path).getxattr(path, name)

      if size == 0:
        # Caller just wants the size of the value.
        return len(xattr)
      else:
        return xattr

    except OSError, e:
      self._debug('getxattr: Caught OSError: errno %d: %s'
                  % (e.errno, e.strerror))
      return -e.errno

    except KeyError, e:
      self._debug('getxattr: Caught KeyError')
      return -errno.ENODATA

    except Exception, e:
      exc_info = sys.exc_info()

      self._debug('*** Unhandled exception occurred')
      self._debug('***     Type: %s' % str(exc_info[0]))
      self._debug('***    Value: %s' % str(exc_info[1]))
      self._debug('*** Traceback:')

      for line in traceback.extract_tb(exc_info[2]):
        self._debug('***    %s(%d) in %s: %s' % line)

      return -errno.EINVAL

  @benchmark
  def listxattr(self, path, size):
    '''
    Callback method to list the names of valid extended attributes in
    a file.

    Returns:
      The number of variables available if size is 0.
      A list of key names if size > 0.
    '''

    self._debug('opcode: listxattr | path: %s | size: %d'
                % (path, size))

    keys = tsumufs.getManager(path).listxattr(path)

    if size == 0:
      return len(''.join(keys)) + len(keys)

    return keys

  @benchmark
  def readlink(self, path):
    '''
    Reads the value of a symlink.

    Returns:
      The string representation of the file the symlink points to, or
      a negative errno code on error.
    '''

    self._debug('opcode: readlink | path: %s' % path)

    try:
      context = self.GetContext()
      tsumufs.getManager(path).access(context['uid'], path, os.R_OK)

      retval = tsumufs.getManager(path).readLink(path)

      self._debug('Returning: %s' % retval)
      return retval
    except OSError, e:
      self._debug('readlink: Caught OSError: errno %d: %s'
                  % (e.errno, e.strerror))
      return -e.errno

  @benchmark
  def opendir(self, path):
    '''
    Test for access to a directory path.

    Returns:
      True upon successful check, otherwise an errno code is
      returned.
    '''

    self._debug('opcode: opendir | path: %s' % path)

    context = self.GetContext()
    self._debug('uid: %s, gid: %s, pid: %s' %
                (repr(context['uid']),
                 repr(context['gid']),
                 repr(context['pid'])))

    try:
      tsumufs.getManager(path).access(context['uid'], path, os.R_OK | os.X_OK)
      return 0
    except OSError, e:
      self._debug('opendir: Caught OSError: errno %d: %s'
                  % (e.errno, e.strerror))
      return -e.errno

  @benchmark
  def readdir(self, path, offset):
    '''
    Generator callback that returns a fuse.Direntry object every time
    it is called. Similar to the C readdir() call.

    Returns:
      A generator that yields a fuse.Direntry object, or an errno
      code on error.
    '''

    self._debug('opcode: readdir | path: %s | offset: %d' % (path, offset))

    try:
      for filename in [ '.', '..' ]:
        dirent = fuse.Direntry(filename)
        dirent.type = stat.S_IFDIR
        dirent.offset = offset

        yield dirent

      dociterators = [ tsumufs.getManager(path).getDirents(path) ]

      if path == tsumufs.viewsPoint:
        # Append the root directories of views
        dociterators.append(tsumufs.viewsManager.getRootDirs())

      for dociterator in dociterators:
        for doc in dociterator:
          dirent        = fuse.Direntry(str(doc.filename))
          dirent.type   = stat.S_IFMT(doc.mode)
          dirent.offset = offset

          yield dirent

    except OSError, e:
      self._debug('readdir: Caught OSError on %s: errno %d: %s'
                  % (filename, e.errno, e.strerror))

      yield -e.errno

  @benchmark
  def unlink(self, path):
    '''
    Callback to unlink a file on disk.

    Returns:
      True on successful unlink, or an errno code on error.
    '''

    self._debug('opcode: unlink | path: %s' % path)

    try:
      context = self.GetContext()
      tsumufs.getManager(os.path.dirname(path)).access(context['uid'],
                                                       os.path.dirname(path),
                                                       os.W_OK)

      if tsumufs.getManager(path).removeCachedFile(path, removeperm=True):
        tsumufs.syncLog.addUnlink(path, 'file')

      return 0

    except OSError, e:
      self._debug('unlink: Caught OSError: errno %d: %s'
                  % (e.errno, e.strerror))
      return -e.errno

    except Exception, e:
      exc_info = sys.exc_info()

      self._debug('*** Unhandled exception occurred')
      self._debug('***     Type: %s' % str(exc_info[0]))
      self._debug('***    Value: %s' % str(exc_info[1]))
      self._debug('*** Traceback:')

      for line in traceback.extract_tb(exc_info[2]):
        self._debug('***    %s(%d) in %s: %s' % line)

      raise

  @benchmark
  def rmdir(self, path):
    '''
    Removes a directory from disk.

    Returns:
      True on successful unlink, or errno code on error.
    '''

    self._debug('opcode: rmdir | path: %s' % path)

    try:
      context = self.GetContext()
      tsumufs.getManager(path).access(context['uid'], path, os.W_OK)

      if tsumufs.getManager(path).removeCachedFile(path, removeperm=True):
        tsumufs.syncLog.addUnlink(path, 'dir')

      return 0
    except OSError, e:
      self._debug('rmdir: Caught OSError: errno %d: %s'
                  % (e.errno, e.strerror))
      return -e.errno

  @benchmark
  def symlink(self, src, dest):
    '''
    Creates a symlink pointing to src as a file called dest.

    Returns:
      True on successful link creation, or errno code on error.
    '''

    self._debug('opcode: symlink | src: %s | dest: %s' % (src, dest))

    try:
      context = self.GetContext()
      parent = os.path.dirname(dest)
      tsumufs.getManager(parent).access(context['uid'], parent, os.W_OK | os.X_OK)

      if tsumufs.getManager(dest).makeSymlink(src, dest, context['uid'], context['gid']):
        tsumufs.syncLog.addNew('symlink', filename=dest)

      return 0
    except OSError, e:
      self._debug('symlink: Caught OSError: errno %d: %s'
                  % (e.errno, e.strerror))
      return -e.errno

  @benchmark
  def rename(self, old, new):
    '''
    Renames a file from old to new, possibly changing it's path as
    well as its filename.

    Returns:
      True on successful rename, or errno code on error.
    '''

    self._debug('opcode: rename | old: %s | new: %s' % (old, new))

    try:
      context = self.GetContext()

      # According to the rename(2) man page, EACCES is raised when:
      #
      #   Write permission is denied for the directory containing oldpath or
      #   newpath, or, search permission is denied for one of the directories in
      #   the path prefix of oldpath or newpath, or oldpath is a directory and
      #   does not allow write permission (needed to update the ..  entry).
      #
      # Otherwise the rename is allowed. It doesn't care about permissions on
      # the file itself.

      # So, do this:
      #  1. Stat old. If dir and not W_OK, EACCES
      #  2. Verify X_OK | W_OK on dirname(old) and dirname(new)

      old_stat = tsumufs.getManager(old).statFile(old)

      if stat.S_ISDIR(old_stat.st_mode):
        tsumufs.getManager(old).access(context['uid'], old, os.W_OK)

      tsumufs.getManager(os.path.dirname(old)).access(context['uid'],
                                                   os.path.dirname(old),
                                                   os.X_OK | os.W_OK)
      tsumufs.getManager(os.path.dirname(new)).access(context['uid'],
                                                   os.path.dirname(new),
                                                   os.X_OK | os.W_OK)

      # Restore the real file path if old has been acceded via
      # a view virtual folder.
      if tsumufs.viewsManager.isAnyViewPath(old):
        old = tsumufs.viewsManager.realFilePath(old)

      if tsumufs.getManager(new).rename(old, new):
        tsumufs.syncLog.addRename(old, new)

      return 0

    except OSError, e:
      self._debug('rename: Caught OSError: errno %d: %s'
                  % (e.errno, e.strerror))
      return -e.errno

  @benchmark
  def link(self, src, dest):
    '''
    Links a the dest filename to the inode number of the src
    filename.

    Returns:
      True on successful linking, or errno code on error.
    '''

    self._debug('opcode: link | src: %s | dest: %s' % (src, dest))

    try:
      # TODO(jtg): Implement this!
      return -errno.EOPNOTSUPP
    except OSError, e:
      self._debug('link: Caught OSError: errno %d: %s'
                  % (e.errno, e.strerror))
      return -e.errno

  @benchmark
  def chmod(self, path, mode):
    '''
    Changes the mode of a file.

    Returns:
      True on successful mode change, or errno code on error.
    '''

    self._debug('opcode: chmod | path: %s | mode: %o' % (path, mode))

    context = self.GetContext()
    file_stat = tsumufs.getManager(path).statFile(path)

    self._debug('context: %s' % repr(context))
    self._debug('file: uid=%d, gid=%d, mode=%o' %
                (file_stat.st_uid, file_stat.st_gid, file_stat.st_mode))

    if ((file_stat.st_uid != context['uid']) and
        (context['uid'] != 0)):
      self._debug('chmod: user not owner, and user not root -- EPERM')
      return -errno.EPERM

    tsumufs.getManager(path).access(context['uid'],
                                    os.path.dirname(path),
                                    os.F_OK)

    try:
      self._debug('chmod: access granted -- chmoding')
      if tsumufs.getManager(path).chmod(path, mode &~ tsumufs.defaultModeMask):
        tsumufs.syncLog.addMetadataChange(path, mode=True)

      return 0
    except OSError, e:
      self._debug('chmod: Caught OSError: errno %d: %s'
                  % (e.errno, e.strerror))
      return -e.errno

  @benchmark
  def chown(self, path, newuid, newgid):
    '''
    Change the owner and/or group of a file.

    Returns:
      True on successful change, otherwise errno code is returned.
    '''

    self._debug('opcode: chown | path: %s | uid: %d | gid: %d' %
               (path, newuid, newgid))

    context = self.GetContext()
    file_stat = tsumufs.getManager(path).statFile(path)

    if context['uid'] != 0:
      if newuid != -1 and context['uid'] != newuid:
        raise OSError(errno.EPERM, os.strerror(errno.EPERM))

      if (file_stat.st_uid != context['uid']) and (newgid != -1):
        if newgid not in tsumufs.getGidsForUid(context['uid']):
          raise OSError(errno.EPERM, os.strerror(errno.EPERM))

    try:
      if tsumufs.getManager(path).chown(path, newuid, newgid):
        tsumufs.syncLog.addMetadataChange(path, uid=True, gid=True)

      return 0
    except OSError, e:
      self._debug('chown: Caught OSError: errno %d: %s'
                  % (e.errno, e.strerror))
      return -e.errno

  @benchmark
  def truncate(self, path, size=0):
    '''
    Truncate a file to zero length.

    Returns:
      0 on successful truncation, otherwise an errno code is
      returned.
    '''

    self._debug('opcode: truncate | path: %s | size: %d' %
               (path, size))

    try:
      fh = self.file_class(path, os.O_WRONLY)
      fh.ftruncate(size)
      fh.release(os.O_WRONLY)
      del fh

    except Exception, e:
      exc_info = sys.exc_info()

      self._debug('*** Unhandled exception occurred')
      self._debug('***     Type: %s' % str(exc_info[0]))
      self._debug('***    Value: %s' % str(exc_info[1]))
      self._debug('*** Traceback:')

      for line in traceback.extract_tb(exc_info[2]):
        self._debug('***    %s(%d) in %s: %s' % line)

    return 0

  @benchmark
  def mknod(self, path, mode, dev):
    '''
    Creates a special device file with the specified mode and device
    number.

    Returns:
      True on successful creation, otherwise an errno code is
      returned.
    '''

    self._debug('opcode: mknod | path: %s | mode: %d | dev: %s' %
               (path, mode, dev))

    context = self.GetContext()

    if mode & (stat.S_IFCHR | stat.S_IFBLK):
      if context['uid'] != 0:
        raise OSError(errno.EPERM)

    parent = os.path.dirname(path)
    tsumufs.getManager(parent).access(context['uid'], parent, os.W_OK|os.X_OK)

    try:
      if tsumufs.getManager(path).makeNode(path, mode &~ tsumufs.defaultModeMask, dev):

        if mode & stat.S_IFREG:
          tsumufs.syncLog.addNew('file', filename=path)
        elif mode & stat.S_IFCHR:
          tsumufs.syncLog.addNew('dev', filename=path, dev_type='char')
        elif mode & stat.S_IFBLK:
          tsumufs.syncLog.addNew('dev', filename=path, dev_type='block')
        elif mode & stat.S_IFIFO:
          tsumufs.syncLog.addNew('fifo', filename=path)

      return 0
    except OSError, e:
      self._debug('mknod: Caught OSError: errno %d: %s'
                  % (e.errno, e.strerror))
      return -e.errno

  @benchmark
  def mkdir(self, path, mode):
    '''
    Creates a new directory with the specified mode.

    Returns:
      0 on successful creation, othewrise a negative errno code is returned.
    '''

    self._debug('opcode: mkdir | path: %s | mode: %o' % (path, mode))

    context = self.GetContext()
    parent = os.path.dirname(path)
    tsumufs.getManager(parent).access(context['uid'], parent,
                                      os.W_OK|os.X_OK)

    try:
      if tsumufs.getManager(path).makeDir(path, mode &~ tsumufs.defaultModeMask,
                                          context['uid'], context['gid']):
        tsumufs.syncLog.addNew('dir', filename=path)
      return 0

    except OSError, e:
      self._debug('mkdir: Caught OSError: errno %d: %s'
                  % (e.errno, e.strerror))
      return -e.errno

    except Exception, e:
      exc_info = sys.exc_info()

      self._debug('*** Unhandled exception occurred')
      self._debug('***     Type: %s' % str(exc_info[0]))
      self._debug('***    Value: %s' % str(exc_info[1]))
      self._debug('*** Traceback:')

      for line in traceback.extract_tb(exc_info[2]):
        self._debug('***    %s(%d) in %s: %s' % line)

      raise

  @benchmark
  def utime(self, path, times):
    '''
    Set the times (atime, mtime, and ctime) of a file.

    Returns:
      True upon successful modification, otherwise an errno code is
      returned.
    '''

    self._debug('opcode: utime | path: %s' % (path))

    context = self.GetContext()
    file_stat = tsumufs.getManager(path).statFile(path)

    self._debug('context: %s' % repr(context))
    self._debug('file: uid=%d, gid=%d, mode=%o' %
                (file_stat.st_uid, file_stat.st_gid, file_stat.st_mode))

    # Use 0 values as a workaroud to simulate a change on the fs
    # without updating any document revision.
    if times == (0, 0):
      return 0

    try:
      if tsumufs.getManager(path).utime(path, times):
        tsumufs.syncLog.addMetadataChange(path, times=True)

      return 0
    except OSError, e:
      self._debug('utime: Caught OSError: errno %d: %s'
                  % (e.errno, e.strerror))
      return -e.errno

  @benchmark
  def access(self, path, mode):
    '''
    Test for access to a path.

    Returns:
      True upon successful check, otherwise an errno code is
      returned.
    '''

    self._debug('opcode: access | path: %s | mode: %o' % (path, mode))

    context = self.GetContext()
    self._debug('uid: %s, gid: %s, pid: %s' %
                (repr(context['uid']),
                 repr(context['gid']),
                 repr(context['pid'])))

    try:
      tsumufs.getManager(path).access(context['uid'], path, mode)

      return 0

    except OSError, e:
      self._debug('access: Caught OSError: errno %d: %s'
                  % (e.errno, e.strerror))
      return -e.errno

    except Exception, e:
      exc_info = sys.exc_info()

      self._debug('*** Unhandled exception occurred')
      self._debug('***     Type: %s' % str(exc_info[0]))
      self._debug('***    Value: %s' % str(exc_info[1]))
      self._debug('*** Traceback:')

      for line in traceback.extract_tb(exc_info[2]):
        self._debug('***    %s(%d) in %s: %s' % line)

      raise

  @benchmark
  def statfs(self):
    '''
    Should return an object with statvfs attributes (f_bsize, f_frsize...).
    Eg., the return value of os.statvfs() is such a thing (since py 2.2).
    If you are not reusing an existing statvfs object, start with
    fuse.StatVFS(), and define the attributes.

    To provide usable information (ie., you want sensible df(1)
    output, you are suggested to specify the following attributes:

    - f_bsize - preferred size of file blocks, in bytes
    - f_frsize - fundamental size of file blcoks, in bytes
    [if you have no idea, use the same as blocksize]
    - f_blocks - total number of blocks in the filesystem
    - f_bfree - number of free blocks
    - f_files - total number of file inodes
    - f_ffree - nunber of free file inodes
    '''
    self._debug('opcode: statfs')

    try:
        class DummyVfs():
            f_bsize = 512
            f_frsize = 512
            f_blocks = 0
            f_bfree = 0

        du = tsumufs.cacheManager.du(os.path.join("/", tsumufs.user.login))

        # TODO: quota = tsumufs.cacheManager.quota(...)
        quota = 1073741824

        vfs = DummyVfs()
        vfs.f_blocks = quota / 512
        vfs.f_bfree = (quota - du) / 512
        return vfs

    except OSError, e:
      self._debug('statfs: Caught OSError: errno %d: %s'
                  % (e.errno, e.strerror))
      return -e.errno

  def GetContext(self):
    context = Fuse.GetContext(self)
    if (sys.platform == "win32" or (context["uid"] == os.getuid() and
                                    context["gid"] == os.getgid())):
        return { "uid" : tsumufs.user.uid,
                 "gid" : tsumufs.user.gid,
                 "pid" : context["pid"] }
    else:
        return context

@extendedattribute('root', 'tsumufs.version')
def xattr_version(type_, path, value=None):
  if not value:
    return '.'.join(map(str, tsumufs.__version__))

  return -errno.EOPNOTSUPP

@extendedattribute('root', 'tsumufs.dbname')
def xattr_dbname(type_, path, value=None):
  if not value:
    return tsumufs.dbName

  return -errno.EOPNOTSUPP
