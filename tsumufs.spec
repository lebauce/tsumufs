%define name TsumuFS
%define version 0.14
%define unmangled_version 0.14
%define release 4

%{!?python_sitelib: %define python_sitelib %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib()")}
%{!?python_sitearch: %define python_sitearch %(%{__python} -c "from distutils.sysconfig import get_python_lib; print get_python_lib(1)")}

Summary: A FS-based caching filesystem
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
BuildRequires: python-devel fuse-python pynfs notify-python pygobject2 dbus-python python-distutils-extra
Requires: pyxattr fuse-python pynfs notify-python pygobject2 dbus-python python-distutils-extra


%description
TsumuFS is a disconnected, offline caching filesystem layer on top of file systems in the spirit of fexd and other caching filesystems (like Coda or Intermezzo). While these other filesystems require specific server-side support, TsumuFS 
is designed to be simple and elegant by solving only the caching issue, and not the filesystem protocol itself.


%prep
%setup -n tsumufs-%{unmangled_version}


%build
python setup.py build


%install
python setup.py install --root=$RPM_BUILD_ROOT
install -D -m 755 tsumufs-applet.desktop $RPM_BUILD_ROOT/etc/xdg/autostart/tsumufs-applet.desktop


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
%{_sysconfdir}/xdg/autostart/tsumufs-applet.desktop
%{_datadir}/applications/tsumufs-applet.desktop
%{_datadir}/locale/fr/LC_MESSAGES/tsumufs.mo


%changelog
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

