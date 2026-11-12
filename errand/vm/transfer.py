"""Copying the project into the guest and results out of it: MSYS2's rsync, pinned.
"""
from __future__ import annotations

import re

from .. import layers as L
from .common import USER


# rsync, which copies the project in: only what changed crosses, where a tar
# carried all of it at every command. MSYS2's, which runs without the rest of
# MSYS2 -- the program and the DLLs it loads, nothing else. Pinned, being what
# an image is made of; downloaded and unpacked by the machine that runs QEMU.
MSYS2_REPO     = "https://repo.msys2.org/msys/x86_64"
MSYS2_PACKAGES = [ "rsync-3.5.1-2", "msys2-runtime-3.6.10-7", "libopenssl-3.6.5-1", "libiconv-1.19-1",
                   "libidn2-2.3.8-1", "libintl-0.22.5-1", "libunistring-1.4.2-1", "liblz4-1.10.0-1",
                   "popt-1.19-1", "libxxhash-0.8.4-1", "libzstd-1.5.7-1" ]
RSYNC_FILES    = [ "rsync.exe", "msys-2.0.dll", "msys-crypto-3.dll", "msys-iconv-2.dll", "msys-idn2-0.dll",
                   "msys-intl-8.dll", "msys-unistring-5.dll", "msys-lz4-1.dll", "msys-popt-0.dll",
                   "msys-xxhash-0.dll", "msys-zstd-1.dll" ]
GUEST_MSYS     = r"C:\errand\msys"
GUEST_RSYNC    = "C:/errand/msys/usr/bin/rsync.exe"
EXCLUDES = [ *L.RSYNC_EXCLUDES, ".errand" ]


def msys_path( path: str ) -> str:
    """A Windows path as the rsync in the guest reads it: E:/x is /e/x."""
    path = str( path ).replace( "\\", "/" )
    if re.match( r"^[A-Za-z]:", path ):
        path = f"/{path[ 0 ].lower()}{path[ 2 : ]}"
    return path.rstrip( "/" )


def rsync_line( reach: list, there: str, source: str = "./" ) -> str:
    """The project, minus what an `Ssh` push leaves out too, into `there` in the
    guest -- run from its root on the machine that runs QEMU. Links followed, as
    NTFS has none worth the name; no permission, owner or group, which the
    guest's ACLs would only garble. Nothing deleted: what a command built beside
    the sources is not on this side, and must stay over there."""
    return L.sh( [ "rsync", "-rtL", "-e", L.sh( reach ), "--rsync-path", GUEST_RSYNC,
                   *[ f"--exclude={e}" for e in EXCLUDES + L.own_paths() ], source, f"{USER}@127.0.0.1:{msys_path( there )}/" ] )


# rsync's 23 ( "some files were not transferred" ) and 24 ( "some vanished" ),
# when every complaint is one of these, are a copy as good as can be: a link
# to nothing has nothing to copy, as for an `Ssh` push.
HARMLESS = re.compile( r"symlink has no referent|file has vanished|^rsync (error|warning): some files" )


def rsync_failed( got ) -> bool:
    if not got.returncode:
        return False
    said = [ l for l in ( got.stderr or "" ).splitlines() if l.strip() ]
    return got.returncode not in ( 23, 24 ) or not all( HARMLESS.search( l.strip() ) for l in said )
