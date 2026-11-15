"""Windows Job Objects: what an agent owns there ( ADR 0008 ).

Each process an agent starts is created suspended, put into a job of its own, then resumed: nothing
it starts can be outside the job, since nothing ran before it was in. The job is
`KILL_ON_JOB_CLOSE` and only the agent holds its handle, so

  - a stop ends the whole tree ( `terminate` ), the leader gone or not -- `taskkill /T` follows
    parent pids, and loses the children of a parent that has exited;
  - the agent's own end, however it comes ( a kill, a crash, a logout ), closes the handle, and
    the kernel ends everything it started.

The handle is kept for the agent's life, not the leader's: what a leader leaves running on purpose
( `start /b` ) stays owned, and goes with the agent.
"""
from __future__ import annotations

import ctypes
import sys

JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE = 0x2000
JobObjectExtendedLimitInformation  = 9
CREATE_SUSPENDED                   = 0x4

_held = [ ]          # every job this process made: closed only when it exits


if sys.platform == "win32":
    from ctypes import wintypes as W

    class _IO_COUNTERS( ctypes.Structure ):
        _fields_ = [ ( n, ctypes.c_ulonglong ) for n in ( "ReadOperationCount", "WriteOperationCount",
                                                           "OtherOperationCount", "ReadTransferCount",
                                                           "WriteTransferCount", "OtherTransferCount" ) ]

    class _BASIC_LIMIT( ctypes.Structure ):
        _fields_ = [ ( "PerProcessUserTimeLimit", ctypes.c_longlong ), ( "PerJobUserTimeLimit", ctypes.c_longlong ),
                     ( "LimitFlags", W.DWORD ), ( "MinimumWorkingSetSize", ctypes.c_size_t ),
                     ( "MaximumWorkingSetSize", ctypes.c_size_t ), ( "ActiveProcessLimit", W.DWORD ),
                     ( "Affinity", ctypes.c_size_t ), ( "PriorityClass", W.DWORD ), ( "SchedulingClass", W.DWORD ) ]

    class _EXTENDED_LIMIT( ctypes.Structure ):
        _fields_ = [ ( "BasicLimitInformation", _BASIC_LIMIT ), ( "IoInfo", _IO_COUNTERS ),
                     ( "ProcessMemoryLimit", ctypes.c_size_t ), ( "JobMemoryLimit", ctypes.c_size_t ),
                     ( "PeakProcessMemoryUsed", ctypes.c_size_t ), ( "PeakJobMemoryUsed", ctypes.c_size_t ) ]

    def _libs():
        k = ctypes.WinDLL( "kernel32", use_last_error = True )
        k.CreateJobObjectW.argtypes = [ ctypes.c_void_p, W.LPCWSTR ]
        k.CreateJobObjectW.restype = W.HANDLE
        k.SetInformationJobObject.argtypes = [ W.HANDLE, ctypes.c_int, ctypes.c_void_p, W.DWORD ]
        k.AssignProcessToJobObject.argtypes = [ W.HANDLE, W.HANDLE ]
        k.TerminateJobObject.argtypes = [ W.HANDLE, W.UINT ]
        k.CloseHandle.argtypes = [ W.HANDLE ]
        k.ResumeThread.argtypes = [ W.HANDLE ]
        k.ResumeThread.restype = W.DWORD
        nt = ctypes.WinDLL( "ntdll" )
        nt.NtResumeProcess.argtypes = [ W.HANDLE ]
        nt.NtResumeProcess.restype = ctypes.c_long
        return k, nt


class Job:
    """A job of one process tree. `None` from `make` where there is none to be had ( not Windows,
    or a Windows that refuses: the old `taskkill /T` then )."""

    def __init__( self, handle ):
        self.handle = handle

    @classmethod
    def make( cls ):
        if sys.platform != "win32":
            return None
        try:
            k, _ = _libs()
            h = k.CreateJobObjectW( None, None )
            if not h:
                return None
            info = _EXTENDED_LIMIT()
            info.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not k.SetInformationJobObject( h, JobObjectExtendedLimitInformation, ctypes.byref( info ),
                                              ctypes.sizeof( info ) ):
                k.CloseHandle( h )
                return None
        except OSError:
            return None
        job = cls( h )
        _held.append( job )
        return job

    def take( self, process_handle, thread_handle = None ) -> bool:
        """A process created suspended: into the job, then resumed -> whether it is in. Resumed
        whatever happens: a process left suspended would be worse than one outside the job."""
        k, nt = _libs()
        inside = bool( k.AssignProcessToJobObject( self.handle, process_handle ) )
        if thread_handle is not None:
            k.ResumeThread( thread_handle )
        else:
            nt.NtResumeProcess( process_handle )
        return inside

    def terminate( self, code: int = 1 ):
        k, _ = _libs()
        k.TerminateJobObject( self.handle, code )
