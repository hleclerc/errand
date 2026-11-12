"""A terminal on Windows: a pseudo-console ( ConPTY, Windows 10 1809 and later ), through ctypes.

The process is started attached to a pseudo-console whose input and output are
two pipes held here: what is written to one is what was typed, what comes out of
the other is the screen, escape sequences and all. Ctrl-C is the byte 0x03,
which the console turns into what Windows does with Ctrl-C. Nothing to install:
the calls are kernel32's.

Without ConPTY ( an older Windows ), `start` raises OSError and the caller falls
back to pipes.
"""
from __future__ import annotations

import ctypes
import os
import signal
import subprocess
from ctypes import wintypes as W

EXTENDED_STARTUPINFO_PRESENT = 0x00080000
CREATE_UNICODE_ENVIRONMENT   = 0x00000400
PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
INFINITE = 0xFFFFFFFF
STARTF_USESTDHANDLES = 0x00000100


class COORD( ctypes.Structure ):
    _fields_ = [ ( "X", W.SHORT ), ( "Y", W.SHORT ) ]


class STARTUPINFOW( ctypes.Structure ):
    _fields_ = [ ( "cb", W.DWORD ), ( "lpReserved", W.LPWSTR ), ( "lpDesktop", W.LPWSTR ), ( "lpTitle", W.LPWSTR ),
                 ( "dwX", W.DWORD ), ( "dwY", W.DWORD ), ( "dwXSize", W.DWORD ), ( "dwYSize", W.DWORD ),
                 ( "dwXCountChars", W.DWORD ), ( "dwYCountChars", W.DWORD ), ( "dwFillAttribute", W.DWORD ),
                 ( "dwFlags", W.DWORD ), ( "wShowWindow", W.WORD ), ( "cbReserved2", W.WORD ),
                 ( "lpReserved2", ctypes.c_void_p ), ( "hStdInput", W.HANDLE ), ( "hStdOutput", W.HANDLE ),
                 ( "hStdError", W.HANDLE ) ]


class STARTUPINFOEXW( ctypes.Structure ):
    _fields_ = [ ( "StartupInfo", STARTUPINFOW ), ( "lpAttributeList", ctypes.c_void_p ) ]


class PROCESS_INFORMATION( ctypes.Structure ):
    _fields_ = [ ( "hProcess", W.HANDLE ), ( "hThread", W.HANDLE ), ( "dwProcessId", W.DWORD ),
                 ( "dwThreadId", W.DWORD ) ]


def _kernel32():
    k = ctypes.WinDLL( "kernel32", use_last_error = True )
    if not hasattr( k, "CreatePseudoConsole" ):
        raise OSError( "no pseudo-console on this Windows ( before 10 1809 )" )
    k.CreatePseudoConsole.argtypes = [ COORD, W.HANDLE, W.HANDLE, W.DWORD, ctypes.POINTER( W.HANDLE ) ]
    k.CreatePseudoConsole.restype = ctypes.c_long
    k.ResizePseudoConsole.argtypes = [ W.HANDLE, COORD ]
    k.ClosePseudoConsole.argtypes = [ W.HANDLE ]
    k.CreatePipe.argtypes = [ ctypes.POINTER( W.HANDLE ), ctypes.POINTER( W.HANDLE ), ctypes.c_void_p, W.DWORD ]
    k.InitializeProcThreadAttributeList.argtypes = [ ctypes.c_void_p, W.DWORD, W.DWORD, ctypes.POINTER( ctypes.c_size_t ) ]
    k.UpdateProcThreadAttribute.argtypes = [ ctypes.c_void_p, W.DWORD, ctypes.c_size_t, ctypes.c_void_p,
                                             ctypes.c_size_t, ctypes.c_void_p, ctypes.c_void_p ]
    k.CreateProcessW.argtypes = [ W.LPCWSTR, W.LPWSTR, ctypes.c_void_p, ctypes.c_void_p, W.BOOL, W.DWORD,
                                  ctypes.c_void_p, W.LPCWSTR, ctypes.POINTER( STARTUPINFOEXW ),
                                  ctypes.POINTER( PROCESS_INFORMATION ) ]
    k.WaitForSingleObject.argtypes = [ W.HANDLE, W.DWORD ]
    k.GetExitCodeProcess.argtypes = [ W.HANDLE, ctypes.POINTER( W.DWORD ) ]
    k.CloseHandle.argtypes = [ W.HANDLE ]
    return k


def _check( ok, what ):
    if not ok:
        raise ctypes.WinError( ctypes.get_last_error(), what )


class _Process:
    """What `spawn.Child` asks of a process: its pid, waiting for it, Ctrl-C."""

    def __init__( self, k, info, console, keys ):
        self.k, self.info, self.console, self.keys = k, info, console, keys
        self.pid = info.dwProcessId
        self.returncode = None

    def wait( self ) -> int:
        self.k.WaitForSingleObject( self.info.hProcess, INFINITE )
        code = W.DWORD()
        self.k.GetExitCodeProcess( self.info.hProcess, ctypes.byref( code ) )
        self.returncode = code.value
        # the console goes with its process: what it still holds of the screen comes out, then EOF
        self.k.ClosePseudoConsole( self.console )
        for h in ( self.info.hProcess, self.info.hThread ):
            self.k.CloseHandle( h )
        return self.returncode

    def send_signal( self, sig ):
        if sig == signal.CTRL_BREAK_EVENT or sig == signal.SIGINT:
            os.write( self.keys, b"\x03" )             # Ctrl-C, typed
        else:
            raise OSError( "only Ctrl-C reaches a console process gently" )


def start( argv, env, cwd, tty ):
    from .spawn import Child
    k = _kernel32()
    pty_in, keys = W.HANDLE(), W.HANDLE()            # what is typed: we write `keys`, the console reads `pty_in`
    screen, pty_out = W.HANDLE(), W.HANDLE()         # the screen: the console writes `pty_out`, we read `screen`
    _check( k.CreatePipe( ctypes.byref( pty_in ), ctypes.byref( keys ), None, 0 ), "CreatePipe" )
    _check( k.CreatePipe( ctypes.byref( screen ), ctypes.byref( pty_out ), None, 0 ), "CreatePipe" )
    console = W.HANDLE()
    size = COORD( int( tty.get( "cols" ) or 80 ), int( tty.get( "rows" ) or 24 ) )
    hr = k.CreatePseudoConsole( size, pty_in, pty_out, 0, ctypes.byref( console ) )
    if hr != 0:
        raise OSError( f"CreatePseudoConsole: {hr:#x}" )
    # the console holds its ends now
    k.CloseHandle( pty_in )
    k.CloseHandle( pty_out )

    n = ctypes.c_size_t()
    k.InitializeProcThreadAttributeList( None, 1, 0, ctypes.byref( n ) )
    attrs = ctypes.create_string_buffer( n.value )
    _check( k.InitializeProcThreadAttributeList( attrs, 1, 0, ctypes.byref( n ) ), "InitializeProcThreadAttributeList" )
    _check( k.UpdateProcThreadAttribute( attrs, 0, PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE, console,
                                         ctypes.sizeof( W.HANDLE ), None, None ), "UpdateProcThreadAttribute" )
    si = STARTUPINFOEXW()
    si.StartupInfo.cb = ctypes.sizeof( STARTUPINFOEXW )
    # Null standard handles, said explicitly: otherwise a child of a process whose own are redirected
    # ( an agent, its output in a log ) writes there, and the console never sees a byte of it.
    si.StartupInfo.dwFlags = STARTF_USESTDHANDLES
    si.lpAttributeList = ctypes.cast( attrs, ctypes.c_void_p )
    info = PROCESS_INFORMATION()
    block = "".join( f"{k_}={v}\0" for k_, v in ( env or os.environ ).items() ) + "\0"
    line = ctypes.create_unicode_buffer( subprocess.list2cmdline( [ str( a ) for a in argv ] ) )
    _check( k.CreateProcessW( None, line, None, None, False,
                              EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT,
                              ctypes.create_unicode_buffer( block ), cwd, ctypes.byref( si ), ctypes.byref( info ) ),
            "CreateProcessW" )

    import msvcrt
    keys_fd = msvcrt.open_osfhandle( keys.value, 0 )
    screen_fd = msvcrt.open_osfhandle( screen.value, os.O_RDONLY )
    proc = _Process( k, info, console, keys_fd )

    def read( n ):
        try:
            return os.read( screen_fd, n )
        except OSError:
            return b""

    def write( data ):
        view = memoryview( data )
        while view:
            view = view[ os.write( keys_fd, view ) : ]

    def resize( cols, rows ):
        k.ResizePseudoConsole( console, COORD( cols, rows ) )

    return Child( proc, [ ( read, "out" ) ], write, lambda: write( b"\x1a" ), resize = resize )
