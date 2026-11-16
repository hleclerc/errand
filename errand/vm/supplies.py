"""What installing needs, fetched by the machine that runs QEMU: the ISO.
"""
from __future__ import annotations

import re

from .. import layers as L
from .common import _sh, VmError


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
