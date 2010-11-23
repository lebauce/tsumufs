%define name TsumuFS
%define version 0.14
%define unmangled_version 0.14
%define release 7

%{!?python_sitelib: %define python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}
%{!?python_sitearch: %define python_sitearch %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib(1)")}

Summary: TsumuFS is a disconnected, offline caching filesystem.
Name: %{name}
Version: %{version}
Release: %{release}%{dist}
Source0: %{name}-%{unmangled_version}.tar.gz
License: GPL v2
Group: Development/Libraries
BuildRoot: %{_tmppath}/%{name}-%{version}-%{release}-buildroot
Prefix: %{_prefix}
BuildArch: noarch
Url: http://tsumufs.googlecode.com/
BuildRequires: python intltool python-devel fuse-python pynfs notify-python pygobject2 dbus-python python-distutils-extra
Requires: python pyxattr fuse-python pynfs notify-python pygobject2 dbus-python python-distutils-extra python-magic couchdb python-ufo


%description
TsumuFS is a disconnected, offline caching filesystem layer on top of file systems in the spirit of fexd and other caching filesystems (like Coda or Intermezzo). While these other filesystems require specific server-side support, TsumuFS is designed to be simple and elegant by solving only the caching issue, and not the filesystem protocol itself.


%prep
%setup -n tsumufs-%{unmangled_version}


%build
python setup.py build


%install
python setup.py install --root=$RPM_BUILD_ROOT
#install -D -m 755 tsumufs-applet.desktop $RPM_BUILD_ROOT/etc/xdg/autostart/tsumufs-applet.desktop


%post


%clean
rm -rf $RPM_BUILD_ROOT


%files
%defattr(-,root,root)
%{_bindir}/force-disconnect
%{_bindir}/force-reconnect
%{_bindir}/gen-bug-report
%{_bindir}/in-cache
%{_bindir}/is-connected
%{_bindir}/is-dirty
%{_bindir}/tsumufs
%{_bindir}/tsumufs-applet
%{_bindir}/tsumufs-unmount-all
%{python_sitelib}/TsumuFS-0.14-py2.6.egg-info
%{python_sitelib}/tsumufs/
%{_mandir}/man1/force-disconnect.1.gz
%{_mandir}/man1/force-reconnect.1.gz
%{_mandir}/man1/gen-bug-report.1.gz
%{_mandir}/man1/in-cache.1.gz
%{_mandir}/man1/is-connected.1.gz
%{_mandir}/man1/is-dirty.1.gz
%{_mandir}/man1/mount.tsumufs.1.gz
%{_mandir}/man1/tsumufs.1.gz
%{_datadir}/tsumufs/icons/
#%{_sysconfdir}/xdg/autostart/tsumufs-applet.desktop
#%{_datadir}/applications/tsumufs-applet.desktop
%{_datadir}/locale/fr/LC_MESSAGES/tsumufs.mo


%changelog
* Tue Nov 23 2010 Kevin Pouget <pouget@agorabox.org> - 0.14-7
- Improved fuusethread cache/views manager dispatching
- Improved views statFile behavior
- Implemented views removeCachedFile for 'unlink/rmdir' system calls
- Removed non sens project title
- Reintegrate tray icon based on database changes
- Implemented tray icon action 'pause synchronization'

* Tue Nov 9 2010 Kevin Pouget <pouget@agorabox.org> - 0.14-6
Completetly changed the cache manager to a filesystem overlay based
on the CouchedFilesystem api from python-ufo library, a middleware 
based on CouchDB that handles all system calls on a mount point and
manage himself the metadatas fo the filesystem in a CouchDB database.
 
- Implemented the FilesystemOverlay that handles all reads and
  updates on the metadatas of the local/remote filesystem.
- Use the local or remote physical filesytem as the 'use-fs' opcode.
- Keep in cache all metadatas document from the CouchDB databse to
  minimize the overhead raised by the http request to database server.
- Use python-ufo (CouchDB) to store the revision of the files in the
  cache.
- Removed the caching of the filesytem stats.
- Forward all system calls to the filesystem overlay.
- For each system calls, return to the fusethread the flag to add the
  change to the sync log.
- Pause the syncthread when a file is opened in write mode to significantly
  increase performance of the fusethread.
- Use python-ufo (CouchDB) views for tsumufs views.
- Use python-ufo (CouchDB) database helper to store the persitent
  sync log.
- Use python-ufo (CouchDB) change feature to implement passive pool on
  the sync log by the sync thread.
- Renamed fsBackend, nfsBackend, sambaBackend and sshfsBackend to
  fuse naming style fsmount, nfsmount, sambamount and sshfsmount.
- Renamed view extensionssort into sortedbytype?
- Added view staredbytag.

* Wed Aug 25 2010 Kevin Pouget <pouget@agorabox.org> - 0.14-5
Fixed check access to directories by implemented 'openddir' fuse system call
Added primitive support for sqlite-based cache representation
Implemented filesystem views architecture based on sql queries
Implemented 'sorted by type' view
Implemented 'buddy shares' view
Removed install of the applet as autostart application

* Wed Jan 20 2010 Sylvain Baubeau <sylvain.baubeau@agorabox.org> - 0.14-4
Added internationalization support.

* Tue Dec 10 2009 Kevin Pouget <pouget@agorabox.org> - 0.14-3
Fix permissions
Translate test suite from Makefile to python
Added temporary special trick to keep tsumufs alive
when an unexpeted file appears is local cache dir.

* Mon Oct 5 2009 Kevin Pouget <pouget@agorabox.org> - 0.14-2
Added dbus notifications

* Fri Sep 25 2009 Kevin Pouget <pouget@agorabox.org> - 0.14-1
Added tray icon

* Fri Jun 12 2009 Bastien Bouzerau <bastien.bouzerau@agorabox.org>
Initial release

