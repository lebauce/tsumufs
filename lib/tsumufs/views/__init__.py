# -*- coding: utf-8 -*-

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

import tsumufs


class View(tsumufs.Debuggable):

  name = ""      # Displayed name of the view root directory

  levels = []    # Orderer list of the depth levels names
                 # of the view.

  queries = {}   # Hash of queries to execute for each depth
                 # levels in a view.

  bindings = {}  # Hash of real files paths corresponding
                 # to virtual files paths in a view

  def _preFunction(self, level, path):
    if hasattr(self, "_%sPreFunction" % level):
      return getattr(self, "_%sPreFunction" % level)(path)

    return ()

  def _postFunction(self, level, tuples, path):
    if hasattr(self, "_%sPostFunction" % level):
      return getattr(self, "_%sPostFunction" % level)(tuples, path)

    return [ tuple[0] for tuple in tuples ]

  def getDirents(self, path):
    depth = min(path.count("/"), len(self.levels) - 1)

    dirents = []
    occurrences = {}

    self._debug("get dirents of level '%s' in view '%s'" %
                ("/".join(self.levels[:depth + 1]), self.name))

    # Builds the sql query from the query string corresponding to the
    # current depth level and its parameters builded form '_preFunction'
    # function call.
    tuples = tsumufs.permsOverlay.getPermsFromQuery(self.queries[self.levels[depth]] %
                                                    self._preFunction(self.levels[depth], path))

    # Then filters the tuple-based result and format the output into a list
    # according to the '_postFunction' with current depth level.
    paths = self._postFunction(self.levels[depth], tuples, path)

    # Fills the result list with result file names, handles duplicated
    # names and save the real paths corresponding to of virtual files paths
    # for further use.
    for filepath in paths:
      name = os.path.basename(filepath)

      if occurrences.has_key(name):
        occurrences[name] += 1
        filename, fileext = os.path.splitext(name)
        name = filename + " (" + str(occurrences[name]) + ")" + fileext

      else:
        occurrences[name] = 0

      dirents.append(str(name))

      if self.isFileLevel(os.path.join(path, name)):
        self.bindings[os.path.join(path, name)] = filepath

    self._debug("Returning dirents %s" % str(dirents))
    return dirents

  def realFilePath(self, path):
    if self.isFileLevel(path):
      try:
        realpath = self.bindings[path]
      except KeyError, e:
        raise OSError(2,
                      "No such file or directory",
                      os.path.join(tsumufs.viewsPoint, path))

      return realpath

    else:
      return os.path.join(tsumufs.viewsPoint, path)

  def statFile(self, path):
    if self.isFileLevel(path):
      pathToStat = self.realFilePath(path)
    else:
      pathToStat = tsumufs.viewsPoint

    return tsumufs.cacheManager.statFile(pathToStat)

  def access(self, uid, path, mode):
    if self.isFileLevel(path):
      tsumufs.cacheManager.access(uid, self.realFilePath(path), mode)

  def isFileLevel(self, path):
    return path.count("/") != 0 and self.levels[path.count("/") - 1] == 'file'


def loadViews():
  '''
  Load all installed modules in the views directory,
  and instantiate corresponding view classes.
  '''
    
  views = []
  viewsPath = os.path.dirname(__file__)

  for view in os.listdir(os.path.abspath(viewsPath)):
    name, ext = os.path.splitext(view)
    if ext == '.py' and name != "__init__":
        module = __import__("tsumufs.views." + name, fromlist=["tsumufs.views"])
        views.append(module.viewClass())

  return views
