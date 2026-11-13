"""What installing needs, fetched by the machine that runs QEMU: the ISO, MSYS2's rsync.
"""
from __future__ import annotations

import re

from .. import layers as L
from .common import _sh, VmError
from .transfer import MSYS2_PACKAGES, MSYS2_REPO, RSYNC_FILES


class Supplies:
    """What installing needs, fetched by the machine that runs QEMU."""

    @property
    def downloads( self ) -> str:
        return f"{self.image.rsplit( '/', 2 )[ 0 ]}/downloads"           # beside windows/

    # -- installing -----------------------------------------------------------

    def obtain_iso( self, iso: str, echo = print ) -> str:
        """-> the ISO as the machine that runs QEMU names it: a path of the
        project over there, or a download beside the images, made by it --
        and removed once the image is installed ( `install` )."""
        if "://" not in iso:
            out = self.host.shell( _sh( 'cd "$( dirname "$1" )" 2>/dev/null && test -f "$( basename "$1" )" '
                                        '&& echo "errand-path=$( pwd )/$( basename "$1" )"', iso ),
                                   capture = True ).stdout or ""
            found = re.search( r"errand-path=(.*)", out )
            if not found:
                raise VmError( f"no ISO at {iso} {self.facts.where}" )
            return found.group( 1 ).strip()
        target = f"{self.downloads}/{L.fingerprint( iso )}.iso"
        if self.host.shell( L.sh( [ "test", "-f", target ] ), quiet = True ).returncode == 0:
            return target
        if "curl" in self.facts.tools:
            fetch = 'curl -fL --retry 3 --progress-bar -o "$2.part" "$1"'
        elif "wget" in self.facts.tools:
            fetch = 'wget -q --show-progress -O "$2.part" "$1"'
        else:
            raise VmError( f"neither curl nor wget {self.facts.where} to download the ISO with" )
        echo( f"  downloading {iso} {self.facts.where}" )
        got = self.host.shell( _sh( f'mkdir -p "$( dirname "$2" )" && {fetch} && mv "$2.part" "$2"', iso, target ) )
        if got.returncode:
            raise VmError( f"could not download the ISO {self.facts.where} -- download it by hand and "
                           f"declare it: errand.Windows( iso = 'path/to/windows.iso' )" )
        return target

    def obtain_rsync( self, into: str, work: str, echo = print ):
        """The rsync of the guest, unpacked from MSYS2's packages into `into`,
        on the install media -- by the machine that runs QEMU, which has a
        zstd to open them with, where Windows may not."""
        if "curl" in self.facts.tools:
            fetch = 'curl -fsSL --retry 3 -o "$p.tar.zst" "$repo/$p-x86_64.pkg.tar.zst"'
        elif "wget" in self.facts.tools:
            fetch = 'wget -q -O "$p.tar.zst" "$repo/$p-x86_64.pkg.tar.zst"'
        else:
            raise VmError( f"neither curl nor wget {self.facts.where} to download rsync for windows with" )
        echo( f"  downloading rsync for windows from msys2 {self.facts.where}" )
        script = ( 'repo="$1" into="$2" work="$3"; shift 3; set -e; mkdir -p "$into" "$work"; cd "$work"; '
                   f'for p in {" ".join( MSYS2_PACKAGES )}; do {fetch}; '
                   'zstd -dqc "$p.tar.zst" | tar -x -f - usr/bin; done; '
                   'for f in "$@"; do cp "usr/bin/$f" "$into/"; done; cd / && rm -rf "$work"' )
        self.there( script, MSYS2_REPO, into, work, *RSYNC_FILES, what = "unpacking rsync for windows" )
