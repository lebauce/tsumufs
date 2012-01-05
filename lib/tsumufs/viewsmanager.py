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

import stat

import tsumufs
from metrics import benchmark
from tsumufs.views import loadViews

from ufo.filesystem import SyncDocument


class ViewsManager(tsumufs.Debuggable):
  '''
  Class designed to handle management of the view folders.
  Each view folder provides a custom view of the filesystem contents.

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

    for name, view in self._views.items():
      for doc in view.getRootDocs():
        yield doc

  def parseViewPath(self, path):
    '''
    Parse the path and returns the view name
    and the path relative to the view
    '''

    for name, view in self._views.items():
      for doc in view.getRootDocs():
        if path.startswith(doc.path):
          return name, view.relPath(path)

    for name, view in self._views.items():
      viewPath = view.relPath(path)
      if viewPath:
        return name, viewPath

    return None, path

  def isAnyViewPath(self, path):
    '''
    Test if it's a path to a view directory.
    '''

    view = self.parseViewPath(path)[0]

    return self._views.has_key(view)

  def getFileClass(self, path):
    '''
    Return the dedicated file class for a path
    '''

    view = self.parseViewPath(path)[0]

    return self._views[view].fileClass

  def __getattr__(self, attr):
    '''
    Redirect a wrapper that call the attribute on the instantiated view
    corresponding to the fusepath given in parameter. The job of this
    wrapper is to translate the fusepath to a path relative to the view
    root directory.
    '''

    # Wrapper function that make path arguments relative to the view path,
    # and dispatch the call to the corresponding view instance.
    def path_wrapper(*args, **kw):
      view = ""
      wrapped_args = ()

      for arg in args:
        if (isinstance(arg, str) or isinstance(arg, unicode)) and self.isAnyViewPath(arg):
          view, relative = self.parseViewPath(arg)
          wrapped_args += (relative,)

        else:
          wrapped_args += (arg,)

      method = getattr(self._views.get(view), attr, None)
      if not method:
        # Attempt to open a file in a view.
        # Default behaviour is to delegate the call to the cache manager
        # as files in most views are indeed real files accessible through
        # a different path
        method = getattr(tsumufs.cacheManager, attr)

      self._debug("Calling '%s%s' on '%s' view" % (attr, str(wrapped_args), view))

      return method(*wrapped_args, **kw)

    return path_wrapper
