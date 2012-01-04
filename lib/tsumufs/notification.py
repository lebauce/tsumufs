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
import sys
import traceback

import tsumufs

from ufo.database import DocumentHelper, BooleanField, TextField, DocumentException
from ufo.notify import NotificationDocument
from threading import _Event


class BinaryStateNotifiation(NotificationDocument):
    state = BooleanField()

    def __init__(self, state=True, **kw):
        super(BinaryStateNotifiation, self).__init__(**kw)

        self.state = state

    def __getattr__(self, attr):
        if attr in ('title', 'body', 'summary'):
            return getattr(self, '_' + attr)[self.state]

        return self.__getattribute__(attr)


class EventNotifier(_Event):

    initiator = 'tsumufs'

    def __init__(self, type, state=False):
        _Event.__init__(self)

        self.type = type

    def notify(self, state):
        self.notifier = DocumentHelper(self.type, tsumufs.user.login)

        try:
            notification = self.notifier.by_subtype_and_initiator(key=[self.type.subtype.default, self.initiator],
                                                                  pk=True)
            notification.state = state
            self.notifier.update(notification)

        except DocumentException, e:
            self.notifier.create(initiator=self.initiator,
                                 target=tsumufs.user.login,
                                 state=state)

    def clear(self):
        _Event.clear(self)
        self.notify(False)

    def set(self):
        _Event.set(self)
        self.notify(True)


class ConnectionNotification(BinaryStateNotifiation):
    subtype = TextField(default="Connection")

    _title   = { False : _("Disconnected from server"),
                 True  : _("Connected to server") }
    _body    = { False : _('You have been disconnected from server.'),
                 True  : _('You are connected to server.') }
    _summary = { False : _("Disconnected from server"),
                 True  : _("Connected to server") }


class UnmountedNotification(BinaryStateNotifiation):
    subtype = TextField(default="Unmounted")


class SyncPauseNotification(BinaryStateNotifiation):
    subtype = TextField(default="SyncPause")


class SyncWorkNotification(BinaryStateNotifiation):
    subtype = TextField(default="SyncWork")
