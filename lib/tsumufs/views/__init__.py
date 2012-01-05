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

'''TsumuFS is a disconnected, offline caching filesystem.'''

import os
import sys
import traceback
import errno
import stat
import posixpath

import tsumufs

from ufo.database import DocumentHelper
from ufo.filesystem import SyncDocument

class View(tsumufs.Debuggable):
  '''
  Base class for tsumufs views development.
  Tsumufs views are virtual directories that provides custom presentation
  of the overlay files like sorting, custom appearance, staring, etc.
  This is possible since tsumufs based on CouchedFilesystem api from the
  python-ufo library that manage the metadatas of the filesystem in a
  CouchDb database.

  A tsumufs view is based on a python-ufo view, the minimal code required
  is the following:

    # Import the python-ufo view class
    from ufo.views import SortedByTypeSyncDocument

    class SortedByTypeView(View):

      # Name of the view.
      name = "Sorted by type"

      # Specify the levels of the view. Levels are the representation of
      # the depth levels of the view file tree.
      #
      # For the view that sort files by mimetype, an example tree could be:
      #
      # - "Sorted By Type" - "application"
      #                           - "pdf"
      #                           - "doc"
      #                           - "x-directory"
      #
      #                    - "text"
      #                           - "xml"
      #                           - "plain"
      #                           - "python"
      #                           - "x-empty"
      #
      levels = ['category', 'type']

      # Specify the python-ufo views class imported at head.
      docClass = SortedByTypeSyncDocument

    # Assign the tsumufs view class to the global variable viewClass
    # to allow to the view loader to know which class has to be
    # instantiated at startup.
    viewClass = SortedByTypeView

  All system calls could be called on a view instance by the views manager,
  so its could be overridden to provides a custom behavior in each view.
  If a system call is'nt overridden in the view class, the default system
  call for all view will be call.

  At the user side, views are accessible in the overlay mount point,
  in the directory specified by the tsumufs mount option 'viewspoint'.
  '''

  name = ""               # Displayed name of the view root directory.

  levels = []             # Ordered list of the depth levels names
                          # of the view.

  bindings = {}           # Hash of real files paths corresponding
                          # to virtual files paths in a view.

  docClass = None         # Document class of the view.

  fileClass = None        # File class of the view.

  viewDocuments = None    # Document helper to get the view documents.

  parentFolder = None     # Parent folder for the view.

  def __init__(self):
    self.viewDocuments = DocumentHelper(self.docClass, tsumufs.dbName)

    if not self.parentFolder:
      self.parentFolder = tsumufs.viewsPoint

  def getRootDocs(self):
    yield SyncDocument(dirpath=self.parentFolder,
                       filename=self.name,
                       mode=0555 | stat.S_IFDIR)

  def getDirents(self, path):
    '''
    Return the dirents from a view depth level. The levels correspond to
    the path nodes after the root directory of the view.

     - When the number of levels of the path is equal or higher than the
       number of the views ones, the returned document are documents
       contained in the filesystem. It's also called the 'file' level.

     - When the number of levels of the path is lower than the number of
       the views ones, documents returned are virtual folders that does'nt
       exist in the filesystem.

    This method computes the levels strings required to call the 'getDocuments'
    method of a view from the fusepath, and handles each returned documents to
    ensure unique filenames in the result dirents.
    '''

    fields = {}
    occurrences = {}

    if self.levels:
      filters = self.hackedPath(path).split('/')[1:]
      for index, filter in enumerate(filters):
        fields[self.levels[index]] = filter

    # Fills the result list with result filenames, handles duplicated
    # names and save the real paths corresponding to of virtual files paths
    # for further use.
    for doc in self.viewDocuments.getDocuments(**fields):
      try:
        if occurrences.has_key(doc.filename):
          occurrences[doc.filename] += 1
          filename, fileext = os.path.splitext(doc.filename)
          customname = filename + " (" + str(occurrences[doc.filename]) + ")" + fileext

        else:
          occurrences[doc.filename] = 0
          customname = doc.filename

        if self.isFileLevel(os.path.join(path, customname)):
          self.bindings[os.path.join(path, customname)] = os.path.join(doc.dirpath, doc.filename)

        doc.filename = customname

      except Exception, e:
        exc_info = sys.exc_info()

        self._debug('*** Unhandled exception occurred')
        self._debug('***     Type: %s' % str(exc_info[0]))
        self._debug('***    Value: %s' % str(exc_info[1]))
        self._debug('*** Traceback:')

        for line in traceback.extract_tb(exc_info[2]):
          self._debug('***    %s(%d) in %s: %s' % line)

        continue

      yield doc

  def statFile(self, path):
    '''
    This method check the path to retrieve the real fusepath of a file
    represented by o virtual path of a view. For example, in the view
    that sort files by mimetype:

    "Sorted By Type" / "application" / "pdf" / "report.pdf" ->
    "Bob" / "Work" / "2010" / "report.pdf"

    If the path correspond to a virtual folder, the stats of the viewPoint
    is return as the folder does not really exist.
    '''

    if self.isFileLevel(path):
      if not self.bindings.has_key(path):
        # Here we need to call getDirent as the list bindings
        # could not contain our file path binding yet
        for doc in self.getDirents(os.path.dirname(path)):
          if doc.filename == os.path.basename(path):
            break

      # Forwards to cacheManager to check the caching policy
      return tsumufs.cacheManager.statFile(self.realFilePath(path))

    else:
      document = None
      rootDirStats = tsumufs.cacheManager.statFile(self.parentFolder)

      if path and path != '/':
        for doc in self.getDirents(os.path.dirname(path)):
          if doc.filename == os.path.basename(path):
            document = doc

        if not document:
          raise OSError(errno.ENOENT, os.strerror(errno.ENOENT))

      else:
        for doc in self.getRootDocs():
          if path.startswith(doc.path):
            document = doc
            break

        if not document:
          return rootDirStats

      # Fill the missing parts of 'stats' with the one of the root folder
      for key in rootDirStats._keys:
        if getattr(document.stats, key, None) == None:
          setattr(document.stats, key, getattr(rootDirStats, key))

      return document.get_stats()

  def getxattr(self, path, key):
    '''
    Default 'getxattr' system call behavior in a view.
    '''
    raise OSError(errno.EOPNOTSUPP, os.strerror(errno.EOPNOTSUPP))

  def makeDir(self, path, mode, uid, gid):
    '''
    Default 'makeDir' system call behavior in a view.
    '''
    raise OSError(errno.EACCES, os.strerror(errno.EACCES))

  def access(self, uid, path, mode):
    '''
    Default 'access' system call behavior in a view.
    '''
    if self.isFileLevel(path):
      tsumufs.cacheManager.access(uid, self.realFilePath(path), mode)

  def rename(self, old, new):
    '''
    Default 'rename' system call behavior in a view.
    '''
    raise OSError(errno.EACCES, os.strerror(errno.EACCES))

  def removeCachedFile(self, fusepath, removeperm=False):
    '''
    Default 'unlink'/'rmdir' behavior.
    The name of this method is not relevant but it is the name
    used in the cache manager, so do not modify it for instance.
    '''
    raise OSError(errno.EACCES, os.strerror(errno.EACCES))

  def realFilePath(self, path):
    '''
    Retrieve the corresponding real fusepath of a virtual path.
    '''
    if self.isFileLevel(path):
      try:
        realpath = self.bindings[path]
      except KeyError, e:
        self._debug("Binding not found for %s (%s)" % (path, str(self.bindings)))
        raise OSError(errno.ENOENT, os.strerror(errno.ENOENT))

      return realpath

    else:
      return os.path.join(self.parentFolder, path)

  def overlayPath(self, path):
    return os.path.join(os.sep, self.parentFolder, path)

  def hackedPath(self, path):
    return path

  def relPath(self, path):
    if self.mountPoint != '/':
      viewPath = path.partition(self.mountPoint + '/')[2]
    else:
      viewPath = path.partition(self.mountPoint)[2]

    if viewPath:
      return "/" + viewPath

    return ""

  def isFileLevel(self, path):
    return self.levels and path.count(os.sep) > len(self.levels)

  @property
  def mountPoint(self):
    return posixpath.join(self.parentFolder, self.name)


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
      try:
        module = __import__("tsumufs.views." + name, fromlist=["tsumufs.views"])
        views.append(module.viewClass())

      except Exception, e:
          pass

  return views
