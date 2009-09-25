
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
#import gtk

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


