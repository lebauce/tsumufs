#!/usr/bin/python2.4
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

'''TsumuFS is a disconnected, offline caching filesystem.'''

import glob
import sys
import os
import os.path

sys.path.append('lib')
import tsumufs

from distutils.core import setup
from DistUtilsExtra.command import *

scripts = ['src/tsumufs']
scripts.extend(glob.glob(os.path.join('utils', '*')))

cmdclass = { "build" : build_extra.build_extra,
             "build_help" :  build_help.build_help,
             "build_icons" :  build_icons.build_icons }

if sys.platform != 'win32':
    data_files = [ ('/usr/share/man/man1',
                   glob.glob(os.path.join('man', '*'))),
                   ('/usr/share/tsumufs/icons',
                   glob.glob(os.path.join('icons', '*'))) ]
    cmdclass['build_i18n'] = build_i18n.build_i18n

else:
    data_files = []


setup(name='TsumuFS',
      version='.'.join(map(str, tsumufs.__version__)),
      license='GPL v2',
      url='http://tsumufs.googlecode.com/',
      author_email='google-tsumufs@googlegroups.com',
      description='A disconnected, offline caching filesystem',

      package_dir={'': 'lib'},
      packages=['tsumufs'],
      scripts=scripts,
      data_files=data_files,
      cmdclass=cmdclass,
      requires=['fuse', 'xattr', 'pygtk', 'gtk', 'egg'],
      include_package_data=True,
      package_data = { 'tsumufs' : [ 'views/*.py' ] },
)
