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
import pwd
import fuse
import stat
import errno
import traceback

import tsumufs
from tsumufs.views import View
from tsumufs.extendedattributes import extendedattribute

from ufo import config
from ufo import utils
from ufo import errors
from ufo.views import MySharesSyncDocument
from ufo.filesystem import SyncDocument
from ufo.database import DocumentHelper, DocumentException
from ufo.debugger import Debugger
from ufo.errors import *

import xmlrpclib as rpc
from ipalib.rpc import KerbTransport

import gettext
_ = gettext.gettext

class MySharesView(View, Debugger):

  name = _("My shares")

  levels = ['buddy']

  docClass = MySharesSyncDocument

  _pendingFriends = []
  _fullnameBindings = {}

  def __init__(self):
    self._syncDocs = DocumentHelper(tsumufs.SyncDocument, tsumufs.dbName)

    View.__init__(self)

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

    if not path.count(os.sep):
      for friend in self._pendingFriends:
        if friend['fullname'] not in returned:
          yield self.docClass(filename=friend['fullname'], mode=0555 | stat.S_IFDIR,
                              uid=friend['uid'], gid=friend['gid'])
        else:
          returned.remove(friend['fullname'])

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
      remote = rpc.Server(config.account_host, KerbTransport())
      owner  = unicode(os.environ['USER'], "utf8")
      friend = unicode(os.path.basename(path), "utf8")

      self.debug("Sending new friend invitation from '%s' to '%s'"
                 % (owner, friend))

      try:
        remote.account.request_friend(friend)
      except rpc.Fault, f:
        raise utils.fault_to_exception(f)

    except (AlreadyFollowerError, PendingFollowerError), e:
      # If 'friend' is already follower and the virtual folder of
      # this user does not exists, this is because he is follower by
      # no shares has been set yet, so only add an entry to the pending
      # friend list to display the folder.
      pass

    except UserNotFoundError, e:
      raise OSError(errno.ENOENT, str(e))

    except Exception, e:
      self.debug("Got exception while calling account.request_friend (%s)" % str(e))
      self.debug_exception()

      raise OSError(errno.EACCES, str(e))

    self._pendingFriends.append(utils.get_user_infos(friend))
    self._fullnameBindings[friend] = utils.get_user_infos(friend)['fullname']

  def rename(self, old, new):
    try:
      # Replace the full name of the friend by its uid within the path
      new = self.hackedPath(new)

      remote = rpc.Server(config.sync_host, KerbTransport())
      owner  = os.environ['USER'].encode('utf8')

      friend_uid = os.path.basename(os.path.dirname(new))
      friend = utils.get_user_infos(uid=int(friend_uid))['login']

      document = self._syncDocs.by_path(key=self.overlayPath(old), pk=True)

      self.debug("Sharing file %s from '%s' to '%s'" % (document.id, owner, friend))

      try:
        remote.sync.add_new_share(friend, document.id, "R")
      except rpc.Fault, f:
        raise utils.fault_to_exception(f)

    except AlreadySharedDocError, e:
      raise OSError(errno.EEXIST, str(e))

    except Exception, e:
      self.debug("Got exception while calling sync.add_new_share (%s)" % str(e))
      self.debug_exception()

      raise OSError(errno.EACCES, str(e))

  def removeCachedFile(self, path, removeperm=False):
    try:
      # Replace the full name of the friend by its uid within the path.
      uidpath = self.hackedPath(path)

      # Here we want to remove a file that correspond to an active
      # share with a friend.
      if self.isFileLevel(path):
        remote = rpc.Server(config.sync_host, KerbTransport())
        owner  = unicode(os.environ['USER'], "utf8")

        friend_uid = uidpath.split(os.sep)[1]
        friend = utils.get_user_infos(uid=int(friend_uid))['login']

        document = self._syncDocs.by_path(key=self.realFilePath(path), pk=True)

        self.debug("%s remove %s from the share of '%s'" % (owner, friend, document.id))

        try:
          remote.sync.remove_participant_from_share(friend, document.id)
        except rpc.Fault, f:
          raise utils.fault_to_exception(f)

      # Here we want to remove a directory that correspond to a friend.
      elif path.count(os.sep) == 1:
        remote = rpc.Server(config.account_host, KerbTransport())
        owner  = unicode(os.environ['USER'], "utf8")

        friend_uid = os.path.basename(uidpath)
        friend = utils.get_user_infos(uid=int(friend_uid))['login']

        self.debug("%s remove %s from its friends" % (owner, friend))

        try:
          remote.account.remove_friend(friend)
        except rpc.Fault, f:
          raise utils.fault_to_exception(f)

        if path.split(os.sep)[1] in self._pendingFriends:
          self._pendingFriends.remove(self._pendingFriends)

      else:
        raise OSError(errno.EACCES, os.strerror(errno.EACCES))

    except Exception, e:
      self.debug_exception()
      raise OSError(errno.EACCES, str(e))


viewClass = MySharesView


@extendedattribute('file', 'tsumufs.myshares.share')
def xattr_tag(type_, path, value=None):
  if value:
    if tsumufs.viewsManager.isAnyViewPath(path):
      path = tsumufs.viewsManager.realFilePath(path)

    pathinview = os.path.join(os.sep, tsumufs.viewsPoint, MySharesView.name,
                              value, os.path.basename(path))

    try:
      tsumufs.viewsManager.rename(path, pathinview)

      return
    except Exception, e:
      return -e.errno

  return -errno.EOPNOTSUPP

@extendedattribute('file', 'tsumufs.myshares.unshare')
def xattr_untag(type_, path, value=None):
  if value:
    pathinview = os.path.join(os.sep, tsumufs.viewsPoint, MySharesView.name,
                              value, os.path.basename(path))

    try:
      tsumufs.viewsManager.removeCachedFile(pathinview, removeperm=True)

      return
    except Exception, e:
      return -e.errno

  return -errno.EOPNOTSUPP

@extendedattribute('file', 'tsumufs.myshares.participants')
def xattr_shareParticipants(type_, path, value=None):
  if not value:
    try:
      participants = []
      viewpath = str(os.path.join(os.sep, tsumufs.viewsPoint, MySharesView.name))
      for dirent in tsumufs.viewsManager.getDirents(viewpath):
        participantpath = os.path.join(viewpath, dirent.filename)

        for doc in tsumufs.viewsManager.getDirents(participantpath):
          if tsumufs.viewsManager.realFilePath(os.path.join(participantpath, doc.filename)) == path:
            participants.append(dirent.filename)
            break;

      return str(",".join(participants))
    except DocumentException, e:
      return str(e)

  return -errno.EOPNOTSUPP

@extendedattribute('any', 'tsumufs.myshares.path')
def xattr_mysharesPath(type_, path, value=None):
  if not value:
    return str(os.path.join(tsumufs.mountPoint, tsumufs.viewsPoint[1:], MySharesView.name))

  return -errno.EOPNOTSUPP
