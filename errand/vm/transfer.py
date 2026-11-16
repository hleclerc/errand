"""MSYS2's rsync and ssh, pinned: what errand started on Windows copies with, through an `Ssh` push by rsync.
A Windows guest or box needs neither: files cross through its agent ( ADR 0006 ).
"""
from __future__ import annotations

import re



# MSYS2's rsync, which runs without the rest of MSYS2 -- the program and the DLLs it loads, nothing else.
MSYS2_REPO     = "https://repo.msys2.org/msys/x86_64"
MSYS2_PACKAGES = [ "rsync-3.5.1-2", "msys2-runtime-3.6.10-7", "libopenssl-3.6.5-1", "libiconv-1.19-1",
                   "libidn2-2.3.8-1", "libintl-0.22.5-1", "libunistring-1.4.2-1", "liblz4-1.10.0-1",
                   "popt-1.19-1", "libxxhash-0.8.4-1", "libzstd-1.5.7-1" ]
RSYNC_FILES    = [ "rsync.exe", "msys-2.0.dll", "msys-crypto-3.dll", "msys-iconv-2.dll", "msys-idn2-0.dll",
                   "msys-intl-8.dll", "msys-unistring-5.dll", "msys-lz4-1.dll", "msys-popt-0.dll",
                   "msys-xxhash-0.dll", "msys-zstd-1.dll" ]
# errand started on Windows: rsync's remote shell must be MSYS2's ssh too, as Windows' own ssh.exe takes
# the pipes MSYS2's rsync gives it for closed ones. Unpacked beside rsync, here only.
SSH_PACKAGES   = [ "openssh-10.6p2-2", "heimdal-libs-7.8.0-9", "libopenssl-4.1.0-1", "libsqlite-3.54.1-1",
                   "libxcrypt-4.5.2-1", "zlib-1.4-1", "gcc-libs-16.2.0-1" ]
SSH_FILES      = [ "ssh.exe", "msys-asn1-8.dll", "msys-com_err-1.dll", "msys-crypt-2.dll", "msys-crypto-4.dll",
                   "msys-gcc_s-seh-1.dll", "msys-gssapi-3.dll", "msys-hcrypto-4.dll", "msys-heimbase-1.dll",
                   "msys-heimntlm-0.dll", "msys-hx509-5.dll", "msys-krb5-26.dll", "msys-roken-18.dll",
                   "msys-sqlite3-0.dll", "msys-wind-0.dll", "msys-z.dll" ]


def msys_path( path: str ) -> str:
    """A Windows path as MSYS2's rsync reads it: E:/x is /e/x."""
    path = str( path ).replace( "\\", "/" )
    if re.match( r"^[A-Za-z]:", path ):
        path = f"/{path[ 0 ].lower()}{path[ 2 : ]}"
    return path.rstrip( "/" )
