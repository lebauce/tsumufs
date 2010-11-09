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

import stat

import tsumufs
from metrics import benchmark
from tsumufs.views import loadViews

from ufo.filesystem import SyncDocument


class ViewsManager(tsumufs.Debuggable):
  '''
  Class designed to handle management of the view folders.
  Each view folder provides a custom view of filesystem contents.

  This manager provides all system call capabilities as the
  cache manager, in the context of virtual path defined by the
  views.

  All system calls are redirected to the instantiated view
  corresponding to the fusepath given in parameter.
  '''

  _views = {}  # A hash of loaded view instances

  def __init__(self):
    for view in loadViews():
      self._views[view.name] = view

    self._debug("Loaded views: " + str(self._views.keys()))

  def getRootDirs(self):
    '''
    Return all root views directories that should be displayed
    in the viewPoint directory.
    '''

    for name in self._views.keys():
        yield SyncDocument(filename=name, mode=0555 | stat.S_IFDIR)

  def isAnyViewPath(self, path):
    '''
    Test if it's a path to a view directory.
    '''

    path.startswith(tsumufs.viewsPoint) and path != tsumufs.viewsPoint
    x, x, viewPath = path.partition(tsumufs.viewsPoint + '/')

    return self._views.has_key(viewPath.split('/')[0])

  def __getattr__(self, attr):
    '''
    Redirect a wrapper that call the attribute on the instantiated view
    corresponding to the fusepath given in parameter. The job of this
    wrapper is to translate the fusepath to a path relative to the view
    root directory.
    '''

    # Wrapper function that make path arguments relative to the view path,
    # and dispatch the call to the corresponding view instance.
    def path_wrapper(*args):
      view = None
      wrapped_args = ()

      for arg in args:
        if isinstance(arg, str) and self.isAnyViewPath(arg):
          x, x, relative = arg.partition(tsumufs.viewsPoint + '/')
          view = relative.split('/')[0]
          wrapped_args += (relative,)

        else:
          wrapped_args += (arg,)

      self._debug("Calling '%s%s' on '%s' view" % (attr, str(wrapped_args), str(view)))

      return getattr(self._views[view], attr).__call__(*wrapped_args)

    return path_wrapper
