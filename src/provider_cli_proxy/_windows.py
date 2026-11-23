import ctypes
import subprocess
from ctypes import wintypes

_EXTENDED_LIMIT_INFORMATION = 9
_KILL_ON_JOB_CLOSE = 0x2000
_PROCESS_TERMINATE = 0x0001
_PROCESS_SET_QUOTA = 0x0100

# Consume only the start byte. The provider inherits the remaining stdin.
_BOOTSTRAP = """
import msvcrt
import os
import subprocess
import sys

msvcrt.setmode(sys.stdin.fileno(), os.O_BINARY)
if os.read(sys.stdin.fileno(), 1) != b'\\x01':
    sys.exit(1)
try:
    result = subprocess.run(
        sys.argv[1:], executable=sys.argv[1], stdin=sys.stdin, stdout=sys.stdout,
        stderr=sys.stderr, creationflags=subprocess.CREATE_NO_WINDOW,
    )
except OSError:
    sys.exit(125)
sys.exit(result.returncode)
"""


class _BasicLimitInformation(ctypes.Structure):
    _fields_ = [
        ("per_process_user_time_limit", ctypes.c_longlong),
        ("per_job_user_time_limit", ctypes.c_longlong),
        ("limit_flags", wintypes.DWORD),
        ("minimum_working_set_size", ctypes.c_size_t),
        ("maximum_working_set_size", ctypes.c_size_t),
        ("active_process_limit", wintypes.DWORD),
        ("affinity", ctypes.c_size_t),
        ("priority_class", wintypes.DWORD),
        ("scheduling_class", wintypes.DWORD),
    ]


class _ExtendedLimitInformation(ctypes.Structure):
    _fields_ = [
        ("basic_limits", _BasicLimitInformation),
        ("io_counters", ctypes.c_ulonglong * 6),
        ("process_memory_limit", ctypes.c_size_t),
        ("job_memory_limit", ctypes.c_size_t),
        ("peak_process_memory_used", ctypes.c_size_t),
        ("peak_job_memory_used", ctypes.c_size_t),
    ]


_kernel = ctypes.WinDLL("kernel32", use_last_error=True)
_create_job = _kernel.CreateJobObjectW
_create_job.argtypes = (ctypes.c_void_p, wintypes.LPCWSTR)
_create_job.restype = wintypes.HANDLE
_set_job_information = _kernel.SetInformationJobObject
_set_job_information.argtypes = (
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
)
_set_job_information.restype = wintypes.BOOL
_open_process = _kernel.OpenProcess
_open_process.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
_open_process.restype = wintypes.HANDLE
_assign_process = _kernel.AssignProcessToJobObject
_assign_process.argtypes = (wintypes.HANDLE, wintypes.HANDLE)
_assign_process.restype = wintypes.BOOL
_close_handle = _kernel.CloseHandle
_close_handle.argtypes = (wintypes.HANDLE,)
_close_handle.restype = wintypes.BOOL


class WindowsJob:
    """Own a non-inheritable kill-on-close job containing the provider tree."""

    def __init__(self, bootstrap_pid: int):
        self._job = _create_job(None, None)
        if not self._job:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            limits = _ExtendedLimitInformation()
            limits.basic_limits.limit_flags = _KILL_ON_JOB_CLOSE
            if not _set_job_information(
                self._job,
                _EXTENDED_LIMIT_INFORMATION,
                ctypes.byref(limits),
                ctypes.sizeof(limits),
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            process = _open_process(
                _PROCESS_SET_QUOTA | _PROCESS_TERMINATE, False, bootstrap_pid
            )
            if not process:
                raise ctypes.WinError(ctypes.get_last_error())
            try:
                if not _assign_process(self._job, process):
                    raise ctypes.WinError(ctypes.get_last_error())
            finally:
                _close_handle(process)
        except BaseException:
            self.close()
            raise

    def close(self) -> None:
        """Close the job and terminate all processes belonging to it."""
        if self._job:
            _close_handle(self._job)
            self._job = None


def bootstrap_args(interpreter: str, command: list[str]) -> tuple[list[str], int]:
    """Build a console-free isolated Python launcher for the job."""
    return (
        [interpreter, "-I", "-S", "-c", _BOOTSTRAP, *command],
        subprocess.CREATE_NO_WINDOW,
    )
