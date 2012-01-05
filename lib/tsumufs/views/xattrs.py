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

'''TsumuFS, a fs-based caching filesystem.'''

import os
import stat
import errno

import tsumufs
from tsumufs.views import View

from ufo import utils
from ufo import errors
from ufo.filesystem import SyncDocument
from ufo.database import DocumentHelper


class ExtendedAttributeFile(tsumufs.Debuggable):
  def __init__(self, path, flags=0, mode=None, uid=None, gid=None, pid=None):
    self._viewPath = path
    self._flags = flags
    x, x, relpath = path.partition(os.path.join(tsumufs.viewsPoint,
                                                ExtendedAttributesView.name))
    self._name = os.path.basename(path)
    self._path = os.path.dirname("/" + "/".join(relpath.split('/')[1:]))
    self._helper = DocumentHelper(SyncDocument, tsumufs.dbName)

  def read(self, length, offset):
    return tsumufs.cacheManager.getxattr(self._path, self._name)

  def write(self, new_data, offset):
    tsumufs.fuseThread.setxattr(os.path.dirname(self._viewPath), self._name,
                                new_data, len(new_data))
    return len(new_data)

  def release(self, flags):
    return 0

  def fsync(self, isfsyncfile):
    return 0

  def flush(self):
    return 0

  def ftruncate(self, length):
    return tsumufs.fuseThread.setxattr(os.path.dirname(self._viewPath),
                                       self._name, "", 0)

  def fgetattr(self):
    document = tsumufs.fsOverlay[self._path]
    stats = document.get_stats()
    value = document.xattrs.get(self._name)
    if value == None:
      stats.st_size = 0
    else:
      stats.st_size = len(value)
    stats.st_mode = 0700 | stat.S_IFREG
    return stats

  def remove(self):
     del tsumufs.fsOverlay[self._path].xattrs[self._name]


class ExtendedAttributesView(View):

  name = ".xattrs"
  docClass = SyncDocument
  fileClass = ExtendedAttributeFile

  def hackedPath(self, path):
    return path

  def getDirents(self, path):
    relpath = "/" + "/".join(path.split('/')[1:])

    try:
      entries = []
      f = tsumufs.fsOverlay[relpath]
      for key in tsumufs.fsOverlay.listxattr(relpath):
        entries.append(SyncDocument(filename=key,
                                    dirpath=os.path.join(f.path),
                                    mode=0700 | stat.S_IFREG,
                                    type="application/x-attr"))
      return entries

    except Exception, e:
      return []

  def isFileLevel(self, path):
    return False

  def statFile(self, path):
    relpath = "/" + "/".join(path.split('/')[1:])
    try:
      stats = tsumufs.cacheManager.statFile(relpath)
      stats.st_mode = 0700 | stat.S_IFDIR
      return stats

    except:
      stats = tsumufs.cacheManager.statFile(os.path.dirname(relpath))
      stats.st_mode = 0700 | stat.S_IFREG
      try:
        stats.st_size = len(tsumufs.cacheManager.getxattr(os.path.dirname(relpath),
                                                          os.path.basename(path)))
      except KeyError:
        raise OSError(errno.ENOENT, path, os.strerror(errno.ENOENT))
      return stats

  def removeCachedFile(self, path, removeperm=False):
    relpath = "/" + "/".join(path.split('/')[1:])
    tsumufs.fuseThread.removexattr(os.path.dirname(relpath),
                                   os.path.basename(path))
    

viewClass = ExtendedAttributesView
