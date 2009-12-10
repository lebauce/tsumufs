#!/usr/bin/python
# -*- python -*-
#
# Copyright (C) 2007  Google, Inc. All Rights Reserved.
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

'''Export proper environement values from conf, and run the test suite'''

import sys, os
import ConfigParser
import subprocess
import shutil
import time
import glob
import tarfile

def ensure_exists(_path):
  if not os.path.exists(_path):
    os.makedirs(_path)

def make_abs(_path):
  if not os.path.isabs(_path):
    return os.path.join(os.path.expanduser("~"), _path)
  return _path

def spawn(cmd, cwd=None, env=None):
  proc = subprocess.Popen(cmd, env=env, shell=False, cwd=cwd, stdin=None, stdout=subprocess.PIPE)
  print proc.communicate()[0]
  return proc.returncode

if __name__ == '__main__':

  print "\n-- running unit tests"
  for unit_test in glob.glob("unit/*_test.py"):
    print "\n---running unit test '"+ os.path.basename(unit_test) + "'"
    if spawn(['/usr/bin/python', unit_test], env={'PYTHONPATH':"../lib"}):
        print "   unit test '"+ os.path.basename(unit_test) + "' failed..."
    else:
        print "   unit test '"+ os.path.basename(unit_test) + "' succeeded !"

  if "debug" in sys.argv:
     emergency_shell = True
  else:
     emergency_shell = False

  if "user" in sys.argv:
     user = True
  else:
     user = False

  if len(sys.argv) > 1 and sys.argv[1] != "debug" and sys.argv[1] != "user":
    conf_file = sys.argv[1]
  elif os.path.exists("/etc/tsumufs/tsumufs.conf"):
    conf_file = "/etc/tsumufs/tsumufs.conf"
  else:
    raise Exception("Could not read conf file path from argv[0]," + \
                    "or default path /etc/tsumufs/tsumufs.conf do not exist")

  cf      = ConfigParser.ConfigParser( defaults = { "debuglevel" : 0 } )
  conf_fs = cf.read(conf_file)

  if conf_fs:
    print "   using configuration file(s) : " + " ".join(conf_fs)
  else:
    raise Exception("No configuration file found")

  print "\n-- checking configuration"
  for section in cf.sections():
    fstype = cf.get(section, "type")
    fsmountpoint = make_abs(cf.get(section, "fsmountpoint"))
    options = cf.get(section, "options")
    export = cf.get(section, "export")
    ip = cf.get(section, "ip")

    cachebasedir = "/tmp/tsumufs-test-cache-dir"
    overlaydir   = "/tmp/tsumufs-est-overlay-dir"
    mountmethod  = "fstab"
    mountcmd     = "/bin/mount"
    umountcmd    = "/bin/umount"

    ensure_exists(fsmountpoint)
    ensure_exists(cachebasedir)
    ensure_exists(overlaydir)

    if os.system("grep " + fsmountpoint + " /etc/fstab 1>/dev/null"):
      print "   fstab does not contain any rules for " + fsmountpoint

    if fstype in [ "nfs", "nfs3", "nfs4" ]:
        uri = "%s:%s" % (ip, export)
    elif fstype == "samba":
        uri = "//%s%s" % (ip, export)
    elif fstype == "sshfs":
        uri = "%s:%s" % (ip, export)
    else:
        raise Exception("Unsupported filesystem (" + fstype + ")")

    print "-- check tsumufs instance"
    if not os.system("mount | grep -qe '^tsumufs on'"):
      raise Exception("Overlay (" + overlaydir + ") is already mounted")

    print "\n-- running functional tests"

    debug = 0
    tsumufsopts = 'fsmountpoint=' + fsmountpoint
    tsumufsopts += ',cachebasedir=' + cachebasedir
    tsumufsopts += ',fstype=' + fstype
    tsumufsopts += ',fsmountcmd=' + mountcmd
    tsumufsopts += ',fsunmountcmd=' + umountcmd
    tsumufsopts += ',fsmountmethod=' + mountmethod
    overlaycmd = ['../src/tsumufs', '-d', '-l', str(debug), '-O', options, '-o', tsumufsopts, uri, overlaydir]
    print "   tsumyfs mount command: " + " ".join(overlaycmd)

    tar = tarfile.open("filesystem.tar")
    for functional_test in glob.glob("functional/*.c"):

      print "\n---running functional test '"+ os.path.basename(functional_test) + "'"
      print "   compile " + functional_test
      if spawn(['/usr/bin/cc', functional_test, '-o', os.path.splitext(functional_test)[0]]):
        print "   compilation of '"+ os.path.basename(functional_test) + "' failed..."
        continue

      print "   rebuild filesystem"
      if os.path.exists("filesystem"):
        shutil.rmtree("filesystem")
      tar.extractall(".")

      print "   mounting overlay on " + overlaydir
      if os.path.exists(cachebasedir):
        shutil.rmtree(cachebasedir)
      spawn(overlaycmd, env={'PYTHONPATH':"../lib"})

      try:
        env = {'CACHE_DIR' : cachebasedir, 'NFS_DIR' : fsmountpoint, 'TEST_DIR' : overlaydir}
        if user:
          env.update({'USR_DIR' : os.getlogin()})

        if spawn([os.path.splitext(os.path.realpath(functional_test))[0]], cwd=overlaydir, env=env):

          print "   functional test '"+ os.path.basename(functional_test) + "' failed..."
          if emergency_shell:
            print "Starting emergency holographic shell to examine the rubble."
            os.system(" CACHE_DIR=" + cachebasedir +                          \
                      " NFS_DIR=" + fsmountpoint +                            \
                      " TEST_DIR=" + overlaydir +                             \
                      ' PS1=\'\[\e[m\e[1;31m\][TSUMUFS]\[\e[0m\] \h:\w\$$ \' ' + \
                      "sh")
        else:
          print "   functional test '"+ os.path.basename(functional_test) + "' succeeded !"
      except Exception, e:
        print e

      os.system("sudo " + umountcmd + " " + overlaydir + " 1>&2 2>/dev/null")
      time.sleep(1)
      os.system("sudo " + umountcmd + " " + overlaydir + " 1>&2 2>/dev/null")
      time.sleep(1)
      os.system("sudo " + umountcmd + " " + overlaydir + " 1>&2 2>/dev/null")

    tar.close()

