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

import sys
import fuse
import stat

import tsumufs
from metrics import benchmark
from tsumufs.views import loadViews


class ViewsManager(tsumufs.Debuggable):
  '''
  Class designed to handle management of the virtual folders.
  Each virtual folder provides a custom view of fs contents, 
  displayed depending on ...
  '''

  _views = {}     # A hash of view in

  def __init__(self):
    for view in loadViews():
      self._views[view.name] = view

    self._debug("Loaded views: " + str(self._views.keys()))

  def isLoadedViewPath(self, path):
    '''
    Test if it's a path to a view directory. 
    '''

    path.startswith(tsumufs.viewsPoint) and path != tsumufs.viewsPoint
    x, x, viewPath = path.partition(tsumufs.viewsPoint + '/')

    return self._views.has_key(viewPath.split('/')[0])

  def realFilePath(self, path):
    '''
    Return the real path of a view directory entry.
    '''

    x, x, viewPath = path.partition(tsumufs.viewsPoint + '/')
    return self._views[viewPath.split('/')[0]].realFilePath(viewPath)

  @benchmark
  def getDirents(self, path):
    '''
    Return all directory views if path is the viewsPoint path,
    or return dirents from a view directory's contents.
    '''

    if path == tsumufs.viewsPoint:
      return self._views.keys()

    else:
      x, x, viewPath = path.partition(tsumufs.viewsPoint + '/')
      return self._views[viewPath.split('/')[0]].getDirents(viewPath)

  @benchmark
  def statFile(self, path):
    '''
    Return the stat referenced by fusepath.

    This method dispatch the stat request to the corresponding
    view according to path.
    '''

    x, x, viewPath = path.partition(tsumufs.viewsPoint + '/')
    view = viewPath.split('/')[0]
    
    self._debug("Statting '%s' in view '%s'" % (path, view))

    return self._views[view].statFile(viewPath)

  @benchmark
  def access(self, uid, path, mode):
    '''
    This method dispatch the access request to the corresponding
    view according to path.
    '''

    x, x, viewPath = path.partition(tsumufs.viewsPoint + '/')
    view = viewPath.split('/')[0]

    return self._views[view].access(uid, viewPath, mode)
