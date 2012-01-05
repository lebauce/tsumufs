# Copyright (C) 2012  Agorabox. All Rights Reserved.
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

'''UFO file synchronization client library.'''

import os
import sys
import stat
import errno
import traceback

import tsumufs
from tsumufs.views import View
from tsumufs.fusefile import FuseFile

from ufo.database import DocumentHelper
from ufo.filesystem import SyncDocument
from ufo.debugger import Debugger

import gettext
_ = gettext.gettext


class UserFile(FuseFile):

  def __init__(self, path, *args, **kw):
    FuseFile.__init__(self, '/' + tsumufs.user.login + path, *args, **kw)


class MountpointView(View, Debugger):

  name = ""

  levels = []

  docClass = SyncDocument

  fileClass = UserFile

  def __init__(self):
    self._syncDocs = DocumentHelper(tsumufs.SyncDocument, tsumufs.dbName)

    View.__init__(self)

  def getRootDocs(self):
    return []

  def __getattribute__(self, attr):
    if attr in ['statFile', 'getDirents', 'getxattr', 'setxattr', 'listxattr']:
      def wrapper(path, *args, **kw):
        return getattr(tsumufs.cacheManager, attr)('/' + tsumufs.user.login + path,
                                                   *args, **kw)
      return wrapper
    else:
      return super(MountpointView, self).__getattribute__(attr)
      

viewClass = MountpointView

