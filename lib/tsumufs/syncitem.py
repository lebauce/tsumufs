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

import tsumufs
from inodechange import *
from dataregion import *

from ufo.database import *


class SyncChangeDocument(UTF8Document):
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

  change    = DictField()

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

  def __init__(self, *args, **hargs):
    if hargs:
      type = hargs['type']

      if type not in self._VALID_TYPES:
        raise TypeError('Invalid change type %s' % type)

      for key in self._REQUIRED_KEYS[type]:
        if key not in hargs.keys():
          raise TypeError('Missing required key %s' % key)

    super(SyncChangeDocument, self).__init__(*args, **hargs)

  def __repr__(self):
    return str(self)

  def __str__(self):
    return ('<SyncItem: type: %s filename: %s date: %s>'
            % (self.type,
               self.filename,
               self.date))

  by_filename = ViewField('syncchange',
    language='javascript',
    map_fun="function (doc) {"
              "if (doc.doctype === 'SyncChangeDocument') {" \
                "if (doc.filename)" \
                  "emit([doc.filename, doc.type, doc.date], doc);" \
                "else " \
                  "emit([doc.new_fname, doc.type], doc);" \
                "}" \
              "}")

  by_dir_prefix = ViewField('syncchange',
    language='javascript',
    map_fun="function (doc) {"
              "if (doc.doctype === 'SyncChangeDocument') {" \
                "var last = '';" \
                "var current = doc.filename;" \
                "while (current !='/' && current != last) {" \
                  "emit(current, doc);" \
                  "current = current.slice(0, current.lastIndexOf('/'));" \
                "}" \
              "}" \
            "}")

  @property
  def filechange(self):
      return FileChangeDocument(id=self.id, **self.change)

