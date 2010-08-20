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

import os, time
import sys
import tsumufs
import threading
import traceback

import gobject
import dbus
import dbus.service

# required
import dbus.glib

gobject.threads_init()
dbus.glib.init_threads()


class DbusNotifier(tsumufs.Debuggable, dbus.service.Object):
  '''
  D-Bus notifier remote object
  '''

  def __init__(self, object_path='/org/tsumufs/NotificationService/notifier'):
    dbus.service.Object.__init__(self, dbus.SystemBus(), object_path)

  @dbus.service.signal(dbus_interface='org.tsumufs.NotificationService')
  def _notifyConnectionStatus(self, value):
    pass

  @dbus.service.signal(dbus_interface='org.tsumufs.NotificationService')
  def _notifySynchronisationStatus(self, value):
    pass

  @dbus.service.signal(dbus_interface='org.tsumufs.NotificationService')
  def _notifyUnmountedStatus(self, value):
    pass

  @dbus.service.signal(dbus_interface='org.tsumufs.NotificationService')
  def _notifySynchronisationItem(self, value):
    pass

  def notify(self, type, value):
    
    signals = { 'connection'      : self._notifyConnectionStatus,
                'synchronisation' : self._notifySynchronisationStatus,
                'unmounted'       : self._notifyUnmountedStatus,
                'synchitem'       : self._notifySynchronisationItem,}

    assert signals.has_key(type)

    self._debug('Notify "%s" -> %s.' % (type, str(value)))
    signals[type].__call__(value)

    return True


class Notification(tsumufs.Debuggable):
  '''
  Wrapper object to invoke remote notifier object
  '''

  def __init__(self):
    self.object = DbusNotifier()

  def notify(self, type, value):
    """
    Invoke notify method of the notifer object
    """

    self.object.notify(type, value)

