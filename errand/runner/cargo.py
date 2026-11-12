"""A cargo project: `cargo test`, its tests read from cargo's own output.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from .base import FRAMEWORK, NONE, Outcome, RunContext, Runner


class Cargo( Runner ):
    """A Rust crate: one entry per test target.

    `cargo metadata` knows the targets without compiling any of them, which is
    what makes collecting cheap. A
    target's file is its source root ( `src/lib.rs`, `tests/foo.rs` ), and the
    crate is the nearest `Cargo.toml` above it. Naming a single test still
    works: the `::name` part becomes the filter `cargo test` takes after `--`.
    """

    name = "cargo"
    level = FRAMEWORK
    whole_files = True
    takes_selector = True

    def __init__( self, manifest = None, args = ( ), release = False ):
        self.manifest = None if manifest is None else Path( manifest )
        self.args     = list( args )
        self.release  = release
        self._targets = { }

    def _manifest_of( self, path: Path ):
        if self.manifest is not None:
            return self._under_root( self.manifest ).resolve()
        top = Path( os.path.realpath( self.root or "/" ) )
        here = Path( os.path.realpath( path ) ).parent
        while True:
            if ( here / "Cargo.toml" ).is_file():
                return here / "Cargo.toml"
            if here == top or here.parent == here:
                return None
            here = here.parent

    def targets( self, manifest: Path ):
        if manifest in self._targets:
            return self._targets[ manifest ]
        self._targets[ manifest ] = found = { }
        if shutil.which( "cargo" ) is None or not manifest.is_file():
            return found
        got = subprocess.run( [ "cargo", "metadata", "--no-deps", "--format-version", "1",
                                "--manifest-path", str( manifest ) ],
                              capture_output = True, text = True, timeout = 300 )
        if got.returncode:
            return found
        for package in json.loads( got.stdout ).get( "packages", [ ] ):
            for target in package.get( "targets", [ ] ):
                if target.get( "test" ):
                    found[ os.path.realpath( target[ "src_path" ] ) ] = {
                        "name": target[ "name" ], "src": target[ "src_path" ],
                        "kind": ( target.get( "kind" ) or [ "lib" ] )[ 0 ],
                        "manifest": str( manifest ) }
        return found

    def suitability( self, path ):
        if path.suffix != ".rs":
            return NONE
        manifest = self._manifest_of( path )
        if manifest is None:
            return NONE
        return FRAMEWORK if os.path.realpath( path ) in self.targets( manifest ) else NONE

    def collect( self, specs ):
        out = [ ]
        for path in self.files_of( specs ):
            manifest = self._manifest_of( path )
            target = self.targets( manifest ).get( os.path.realpath( path ) ) if manifest else None
            if target is not None:
                out.append( self.entry( name = target[ "name" ], file = path,
                                        key = json.dumps( target ),
                                        tags = [ "cargo", target[ "kind" ] ] ) )
        return out

    def run( self, entry, ctx: RunContext ) -> Outcome:
        target = json.loads( entry.key )
        which = { "lib": [ "--lib" ], "bin": [ "--bin", target[ "name" ] ] }.get(
            target[ "kind" ], [ "--test", target[ "name" ] ] )
        argv = [ "cargo", "test", "--manifest-path", target[ "manifest" ], *which,
                 *( [ "--release" ] if self.release else [ ] ), *self.args ]
        if ctx.selector or ctx.args:
            argv += [ "--", *( [ ctx.selector ] if ctx.selector else [ ] ), *ctx.args ]
        got = self.shell( argv, ctx )
        text = got.stdout + got.stderr

        ( ctx.out_dir / "cargo.txt" ).write_text( text )
        counts = _from_cargo( text )
        if counts is None:
            return Outcome( status = "PASS" if got.returncode == 0 else "FAIL",
                            error = None if got.returncode == 0 else f"exit {got.returncode}",
                            output = text )
        status = "FAIL" if counts[ "failed" ] else (
            "SKIP" if counts[ "passed" ] == 0 and counts[ "ignored" ] else "PASS" )
        return Outcome( status = status, results = counts, output = text,
                        error = f"{counts[ 'failed' ]} test(s) failed" if counts[ "failed" ] else None )


def _from_cargo( text: str ):
    """`test result: ok. 3 passed; 0 failed; 1 ignored; …`, summed over targets."""
    found = re.findall(
        r"test result: \w+\. (\d+) passed; (\d+) failed; (\d+) ignored", text )
    if not found:
        return None
    return { "passed" : sum( int( a ) for a, _, _ in found ),
             "failed" : sum( int( b ) for _, b, _ in found ),
             "ignored": sum( int( c ) for _, _, c in found ) }
