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

from ufo.database import Document, TextField, IntegerField, ViewField


class RangeError(Exception):
  '''
  Exception for representing a range error.
  '''

  pass


class RegionError(Exception):
  '''
  Exception to signal when a general region error has occured.
  '''

  pass


class RegionLengthError(RegionError):
  '''
  Exception to signal when a region length does not match it's
  range.
  '''

  pass


class RegionOverlapError(RegionError):
  '''
  Exception to signal when a region overlap error has
  occurred. Typically when a DataRegion::mergeWith call has been made
  with the argument being a region that cannot be merged.
  '''

  pass


class DataRegionDocument(Document):
  '''
  CouchDb document that represents a region of data in a file.

  This class is specifically used for managing the changes in files as
  stored in the cache on disk.
  '''

  doctype       = TextField(default="DataRegionDocument")
  filechangeid  = TextField()

  data   = TextField()
  start  = IntegerField()
  end    = IntegerField()
  length = IntegerField()

  def __len__(self):
    '''
    Return the length of the region.

    Returns:
      Integer

    Raises:
      None
    '''

    return self.length

  def __repr__(self):
    '''
    Method to display a somewhat transparent representation of a
    DataRegionDocument object.
    '''

    return('<DataRegionDocument [%d:%d] (%d): %s>'
           % (self.start, self.end, self.length, repr(self.data)))

  def __init__(self, **hargs):
    '''
    Initializer. Can raise InvalidRegionSpecifiedError and
    RegionDoesNotMatchLengthError.
    '''

    if hargs:
      if (hargs['end'] < hargs['start']):
        raise RangeError, ('End of range is before start (%d, %d)'
                           % (hargs['start'], hargs['end']))

      if ((hargs['end'] - hargs['start']) != len(hargs['data'])):
        raise RegionLengthError, (('Range specified (%d-%d) does not match '
                                   'the length of the data (%d) given (%s).')
                                  % (hargs['start'], hargs['end'],
                                     len(hargs['data']), repr(hargs['data'])))

      hargs['length'] = len(hargs['data'])

    Document.__init__(self, **hargs)

  def canMerge(self, dataregion):
    if ((dataregion.start == self.start) and   # |---|
        (dataregion.end == self.end)):         # |===|
      return 'perfect-overlap'

    elif ((dataregion.start < self.start) and  #       |-----|
          (dataregion.end == self.start)):     # |====|
      return 'left-adjacent'

    elif ((dataregion.end > self.end) and      # |----|
          (dataregion.start == self.end)):     #       |=====|
      return 'right-adjacent'

    elif ((dataregion.start > self.start) and  # |-----------|
          (dataregion.end < self.end)):        #    |=====|
      return 'inner-overlap'

    elif ((dataregion.start < self.start) and  #    |-----|
          (dataregion.end > self.end)):        # |===========|
      return 'outer-overlap'

    elif ((dataregion.end >= self.start) and   #    |-----|
          (dataregion.end <= self.end) and     # |=====|
          (dataregion.start <= self.start)):   # |==|
      return 'left-overlap'                    # |========|

    elif ((dataregion.start >= self.start) and #    |-----|
          (dataregion.start <= self.end) and   #       |=====|
          (dataregion.end >= self.end)):       #          |==|
      return 'right-overlap'                   #    |========|

    else:
      return None

  def mergeWith(self, dataregion):
    '''
    Attempt to merge the given DataRegion into the current
    instance. Raises RegionError if the given DataRegion does not
    overlap with the self.
    '''

    merge_type = self.canMerge(dataregion)

    # Catch the invalid case where the region doesn't overlap
    # or is not adjacent.
    if merge_type == None:
      raise RegionOverlapError, (('The DataRegionDocument given does not '
                                  'overlap this instance '
                                  '(%s, %s)') % (self, dataregion))

    # |===========|
    #    |-----|
    if merge_type in ('outer-overlap', 'perfect-overlap'):
      return dataregion

    # |-----------|
    #    |=====|
    elif merge_type == 'inner-overlap':
      start_offset = dataregion.start - self.start
      end_offset = self.length - (self.end - dataregion.end)

      return DataRegionDocument(start=self.start,
                                end=self.end,
                                data=(self.data[:start_offset] +
                                      dataregion.data +
                                      self.data[end_offset:]))

    # Case where the dataregion is offset to the left and only
    # partially overwrites this one, inclusive of the end points.
    #            |-------|
    #         |======|
    #      |=====|
    elif merge_type == 'left-overlap':
      start_offset = dataregion.end - self.start
      return DataRegionDocument(start=dataregion.start,
                                end=self.end,
                                data=dataregion.data + self.data[start_offset:])

    # Case where the dataregion is offset to the left and only
    # partially overwrites this one, inclusive of the end points.
    #            |-------|
    #                |======|
    #                    |======|
    elif merge_type in 'right-overlap':
      end_offset = self.length - (self.end - dataregion.start)
      return DataRegionDocument(start=self.start,
                                end=dataregion.end,
                                data=self.data[:end_offset] + dataregion.data)

    # Case where the dataregion is adjacent to the left.
    #            |-------|
    #     |=====|
    elif merge_type == 'left-adjacent':
      return DataRegionDocument(start=dataregion.start,
                                end=self.end,
                                data=dataregion.data + self.data)

    # Case where the dataregion is adjacent to the right.
    #            |-------|
    #                     |======|
    elif merge_type == 'right-adjacent':
      return DataRegionDocument(start=self.start,
                                end=dataregion.end,
                                data=self.data + dataregion.data)

  @ViewField.define('dataregionchange')
  def by_filechangeid(doc):
    if doc['doctype'] == "DataRegionDocument":
      yield doc['filechangeid'], doc
