#!/usr/bin/python
# -*- python -*-
#
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

import os
import os.path
import sys
import errno
import stat
import traceback
import threading 
import thread
import shutil
import time

import pygtk
pygtk.require('2.0')

import gtk
import gobject
import egg.trayicon
import pynotify
import xattr

__version__  = (0, 1)

import fuse
import tsumufs



class TrayIconThread(tsumufs.Debuggable, threading.Thread):
  _trayIcon = None
  _tooltips = None
  _eventBox = None
  _displayImage = None

  _mountPointPath = '.'

  _isConnected = False
  _isConflicted = False

  _iconPathPrefix ="/usr/share/tsumufs/icons" 
  
  _isSynchronized = False  

  def __init__(self):
      
    #Initializing TrayIcon object.   
    pynotify.init('TsumuFS')

    self._trayIcon = egg.trayicon.TrayIcon('TsumuFS')
    self._tooltips = gtk.Tooltips()
    self._eventBox = gtk.EventBox()
    self._eventBox.set_events(gtk.gdk.BUTTON_PRESS_MASK)
    self._displayImage = gtk.Image()
    self._eventBox.add(self._displayImage)
    self._eventBox.connect('button_press_event', self._buttonPress)
    self._trayIcon.connect('delete-event', self._cleanup)
    self._trayIcon.add(self._eventBox)
    self._trayIcon.show_all()
            
    
    self._updateIcon()
    gobject.timeout_add(500, self._timer)
    
   
    self._debug('Setting up thread state.')
    threading.Thread.__init__(self, name='TrayIconThread')

  def _updateIcon(self):
    path = ''

    #choose the trayIcon according to connexion state. 
    #If SyncWork event is set, then _isSynchronized is True
    #SyncWork is set during propogate changes
    if self._isSynchronized:
        path = os.path.join(self._iconPathPrefix, 'synchronized.png')
    elif self._isConnected:
        path = os.path.join(self._iconPathPrefix, 'connected.png')
    else:
        path = os.path.join(self._iconPathPrefix, 'disconnected.png')

    pixbuf = gtk.gdk.pixbuf_new_from_file(path)

    if self._isConflicted:
      path = os.path.join(self._iconPathPrefix, 'conflicted.png')
      pixbuf.blit_from_file(path)

    size = self._trayIcon.get_size()
    pixbuf.scale_simple(size[0], size[1], gtk.gdk.INTERP_BILINEAR)
    self._displayImage.set_from_pixbuf(pixbuf)

  def _cleanup(self):
    gtk.main_quit()

  def _timer(self):
      
    old_isConnected = TrayIconThread._isConnected
    old_isConflicted = self._isConflicted
    old_isSynchronized = self._isSynchronized
      
    if tsumufs.fsAvailable.isSet():
        TrayIconThread._isConnected = True
    else:
        TrayIconThread._isConnected = False
    
    if tsumufs.syncWork.isSet():
        self._isSynchronized = True
    else:
        self._isSynchronized = False
    
    if ((old_isConnected != self._isConnected) or
        (old_isConflicted != self._isConflicted) or
        (old_isSynchronized != self._isSynchronized )):
      self._updateIcon()

      # Display a notification only if disconnected mode has appear
      if not self._isConnected:
        self._notifyDisconnected()
        
    time.sleep(0.1)    
    return True

  def _buttonPress(self, widget, event):
      
    #Creating gtkMenu to get informations about files which are not synchronized
    #We don't care about Event.type
    
    #Display tsumufs mode
    menu = gtk.Menu()
    if tsumufs.syncWork.isSet():
        #(_("...")) is for gettext module in goal to traduct in french or other languages
        item1 = gtk.ImageMenuItem(_("Synchronized.."))
    elif tsumufs.fsAvailable.isSet():
        item1 = gtk.ImageMenuItem(_("Connected.."))
    else:
        item1 = gtk.ImageMenuItem(_("Disconnected.."))
        
    #Ufo_icon is my application logo    
    path = os.path.join(self._iconPathPrefix, 'ufo_icon.png')
    pImage = gtk.image_new_from_file(path)
    item1.set_image(pImage)    
    menu.append(item1)
    
    #Create separator in gtkMenu
    barre = gtk.SeparatorMenuItem()
    menu.append(barre)
    
    #We're looking for if an item is sending to distant file system server
    #In that case, we display its name
    if tsumufs.syncWork.isSet():
        try:
            syncitem = tsumufs.syncLog._syncQueue[0]
            name = syncitem.getFilename()
            item3 = gtk.ImageMenuItem(str(name))
            path = os.path.join(self._iconPathPrefix, 'syncro_file.png')
            pImage = gtk.image_new_from_file(path)
            item3.set_image(pImage)   
            menu.append(item3) 
        except IndexError, KeyError:
            pass
        
    #Edit a submenu to show all items which are in the syncQueue
    item2 = gtk.ImageMenuItem(_("Files not synchronized"))
    path = os.path.join(self._iconPathPrefix, 'synchronized.png')
    pImage = gtk.image_new_from_file(path)
    item2.set_image(pImage)   
    menu.append(item2)
    
    #Show an icon depending to type of changing (add, delete, modify, etc)
    submenu = gtk.Menu()
    if len(tsumufs.syncLog._syncQueue) > 0:
        for i in tsumufs.syncLog._syncQueue:
            file = i.getFilename()
            change = i.getType()
            subitem = gtk.ImageMenuItem(str(file))
            if str(change) == "new":
                path = os.path.join(self._iconPathPrefix, 'new_file.png')
            elif str(change) == "link":
                path = os.path.join(self._iconPathPrefix, 'new_file.png')
            elif str(change) == "unlink":
                path = os.path.join(self._iconPathPrefix, 'delete_file.png')
            elif str(change) == "change":
                path = os.path.join(self._iconPathPrefix, 'update_file.png')
            elif str(change) == "rename":
                path = os.path.join(self._iconPathPrefix, 'rename_file.png')
                
            pImage = gtk.image_new_from_file(path)
            subitem.set_image(pImage)
            submenu.append(subitem)
            subitem.show()
    else:
        file = (_("No files queued"))
        subitem = gtk.MenuItem(str(file))
        submenu.append(subitem)
        subitem.show()
    #Appending submenu to mainMenu        
    item2.set_submenu(submenu)
    item1.show()
    barre.show()
    if tsumufs.syncWork.isSet():
        item3.show()
    item2.show()
    menu.popup(None, None, None, event.button, event.time)
    menu.attach_to_widget(self._trayIcon,None)

  
  def _notifyDisconnected(self):
    summary = 'Disconnected from server'
    body = (_('You have been disconnected, files are only stored on local'))
    uri = os.path.join(self._iconPathPrefix, 'ufo.png')

    notification = pynotify.Notification(summary, body, uri)
    notification.attach_to_widget(self._trayIcon)
    notification.show()

  def _main(self):
    #self.validateMountPoint()
    #self.daemonize()
    gtk.main() 
    
  def validateMountPoint(self):
    #I don't use ValidateMountPoint() function in my application, 
    #I haven't realy undertstand its interest in this script
    try:
      xattr.get(self._mountPointPath, 'tsumufs.version')
    except   EnvironmentError:
      print >>sys.stderr, ('%s is not a TsumuFS mount point, or is not the root '
                         'of the TsumuFS mount point.' % icon._mountPointPath)
      sys.exit(1)


  def daemonize(self):
    if os.fork() > 0:
      sys.exit(0)

    sys.stderr.close()
    sys.stdout.close()
    sys.stdin.close()

  def run(self):
    
    self._main()  
          
        
    
    
    


