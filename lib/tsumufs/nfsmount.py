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
import socket
import tsumufs

from pynfs.nfs4constants import *
from pynfs.nfs4types import *
from pynfs import nfs4lib 


class NFSMountError(Exception):
  pass


class NFSMount(tsumufs.FSMount):

  def __init__(self):
    # Try to get server infos from command line
    try:
      self._serverIp = tsumufs.mountSource.split(":")[0]

      # Use port 2049 as default
      self._serverPort = 2049
      for mountOpt in str(tsumufs.mountOptions).split(','):
        if mountOpt[0:5] == "port=":
          self._serverPort = int(mountOpt[5:])
          break

    except AttributeError, e:
      pass

    tsumufs.FSMount.__init__(self)

  def pingServerOK(self):
    try:
      kwargs = {}
      if os.getenv("PYNFS_UID"):
        kwargs["uid"] = int(os.getenv("PYNFS_UID"))

      if os.getenv("PYNFS_GID"):
        kwargs["gid"] = int(os.getenv("PYNFS_GID"))

      nfs4lib.create_client(self._serverIp, self._serverPort, "tcp", **kwargs)

    except (socket.error, TypeError), e:
        return False
    return True

  def findServerInfos(self):
    try:
      # List nfs root to wake up nfs
      os.listdir(tsumufs.fsMountPoint)

      mountPoints = open('/proc/mounts').readlines()
      mountPoints.reverse()

      for mountPoint in mountPoints:
        self._debug(mountPoint)
        infos = mountPoint.split(' ')
        if (infos[1] == tsumufs.fsMountPoint and infos[2] == tsumufs.fsType):

          self._serverIp = infos[0].split(":")[0]

          # Use port 2049 as default
          self._serverPort = 2049
          for mountOpt in infos[3].split(','):
            if mountOpt[0:5] == "port=":
              self._serverPort = int(mountOpt[5:])
              break
          break

    except (OSError, IOError), e:
      pass

