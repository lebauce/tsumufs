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
from ufo.user import user
import ufo.acl as acl

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

    friend = os.path.basename(path)
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

      else:
        raise OSError(errno.EACCES, os.strerror(errno.EACCES))

    except Exception, e:
      self.debug_exception()
      raise OSError(errno.EACCES, str(e))


@extendedattribute('file', 'tsumufs.myshares.share')
def xattr_share(type_, path, friend=None):
   if tsumufs.viewsManager.isAnyViewPath(path):
     path = tsumufs.viewsManager.realFilePath(path)

   try:
     posix_acl = tsumufs.cacheManager.getxattr(path, acl.ACL_XATTR)
   except KeyError, e:
     current_acl = acl.ACL.from_mode(tsumufs.cacheManager.statFile(path).st_mode)
   else:
     current_acl = acl.ACL.from_xattr(posix_acl)

   current_acl.append(acl.ACE(acl.ACL_USER,
                              acl.ACL_READ,
                              utils.get_user_infos(login=friend)['uid']))

   tsumufs.cacheManager.setxattr(path, acl.ACL_XATTR, current_acl.to_xattr())

   return 0

@extendedattribute('file', 'tsumufs.myshares.unshare')
def xattr_unshare(type_, path, value=None):
   if tsumufs.viewsManager.isAnyViewPath(path):
     path = tsumufs.viewsManager.realFilePath(path)

   try:
     posix_acl = tsumufs.cacheManager.getxattr(path, acl.ACL_XATTR)
   except KeyError, e:
     return errno.ENODATA

   current_acl = acl.ACL.from_xattr(posix_acl)
   for i, ace in enumerate(current_acl):
       if ace.kind & acl.ACL_USER:
           del current_acl[i]
           break

   tsumufs.cacheManager.setxattr(path, acl.ACL_XATTR, current_acl.to_xattr())

   return 0

@extendedattribute('file', 'tsumufs.myshares.participants')
def xattr_shareParticipants(type_, path, value=None):

  if not value:
    try:
      participants = []
      current_acl = acl.ACL.from_xattr(tsumufs.cacheManager.getxattr(path, acl.ACL_XATTR))
      for ace in current_acl:
          if ace.kind & acl.ACL_USER:
              participants.append(ace.qualifier)
      return str(",".join(participants))
    except DocumentException, e:
      return str(e)

  return -errno.EOPNOTSUPP

@extendedattribute('any', 'tsumufs.myshares.path')
def xattr_mysharesPath(type_, path, value=None):
  if not value:
    return str(os.path.join(tsumufs.mountPoint, tsumufs.viewsPoint[1:], MySharesView.name))

  return -errno.EOPNOTSUPP

@extendedattribute('any', 'system.nfs4_acl')
def xattr_nfs4_acl(type_, path, value=None):
  raise OSError(errno.ENODATA, os.strerror(errno.ENODATA))


viewClass = MySharesView

