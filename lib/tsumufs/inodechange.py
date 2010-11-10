# Copyright (C) 2008  Google, Inc. All Rights Reserved.
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

import sys

import tsumufs
from dataregion import *

from ufo.database import *


class FileChangeDocument(Document, tsumufs.Debuggable):
  '''
  CouchDb document that represents any change to a file
  and the data that it points to.
  '''

  doctype       = TextField(default="FileChangeDocument")
  syncchangeid  = TextField()

  mode  = BooleanField()
  uid   = BooleanField()
  gid   = BooleanField()
  times = BooleanField()

  symlinkPath = TextField()

  @ViewField.define('filechange')
  def by_syncchangeid(doc):
    if doc['doctype'] == "FileChangeDocument":
      yield doc['syncchangeid'], doc

  def __repr__(self):
    '''
    Pretty printer method to give a bit more transparency into the
    object.
    '''

    rep = '<FileChangeDocument %s' % self.syncchangeid

    if self.times:
      rep += ' times: %s' % self.times
    if self.mode:
      rep += ' mode: %s' % self.mode
    if self.uid:
      rep += ' uid: %s' % self.uid
    if self.gid:
      rep += ' gid: %s' % self.gid
    if self.symlinkPath:
      rep += ' symlinkPath: %s' % self.symlinkPath

    rep += '>'

    return rep

  def __str__(self):
    return repr(self)

  def __init__(self, **hargs):
    self._setName('FileChangeDocument')
    sys.excepthook = tsumufs.syslogExceptHook

    Document.__init__(self, **hargs)

    self._dataRegions = DocumentHelper(DataRegionDocument, tsumufs.dbName, batch=True)

  def addDataChange(self, start, end, data):
    '''
    Method to add a representation of a change in data in an inode. Can
    throw an InvalidRegionSpecified and
    RegionDoesNotMatchLengthError. Note that this method attempts to
    auto-merge the change with other lists already existing if it
    can.
    '''

    accumulator = DataRegionDocument(start=start, end=end, data=data)

    for r in self._dataRegions.by_filechangeid(key=self.id):
      if r.canMerge(accumulator):
        accumulator = accumulator.mergeWith(r)
      else:
        self._dataRegions.create(filechangeid=self.id,
                                 start=accumulator.start,
                                 end=accumulator.end,
                                 data=accumulator.data)
        accumulator = r

    self._dataRegions.create(filechangeid=self.id,
                             start=accumulator.start,
                             end=accumulator.end,
                             data=accumulator.data)

  def addMetaDataChange(self, **metachanges):
    '''
    Method to add a representation of meta changes. 
    '''

    for metachange in metachanges:
      if metachanges[metachange]:
        setattr(self, metachange, metachanges[metachange])

  def getDataChanges(self):
    '''
    Method to return a list of changes made to the data
    pointed to by this inode.
    '''

    return [ doc for doc in self._dataRegions.by_filechangeid(key=self.id) ]

  def getMetaDataChanges(self):
    '''
    Method to return a list of changes made to the meta datas
    pointed to by this inode.
    '''

    return self.mode, self.uid, self.gid, self.times

  def clearDataChanges(self):
    '''
    Method to clear the dataregions list for this change.
    '''

    for dataregion in self._dataRegions.by_filechangeid(key=self.id):
      self._dataRegions.delete(dataregion)

