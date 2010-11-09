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

import tsumufs
from tsumufs.views import View

from ufo.views import SortedByTypeSyncDocument


class SortedByTypeView(View):
  '''
  Tsumufs view that sort the filesystem contents by mimetype.

  The first depth level of a view display all CATEGORIES of files
  in the overlay. The second level display all TYPES of files within
  a category.

  This view is entirely based on the python-ufo view SortedByTypeView,
  and do not provides any custom behavior for system calls.
  '''

  name = "Sorted by type"

  levels = ['category', 'type']

  docClass = SortedByTypeSyncDocument

viewClass = SortedByTypeView