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

'''TsumuFS is a disconnected, offline caching filesystem.'''

import os
import socket

from socket import *

import tsumufs


class SSHFSMountError(Exception):
  pass


class SSHFSMount(tsumufs.FSMount):

  def __init__(self):
    self.server_ip = tsumufs.mountSource.slit(":")[0]
    self.server_port = 22
    tsumufs.FSMount.__init__(self)

  def pingServerOK(self):
    '''
    Method to verify that the SSHFS server is available.
    '''
    try:
      PySocket = socket.socket(AF_INET,SOCK_DGRAM)
      PySocket.connect((self.server_ip, self.server_port))
    except socket.error, e:
        PySocket.close()
        return False

    PySocket.close()
    return True
        
