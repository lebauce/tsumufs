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

import threading
import pwd
import grp

# Not the greatest thing in the world to do, but it makes things
# organizationally easier to reach. Dumping all of these classes into this file
# directly would be impractical. In general, we follow the "one class one file"
# rule.

from debuggable import *
from cachemanager import *
from viewsmanager import *
from synclog import *
from fusefile import *
from fusethread import *
from syncthread import *
from inodechange import *
from syncitem import *
from mutablestat import *
from filesystemoverlay import *
from extendedattributes import *
from notification import *
from metrics import *

from fsmount import *
from nfsmount import *
from sambamount import *
from sshfsmount import *

from pynfs.nfs4constants import *
from pynfs.nfs4types import *
import pynfs.nfs4lib

from ufo.utils import *
from ufo.filesystem import *

__version__ = (0, 16)

populateDb = False
debugMode  = False
debugLevel = 0

progName   = None
syslogOpen = False

mountSource  = None
mountPoint   = None
mountOptions = None

# Set default values to options here,
# I can't get default values working with optParse...
rootUID      = 0
rootGID      = 0
rootMode     = 0555

dbName       = 'tsumufs'
dbRemote     = None
spnego       = False

fsBaseDir     = '/var/lib/tsumufs/fs'
fsMountPoint  = None
fsMountCmd    = None
fsUnmountCmd  = None
fsMount       = None
fsType        = 'nfs4'
fsMountMethod = 'default'

cacheBaseDir = '/var/cache/tsumufs'
cacheSpecDir = '/var/lib/tsumufs/cachespec'
cachePoint   = None
cacheManager = None

viewsPoint = ''
viewsManager = None

conflictDir  = '/.tsumufs-conflicts'

defaultModeMask   = 0077
defaultCacheMode  = 0600        # readable only by the user
checkpointTimeout = 30          # in seconds

syncLog   = None
fsOverlay = None
notifier  = None


class EventNotifier(threading._Event):

  def __init__(self, noticationtype):
    threading._Event.__init__(self)
    self.type = noticationtype

  def clear(self):
    threading._Event.clear(self)
    notifier.notify(self.type, False)
    
  def set(self):
    threading._Event.set(self)
    notifier.notify(self.type, True)


unmounted       = EventNotifier("unmounted")
fsAvailable     = EventNotifier("connection")
forceDisconnect = threading.Event()
syncPause       = EventNotifier("syncpause")
syncWork        = EventNotifier("syncwork")


def syslogCurrentException():
  '''
  Shortcut to the below idiom.
  '''

  syslogExceptHook(*sys.exc_info())


def syslogExceptHook(type, value, tb):
  '''
  Quick exception handler to log exceptions to syslog rather than
  dumping them to /dev/null after FUSE has forked.
  '''

  syslog.syslog(syslog.LOG_ERR, '*** Unhandled exception occurred')
  syslog.syslog(syslog.LOG_ERR, '***     Type: %s' % str(type))
  syslog.syslog(syslog.LOG_ERR, '***    Value: %s' % str(value))
  syslog.syslog(syslog.LOG_ERR, '*** Traceback:')

  for line in traceback.extract_tb(tb):
    syslog.syslog(syslog.LOG_ERR, '***    %s(%d) in %s: %s'
                  % line)

def getManager(path):
  '''
  Fusepath could be a "viewpath" or a "fspath".
  According to fusepath, the corresponding manager is returned.
  '''
  if tsumufs.viewsManager.isAnyViewPath(path):
    return tsumufs.viewsManager
  else:
    return tsumufs.cacheManager

def fsPathOf(fusepath):
  '''
  Quick one-off method to help with translating FUSE-side pathnames
  to VFS pathnames.

  Returns:
  A string containing the absolute path to the file on the fs
  mount.

  Raises:
  Nothing
  '''

  # Catch the case that the fusepath is absolute (which it should be)
  if fusepath[0] == '/':
    rhs = fusepath[1:]
  else:
    rhs = fusepath

  transpath = os.path.join(tsumufs.fsMountPoint, rhs)
  return transpath


def cachePathOf(fusepath):
  '''
  Quick one-off method to help with translating FUSE-side pathnames
  to VFS pathnames.

  This method returns the cache-side VFS pathname for the given
  fusepath.

  Returns:
  A string containing the absolute path to the file on the cache
  point.

  Raises:
  Nothing
  '''

  # Catch the case that the fusepath is absolute (which it should be)
  if fusepath[0] == '/':
    rhs = fusepath[1:]
  else:
    rhs = fusepath

  transpath = os.path.join(tsumufs.cachePoint, rhs)
  return transpath


def getGidsForUid(uid):
  '''
  Return a listing of group IDs that the given uid belongs to. Note that the
  primary group is included in this list.

  Returns:
    A list of integers.

  Raises:
    Nothing.
  '''

  pwent = pwd.getpwuid(uid)
  username = pwent.pw_name
  groups = [ pwent.pw_gid ]

  for group in grp.getgrall():
    if username in group.gr_mem:
      groups.append(group.gr_gid)

  return groups
