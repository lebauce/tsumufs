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
import tsumufs
from tsumufs.fsmount import FSMount
from ufo.fsbackend.dav import WebDAVFileSystem
 
class DAVMount(FSMount, WebDAVFileSystem):

    def __init__(self, url, auth=None):
        self.url = url

        FSMount.__init__(self)
        WebDAVFileSystem.__init__(self, url, auth=auth)

    def pingServerOK(self):
        try:
            self.lstat("/" + str(tsumufs.user))
        except:
            return False

        return True

    def fsMountCheckOK(self):
        if self.pingServerOK():
            tsumufs.fsAvailable.set()
            return True

        tsumufs.fsAvailable.clear()
        return False

    def mount(self):
        return True

    def unmount(self):
        return True

