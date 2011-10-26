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

import traceback
import syslog
import sys

import fuse
from fuse import Fuse

import tsumufs


class ExtendedAttributes(tsumufs.Debuggable):
  '''
  This class represents the ability to store TsumuFS specific extended attribute
  data for various file types and paths.
  '''

  _attributeCallbacks = { 'root': {},
                          'dir' : {},
                          'file': {} }

  @classmethod
  def _validateXAttrType(cls, type_):
    if type_ not in cls._attributeCallbacks.keys():
      if type_ == 'any':
        return

      raise KeyError('Extended attribute type %s is not one of %s' %
                     (type_, cls._attributeCallbacks.keys()))

  @classmethod
  def setCallbackFor(cls, type_, name, set_callback, get_callback, remove_callback):
    cls._validateXAttrType(type_)

    if type_ == 'any':
      types = cls._attributeCallbacks.keys()
    else:
      types = [ type_ ]

    for type_ in types:
      cls._attributeCallbacks[type_][name] = { 'set': set_callback,
                                               'get': get_callback,
                                               'remove': remove_callback }

  @classmethod
  def clearCallbackFor(cls, type_, name):
    cls._validateXAttrType(type_)

    if type_ == 'any':
      type_ = cls._attributeCallbacks.keys()
    else:
      type_ = [ type_ ]

    for type_ in cls._attributeCallbacks.keys():
      if cls._attributeCallbacks.has_key(type_):
        del cls._attributeCallbacks[type_][name]

  @classmethod
  def clearAllCallbacks(cls):
    cls._attributeCallbacks = { 'root': {},
                                'dir': {},
                                'file': {} }

  @classmethod
  def getXAttr(cls, type_, path, name):
    cls._validateXAttrType(type_)

    if cls._attributeCallbacks.has_key(type_):
      callback = cls._attributeCallbacks[type_][name]['get']
      result = callback.__call__(type_, path)
      if type(result) == int:
        raise OSError(result)
      return result

    raise KeyError('No extended attribute set for (%s, %s) pair.' %
                   (type_, name))

  @classmethod
  def getAllXAttrs(cls, type_, path):
    cls._validateXAttrType(type_)
    results = {}

    if cls._attributeCallbacks.has_key(type_):
      for name in cls._attributeCallbacks[type_]:
        callback = cls._attributeCallbacks[type_][name]['get']
        try:
            result = callback.__call__(type_, path)
            if type(result) != int:
                results[name] = result
        except:
            # Do not fail because of one broken/missing attribute
            pass
    return results

  @classmethod
  def getAllNames(cls, type_):
    cls._validateXAttrType(type_)
    results = []

    if cls._attributeCallbacks.has_key(type_):
      results = cls._attributeCallbacks[type_].keys()

    return results

  @classmethod
  def setXAttr(cls, type_, path, name, value):
    cls._validateXAttrType(type_)

    if cls._attributeCallbacks.has_key(type_):
      callback = cls._attributeCallbacks[type_][name]['set']
      result = callback.__call__(type_, path, value)

      if type(result) == int and result:
          raise OSError(result)

      return

    raise KeyError('No extended attribute set for (%s, %s) pair.' %
                   (type_, name))

  @classmethod
  def removeXAttr(cls, type_, path, name):
    cls._validateXAttrType(type_)

    if cls._attributeCallbacks.has_key(type_):
      callback = cls._attributeCallbacks[type_][name]['remove']
      result = callback.__call__(type_, path)

      if type(result) == int and result:
          raise OSError(result)

      return

    raise KeyError('No extended attribute set for (%s, %s) pair.' %
                   (type_, name))


def extendedattribute(type_, name):
  def decorator(func):
    def wrapper(__self, *args, **kwargs):
      return func(__self, *args, **kwargs)

    ExtendedAttributes.setCallbackFor(type_, name, wrapper, wrapper, wrapper)
    return wrapper
  return decorator

