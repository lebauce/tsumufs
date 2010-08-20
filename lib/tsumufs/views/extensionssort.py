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
import fuse
import stat
import fnmatch

import tsumufs
from tsumufs.views import View


class ExtensionsSortView(View):
  '''
  Depth levels: category/type/file

  'category':
    Displays categories found among all files mimetypes as directories.

  'type':
    Displays types found among all files mimetypes where mime category
    equal the current directory name.

  'file':
    Displays all files where the mimetype is represented by the current
    path in the view. We concatenate the parent folder and the current folder
    to build a mimetype string like 'category/type'
  '''

  name = "Sorted by type"

  levels = ['category', 'type', 'file']

  queries = { 'category' : "SELECT DISTINCT type FROM file where type <> 'application/x-directory'",
              'type'     : "SELECT DISTINCT type FROM file where type <> 'application/x-directory'",
              'file'     : "SELECT filename, directory FROM file WHERE type = '%s/%s'" }

  def __init__(self):
    View.__init__(self)

  def _filePreFunction(self, path):
    type = os.path.basename(path)
    category = os.path.basename(os.path.dirname(path))
    return (category, type)

  def _categoryPostFunction(self, tuples, path):
    return list(set([ os.path.join(path, mimetype[0].split('/')[0]) \
                      for mimetype in tuples ]))

  def _typePostFunction(self, tuples, path):
    return list(set([ os.path.join(path, mimetype[0].split('/')[1]) \
                      for mimetype in tuples \
                      if mimetype[0].split('/')[0] == os.path.basename(path)]))

  def _filePostFunction(self, tuples, path):
    return [ os.path.join(dir, name) for name, dir in tuples]

viewClass = ExtensionsSortView