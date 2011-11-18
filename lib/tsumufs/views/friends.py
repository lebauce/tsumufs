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

'''UFO file synchronization client library.'''

import os
import sys
import fuse
import stat
import errno
import traceback

import tsumufs
from tsumufs.views import View
from tsumufs.extendedattributes import extendedattribute

from ufo import config, utils, errors
from ufo.sharing import FriendDocument
from ufo.views import FriendSyncDocument
from ufo.database import DocumentHelper, DocumentException
from ufo.debugger import Debugger
from ufo.errors import *
from ufo.user import user

import gettext
_ = gettext.gettext

class FriendsView(View, Debugger):

  name = _(".My friends")

  levels = ['buddy']

  docClass = FriendSyncDocument

  _fullnameBindings = {}

  def __init__(self, *args, **kw):
    super(FriendsView, self).__init__(*args, **kw)

  def hackedPath(self, path):
    # Replace the full name name of the provider by his uid,
    # as the python-ufo BuddyShares view use uid to retrieve docs
    if path.count(os.sep) >= len(self.levels):
      dirpath = os.sep.join(path.split(os.sep)[:2])
      uid = self.statFile(dirpath).st_uid
      listpath = path.split(os.sep)
      listpath[1] = str(uid)
      return os.sep.join(listpath)

    return path

  def statFile(self, path):
    if (path.count(os.sep) == 1
        and self._fullnameBindings.has_key(os.path.basename(path))):
      listpath = path.split(os.sep)
      listpath[1] = self._fullnameBindings[os.path.basename(path)]
      path = os.sep.join(listpath)

    return View.statFile(self, path)

  def getDirents(self, path):
    returned = []
    for dirent in View.getDirents(self, path):
      returned.append(dirent.filename)
      yield dirent

  def makeDir(self, path, mode, uid, gid):
    if self.levels[path.count("/") - 1] != "buddy":
      View.mkdir(self, path, mode)

    try:
      if self.statFile(path):
        raise OSError(errno.EEXIST, os.strerror(errno.EEXIST))

    except OSError, e:
      if e.errno != errno.ENOENT:
        raise

    try:
      friend = os.path.basename(path)
      user.request_friend(friend)

    except (AlreadyFriendError, PendingFriendError), e:
      self._debug("Already friend or pending friend")
      raise OSError(errno.EEXIST, os.strerror(errno.EEXIST))

    except UserNotFoundError, e:
      self._debug("User not found")
      raise OSError(errno.ENOENT, str(e))

    except Exception, e:
      self._debug("Got exception while calling account.request_friend (%s)" % str(e))
      self.debug_exception()

      raise OSError(errno.EACCES, str(e))

    # self._pendingFriends.append(utils.get_user_infos(friend))
    # self._fullnameBindings[friend] = utils.get_user_infos(friend)['fullname']

    return 0

  def removeCachedFile(self, path, removeperm=False):
    try:
      # Replace the full name of the friend by its uid within the path.
      friend = os.path.basename(path)

      self.debug("Remove %s from friends list" % friend)
      user.remove_friend(friend)

    except Exception, e:
      self.debug_exception()
      raise OSError(errno.EACCES, str(e))


@extendedattribute('dir', 'tsumufs.friends.status')
def xattr_friend_status(type_, path, value=None):
  if not value:
    try:
      friend = DocumentHelper(FriendDocument, tsumufs.dbName).by_login(key=os.path.basename(path), pk=True)
      return str(friend.status)

    except Exception, e:
      raise OSError(errno.ENOENT, str(e))

  return -errno.EOPNOTSUPP

@extendedattribute('any', 'tsumufs.friends.path')
def xattr_friendsPath(type_, path, value=None):
  if not value:
    return str(os.path.join(tsumufs.mountPoint, tsumufs.viewsPoint[1:], FriendsView.name))

  return -errno.EOPNOTSUPP

viewClass = FriendsView

