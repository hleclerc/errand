"""A cargo project: `cargo test`, its tests read from cargo's own output.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

from ..streams import ended
from .base import FRAMEWORK, NONE, Outcome, RunContext, Runner


class Cargo( Runner ):
    """A Rust crate: one run per test target.

    `cargo metadata` knows the targets without compiling any of them. A
    target's file is its source root ( `src/lib.rs`, `tests/foo.rs` ), and the
    crate is the nearest `Cargo.toml` above it. The `::name` part becomes the
    filter `cargo test` takes after `--`.

    The tests are compiled during the preparation ( `cargo test --no-run` ), in
    the place they will run, into this environment's own target directory
    ( `{build_dir}/target` ): two environments never share a binary, and the run
    only runs.
    """

    name = "cargo"
    level = FRAMEWORK
    whole_files = True
    takes_selector = True
    jobs = True                          # `-j N` on one target: `--test-threads N`

    def __init__( self, manifest = None, args = ( ), release = False, target_dir = "{build_dir}/target",
                  zones = None ):
        self.manifest   = None if manifest is None else Path( manifest )
        self.args       = list( args )
        self.release    = release
        # Where cargo builds: per environment by default; None leaves it to cargo ( `target/` ).
        self.target_dir = target_dir
        self._targets   = { }
        self.zones      = dict( zones or { } )

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
        cargo = self.tool( "cargo" )
        if shutil.which( cargo[ 0 ] ) is None or not manifest.is_file():
            return found
        got = subprocess.run( [ *cargo, "metadata", "--no-deps", "--format-version", "1",
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

    def _env( self, ctx: RunContext ):
        """`CARGO_TARGET_DIR` for this environment, in both phases: what was built is what runs."""
        if self.target_dir is None:
            return ctx
        where = Path( self.target_dir.replace( "{build_dir}", str( ctx.build_dir or "build" ) ) )
        ctx.env = { **ctx.env, "CARGO_TARGET_DIR": str( ctx.root / where if not where.is_absolute() else where ) }
        return ctx

    def build_lines( self, entries, ctx: RunContext ) -> list:
        return [ f"{' '.join( self.tool( 'cargo', ctx ) )} test --no-run --manifest-path {m}" + ( " --release" if self.release else "" )
                 for m in self._manifests( entries ) ]

    @staticmethod
    def _manifests( entries ):
        return list( dict.fromkeys( json.loads( e.key )[ "manifest" ] for e in entries ) )

    def prepare( self, entries, ctx: RunContext ):
        """Compiles every test target of the crates asked for, once, before anything runs."""
        cargo = self.tool( "cargo", ctx )
        if shutil.which( cargo[ 0 ] ) is None:
            return f"{cargo[ 0 ]} is not on this place's PATH ( or name it: Env( tools = {{ \"cargo\": ... }} ) )"
        ctx = self._env( ctx )
        for m in self._manifests( entries ):
            got = self.shell( [ *cargo, "test", "--no-run", "--manifest-path", m,
                                *( [ "--release" ] if self.release else [ ] ), *self.args ], ctx )
            if got.returncode:
                return f"the build failed ( cargo test --no-run, {m} ):\n{( got.stdout + got.stderr )[ -3000 : ]}"
        return None

    def run( self, entry, ctx: RunContext ) -> Outcome:
        ctx = self._env( ctx )
        target = json.loads( entry.key )
        which = { "lib": [ "--lib" ], "bin": [ "--bin", target[ "name" ] ] }.get(
            target[ "kind" ], [ "--test", target[ "name" ] ] )
        argv = [ *self.tool( "cargo", ctx ), "test", "--manifest-path", target[ "manifest" ], *which,
                 *( [ "--release" ] if self.release else [ ] ), *self.args ]
        # After `--`: the test binary's own arguments.
        tail = [ *( [ ctx.selector ] if ctx.selector else [ ] ),
                 *( [ "--test-threads", str( ctx.jobs ) ] if ctx.jobs > 1 else [ ] ), *ctx.args ]
        if tail:
            argv += [ "--", *tail ]
        got = self.shell( argv, ctx, live_stderr = True )
        text = got.stdout + got.stderr
        shown = self.shown_output( got )

        ( ctx.out_dir / "cargo.txt" ).write_text( text )
        counts = _from_cargo( text )
        if counts is None:
            return Outcome( status = "PASS" if got.returncode == 0 else "FAIL",
                            error = None if got.returncode == 0 else ended( got.returncode ),
                            output = shown, exit = self.exit_of( got ) )
        status = "FAIL" if counts[ "failed" ] else (
            "SKIP" if counts[ "passed" ] == 0 and counts[ "ignored" ] else "PASS" )
        return Outcome( status = status, results = counts, output = shown,
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
