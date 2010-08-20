# Copyright (C) 2010  Agorabox. All Rights Reserved.
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

'''TsumuFS, a NFS-based caching filesystem.'''

import os
import errno
import sys
import stat
import syslog
import thread
import threading
import dataregion


import tsumufs

class SAMBABackendError(Exception):
  pass

class SAMBABackend(tsumufs.Debuggable, tsumufs.FSBackend):

  def __init__(self):
    tsumufs.FSBackend.__init__(self)

  def pingServerOK(self):
    '''
    Method to verify that the SAMBA server is available.
    '''
    retval=os.system("/usr/bin/smbclient -L //192.168.1.13/haksan")
    if retval == 0:
      return True
    else:
      return False

    

