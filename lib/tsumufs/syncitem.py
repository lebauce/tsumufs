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

'''TsumuFS, a fs-based caching filesystem.'''

import tsumufs
from inodechange import *
from dataregion import *

from ufo.database import *


class SyncChangeDocument(Document):
  '''
  CouchDb document that encapsulates a change to the filesystem in the SyncLog.
  Note that this does /not/ include DataRegions -- specifically that should be
  in a different list.
  '''

  doctype = TextField(default="SyncChangeDocument")
  date    = FloatField()

  type      = TextField()     # 'new|'link|'unlink|'change|'rename

  file_type = TextField()     # 'file|'dir|'socket|'fifo|'device
  dev_type  = TextField()     # 'char|'block
  major     = IntegerField()
  minor     = IntegerField()

  old_fname = TextField()
  new_fname = TextField()
  filename  = TextField()

  _REQUIRED_KEYS = {
    'new':    [ 'file_type', 'filename' ],
    'link':   [ 'filename' ],
    'change': [ 'filename' ],
    'unlink': [ 'filename' ],
    'rename': [ 'old_fname', 'new_fname' ],
    }

  _VALID_TYPES      = [ 'new', 'link', 'unlink', 'change', 'rename' ]
  _VALID_FILE_TYPES = [ 'file', 'dir', 'symlink', 'socket', 'fifo', 'device' ]
  _VALID_DEV_TYPES  = [ 'char', 'block' ]

  def __init__(self, **hargs):
    if hargs:
      type = hargs['type']

      if type not in self._VALID_TYPES:
        raise TypeError('Invalid change type %s' % type)

      for key in self._REQUIRED_KEYS[type]:
        if key not in hargs.keys():
          raise TypeError('Missing required key %s' % key)

    Document.__init__(self, **hargs)

  def __repr__(self):
    return (('<SyncItem:'
             ' type: %s'
             ' filename: %s'
             ' date: %d>')
            % (self.type,
               self.filename,
               self.date))

  def __str__(self):
    return repr(self)

  @ViewField.define('syncchange')
  def by_id(doc):
    if doc['doctype'] == "SyncChangeDocument":
      yield doc['_id'], doc

  @ViewField.define('syncchange')
  def by_date(doc):
    if doc['doctype'] == "SyncChangeDocument":
      yield doc['date'], doc

  @ViewField.define('syncchange')
  def by_filename(doc):
    if doc['doctype'] == "SyncChangeDocument":
      if doc['filename']:
        yield doc['filename'], doc
      else:
        yield doc['new_fname'], doc

  @ViewField.define('syncchange')
  def by_filename_and_type(doc):
    if doc['doctype'] == "SyncChangeDocument":
      yield [doc['filename'], doc['type']], doc

  @ViewField.define('syncchange')
  def by_dir_prefix(doc):
    from os import sep
    from os.path import dirname
    if doc['doctype'] == "SyncChangeDocument" and doc['filename']:
      last = ''
      current = dirname(doc['filename'])
      while current != sep and current != last:
        yield current, doc
        last = current
        current = dirname(current)
