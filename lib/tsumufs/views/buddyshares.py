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

import tsumufs
from tsumufs.views import View


class BuddySharesView(View):
  '''
  Depth levels: category/type/file

  'buddy':
    Displays friends who share documents with me as directories.

  'file':
    Displays all files where the owner is represented by the current
    path in the view.
  '''

  name = "Buddy shares"

  levels = ['buddy', 'file']

  queries = { 'buddy' : "SELECT DISTINCT uid FROM file where uid <> %d AND directory <> '/'",
              'file'  : "SELECT filename, directory FROM file WHERE uid = %s AND directory <> '/'" }

  uidBindings = {}

  def __init__(self):
    View.__init__(self)

  def _buddyPreFunction(self, path):
    return (os.getuid(),)

  def _filePreFunction(self, path):
    return (self.uidBindings[os.path.basename(path)],)

  def _buddyPostFunction(self, tuples, path):
    return [ os.path.join(path, self._getCorrespondingName(uid[0])) \
             for uid in tuples ]

  def _filePostFunction(self, tuples, path):
    return [ os.path.join(dir, name) for name, dir in tuples]

  def _getCorrespondingName(self, uid):
    # TODO: Retrieve a more user-friendly name
    name = str(uid)
    self.uidBindings[name] = uid
    return str(name)

viewClass = BuddySharesView