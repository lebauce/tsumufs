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

import threading
import sqlite3

import tsumufs


class DatabaseHelper(tsumufs.Debuggable):
  '''
  Class that provides simple database operations. 
  '''

  _cacheDbConnect = None   # Database connection object

  _cacheDbCursor = None    # SQLite cursor to performSQL commands
  
  _lock = None             # Lock to manage concurrency
  
  def __init__(self, path):
    '''
    Initializer. Try to connect to database identified by path.
    '''

    # TODO:
    # Use a in-memory database and provide function to
    # save / load database to / from a file

    try:
      self._cacheDbConnect = sqlite3.connect(path, check_same_thread=False)
      self._cacheDbCursor  = self._cacheDbConnect.cursor()
    except sqlite3.OperationalError, e:
      self._debug(e)
      raise e
    
    self._lock = threading.RLock()

  def execute(self, query, commit=False, script=False):
    '''
    Execute a query on database, also manage locks.
    '''

    try:
      self._lock.acquire()

      self._debug('Executing request "%s"' % query)

      if script:
        self._cacheDbCursor.executescript(query)
      else:
        self._cacheDbCursor.execute(query)

      if commit:
        self._cacheDbConnect.commit()

      result = self._cacheDbCursor.fetchall()
      self._debug('Returning result "%s"' % result)

    except sqlite3.OperationalError, e:
      raise Exception(e.message)

    finally:
      self._lock.release()
    
    return result
