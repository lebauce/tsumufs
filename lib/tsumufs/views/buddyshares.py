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
from tsumufs.extendedattributes import extendedattribute

from ufo import utils
from ufo import errors
from ufo.views import BuddySharesSyncDocument

import gettext
_ = gettext.gettext

class BuddySharesView(View):

  name = _("Buddy shares")

  levels = ['buddy']

  docClass = BuddySharesSyncDocument

  def __init__(self):
    View.__init__(self)

  def hackedPath(self, path):
    # Replace the full name of the provider by his uid,
    # as the python-ufo BuddyShares view use uid to retrieve docs
    if path.count(os.sep) >= len(self.levels):
      dirpath = os.sep.join(path.split(os.sep)[:2])
      uid = self.statFile(dirpath).st_uid
      listpath = path.split(os.sep)
      listpath[1] = str(uid)
      return os.sep.join(listpath)

    return path


viewClass = BuddySharesView


@extendedattribute('any', 'tsumufs.buddyshares.path')
def xattr_mysharesPath(type_, path, value=None):
  if not value:
    return str(os.path.join(tsumufs.mountPoint, tsumufs.viewsPoint[1:], BuddySharesView.name))

  return -errno.EOPNOTSUPP
