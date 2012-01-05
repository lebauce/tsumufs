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
import posixpath

import tsumufs
from tsumufs.views import View

from ufo.database import DocumentHelper
from ufo.filesystem import SyncDocument
from ufo.debugger import Debugger

import gettext
_ = gettext.gettext

VOLUME_AUTORUN = "autorun.inf"
VOLUME_ICON = ".michufs.png"

class StaticFile(tsumufs.Debuggable):
  _fd = None

  rootDir = os.path.join(os.path.dirname(__file__), "icons")

  def __init__(self, path, flags=0, mode=0777, uid=None, gid=None, pid=None):
    self._path = os.path.join(self.rootDir, path[1:])
    self.path = path
    self.dirpath = os.path.dirname(path)
    self.filename = os.path.basename(path)
    self.flags = flags
    self.mode = mode

  def read(self, length, offset):
    os.lseek(self.fd, offset, os.SEEK_SET)
    return os.read(self.fd, length)

  def write(self, new_data, offset):
    os.lseek(self.fd, offset, os.SEEK_SET)
    return os.write(new_data)

  def fsync(self):
    return os.fsync(self.fd)

  def flush(self):
    pass

  def release(self):
    return os.close(self.fd)

  def ftruncate(self, length):
    if hasattr(os, "ftruncate"):
      return os.ftruncate(self.fd, length)

  def fgetattr(self):
    return os.stat(self._path)

  def __getattr__(self, attr):
    return getattr(self.fgetattr(), "st_" + attr)

  @property
  def fd(self):
    if not self._fd:
      self._fd = os.open(self._path, self.flags, self.mode)
    return self._fd

  @property
  def stats(self):
    return self.fgetattr()

  def get_stats(self):
    return self.stats


class AutorunFile(StaticFile):
  def __init__(self, path, flags=0, mode=0777, uid=None, gid=None, pid=None):
    StaticFile.__init__(self, path, flags, mode, uid, gid, pid)
    self.path = path

  def read(self, length, offset):
    return self.getContent()[offset:offset + length]

  def getContent(self):
    content  = "[autorun]\n"
    content += 'label="%s"\n' % _("My UFO")
    content += "icon=%s\n" % VOLUME_ICON
    return content

  def fgetattr(self):
    stats = tsumufs.cacheManager.statFile(tsumufs.viewsPoint)
    stats.st_mode = 0444 | stat.S_IFREG
    stats.st_size = len(self.getContent())
    return stats

  write = release = fsync = flush = ftruncate = lambda *args, **kw: 0


class DecorationFile(tsumufs.Debuggable):
  def __new__(cls, path, *args, **kwargs):
    if path == posixpath.join(tsumufs.viewsPoint, VOLUME_AUTORUN):
      return AutorunFile(path, *args, **kwargs)

    elif path == posixpath.join(tsumufs.viewsPoint, VOLUME_ICON):
      return StaticFile(path, *args, **kwargs)

    raise Exception("Unhandled file %s" % path)

                                                                      
class DecorationView(View, tsumufs.Debuggable):

  name = "decoration"

  levels = []

  docClass = SyncDocument

  fileClass = DecorationFile

  mountPoint = "/"

  def getRootDocs(self, *args, **kw):
   for filename, klass in ((VOLUME_AUTORUN, AutorunFile),
                           (VOLUME_ICON, StaticFile)):
      yield klass(posixpath.join(tsumufs.viewsPoint, filename))

  getDirents = getRootDocs


viewClass = DecorationView
