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
import fuse
import stat
import errno

import tsumufs
from tsumufs.views import View
from tsumufs.extendedattributes import extendedattribute

from ufo.database import DocumentHelper
from ufo.views import TaggedSyncDocument

import gettext
_ = gettext.gettext

class StaredByTagView(View, tsumufs.Debuggable):
  '''
  Tsumufs view that sort the filesystem contents by tags.

  The first depth level of a view display all TAGS existing on
  files of the filesystem.

  This view is based on the python-ufo view TaggedSyncDocument,
  and provides custom behaviors for tag creation/deletion and
  assignment of tags to files.

  - Create a tag: mkdir in the 'tag' level of the view.
  - Delete a tag: unlink on a diretory in the 'tag' level of
                  a view.
  - Assign a tag: rename a file from the overlay to a directory
                  of the 'tag' level.
  '''

  name = _("Stared by tag")

  levels = ['tag']

  docClass = TaggedSyncDocument

  _pendingTags = []

  def __init__(self):
    View.__init__(self)

    self._syncDocs = DocumentHelper(tsumufs.SyncDocument, tsumufs.dbName)

  def getDirents(self, path):
    '''
    Add to the result of getDirent on the parent call View,
    and add the pending tags dir to the dirents if path is at 'tag' level.
    '''

    returned = []
    for dirent in View.getDirents(self, path):
      yield dirent
      returned.append(dirent.filename)

    if not path.count(os.sep):
      for tag in self._pendingTags:
        if tag not in returned:
          yield self.docClass(filename=tag, mode=0555 | stat.S_IFDIR)
        else:
          returned.remove(tag)

  def makeDir(self, path, mode, uid, gid):
    '''
    Create a tag if path is at 'tag' level.
    '''
    if self.isFileLevel(path):
      View.makeDir(self, path, mode)

    tag = os.path.basename(path)
    try:
      self._syncDocs.by_tag(key=tag, pk=True)
      raise OSError(errno.EEXIST, os.strerror(errno.EEXIST))

    except tsumufs.DocumentException, e:
      if tag in self._pendingTags:
        raise OSError(errno.EEXIST, os.strerror(errno.EEXIST))

      self._pendingTags.append(tag)

  def rename(self, old, new):
    '''
    Assign a tag to a file.
    '''

    if not self.isFileLevel(new):
      View.rename(self, old, new)

    tag = os.path.basename(os.path.dirname(new))
    overlaypath = self.overlayPath(old)

    if tag in tsumufs.fsOverlay[overlaypath].tags:
      raise OSError(errno.EEXIST, "File already tagged with this tag.")

    tsumufs.fsOverlay.tag(overlaypath, tag)

    self._debug('Add "tags" metadata change for %s' % overlaypath)
    tsumufs.syncLog.addMetadataChange(overlaypath)

  def removeCachedFile(self, path, removeperm=False):
    '''
    Delete a tag if path is at 'tag' level.
    '''

    if self.isFileLevel(path):
      tag = os.path.basename(os.path.dirname(path))

      realpath = self.realFilePath(path)
      tsumufs.fsOverlay.tag(realpath, tag, remove=True)

      self._debug('Add "tags" metadata change for %s' % realpath)
      tsumufs.syncLog.addMetadataChange(realpath)

    else:
      tag = os.path.basename(path)

      for doc in self._syncDocs.by_tag(key=tag):
        tsumufs.fsOverlay.tag(os.path.join(doc.dirpath, doc.filename), tag, remove=True)

        self._debug('Add "tags" metadata change for %s'
                    % os.path.join(doc.dirpath, doc.filename))
        tsumufs.syncLog.addMetadataChange(os.path.join(doc.dirpath, doc.filename))


viewClass = StaredByTagView


@extendedattribute('file', 'tsumufs.staredbytag.tag')
def xattr_tag(type_, path, value=None):
  if value:
    if tsumufs.viewsManager.isAnyViewPath(path):
      path = tsumufs.viewsManager.realFilePath(path)

    pathinview = os.path.join(os.sep, tsumufs.viewsPoint, StaredByTagView.name,
                              value, os.path.basename(path))

    try:
      tsumufs.viewsManager.rename(path, pathinview)

      return
    except Exception, e:
      return -e.errno

  return -errno.EOPNOTSUPP

@extendedattribute('file', 'tsumufs.staredbytag.untag')
def xattr_untag(type_, path, value=None):
  if value:
    pathinview = os.path.join(os.sep, tsumufs.viewsPoint, StaredByTagView.name,
                              value, os.path.basename(path))

    try:
      tsumufs.viewsManager.removeCachedFile(pathinview, removeperm=True)

      return
    except Exception, e:
      return -e.errno

  return -errno.EOPNOTSUPP

@extendedattribute('file', 'tsumufs.staredbytag.tags')
def xattr_tags(type_, path, value=None):
  if not value:
    return str(",".join(tsumufs.fsOverlay[path].tags))

  return -errno.EOPNOTSUPP

@extendedattribute('any', 'tsumufs.staredbytag.path')
def xattr_mysharesPath(type_, path, value=None):
  if not value:
    return str(os.path.join(tsumufs.mountPoint, tsumufs.viewsPoint[1:], StaredByTagView.name))

  return -errno.EOPNOTSUPP
