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

'''TsumuFS, a generic-based caching filesystem.'''

import os
import errno
import sys
import stat
import syslog
import thread
import threading
import dataregion
import socket
import tsumufs

from pynfs.nfs4constants import *
from pynfs.nfs4types import *
from pynfs import nfs4lib 

class NFSBackendError(Exception):
  pass

class NFSBackend(tsumufs.Debuggable, tsumufs.FSBackend):

  _ncl = None

  def __init__(self):
    pass
  

  def pingServerOK(self):
    '''
    Method to verify that the NFS server is available.
    
    import subprocess
    import os
    retval=subprocess.call('/home/megabast/Documents/tsumuFS/tsumufs-read-only/lib/tsumufs/PingServer.sh')
    if retval == 0:
      return True
    else:
       return False
    '''
    try:
      kwargs = {}
      if os.getenv("PYNFS_UID"):
        kwargs["uid"] = int(os.getenv("PYNFS_UID"))
      if os.getenv("PYNFS_GID"):
        kwargs["gid"] = int(os.getenv("PYNFS_GID"))
      self._ncl = nfs4lib.create_client("192.168.1.4", 2049, "tcp", **kwargs)
    except socket.error, e:
        return False
    return True
    #self._ncl.init_connection()
