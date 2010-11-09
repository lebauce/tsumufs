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
import socket
import tsumufs

from pynfs.nfs4constants import *
from pynfs.nfs4types import *
from pynfs import nfs4lib 


class NFSMountError(Exception):
  pass


class NFSMount(tsumufs.FSMount):

  _ncl = None

  def __init__(self):
    self.server_ip = tsumufs.mountSource.split(":")[0]
    self.server_port = 2049
    for mountOpt in tsumufs.mountOptions.split(','):
      if mountOpt[0:5] == "port=":
         self.server_port = int(mountOpt[5:])
         break

    tsumufs.FSMount.__init__(self)

  def pingServerOK(self):
    try:
      kwargs = {}
      if os.getenv("PYNFS_UID"):
        kwargs["uid"] = int(os.getenv("PYNFS_UID"))
      if os.getenv("PYNFS_GID"):
        kwargs["gid"] = int(os.getenv("PYNFS_GID"))
      self._ncl = nfs4lib.create_client(self.server_ip, self.server_port, "tcp", **kwargs)
    except socket.error, e:
        return False
    return True

