"""Use one Linux lock inode across WSL mount namespaces, with cross-platform flock."""
import errno
import hashlib
import os
from pathlib import Path
import sys

LOCK_SH = 1
LOCK_EX = 2
LOCK_NB = 4
LOCK_UN = 8


def runtime_lock_path(path):
    path=Path(path).resolve()
    if sys.platform=='linux' and len(path.parts)>2 and path.parts[1]=='mnt':
        # DrvFS mounts can expose identical Windows files as different lock inodes.
        key=hashlib.sha256(str(path).encode()).hexdigest()
        return Path.home()/'.barolab/locks'/(path.name+'-'+key[:24]+'.lock')
    return path


if os.name == 'nt':
    import ctypes
    from ctypes import wintypes
    import msvcrt

    _kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

    class _OVERLAPPED(ctypes.Structure):
        _fields_ = [
            ('Internal', ctypes.c_void_p),
            ('InternalHigh', ctypes.c_void_p),
            ('Offset', wintypes.DWORD),
            ('OffsetHigh', wintypes.DWORD),
            ('hEvent', wintypes.HANDLE),
        ]

    _kernel32.LockFileEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_OVERLAPPED)
    ]
    _kernel32.LockFileEx.restype = wintypes.BOOL
    _kernel32.UnlockFileEx.argtypes = [
        wintypes.HANDLE, wintypes.DWORD,
        wintypes.DWORD, wintypes.DWORD, ctypes.POINTER(_OVERLAPPED)
    ]
    _kernel32.UnlockFileEx.restype = wintypes.BOOL

    def flock(fd_or_file, operation):
        fd = fd_or_file.fileno() if hasattr(fd_or_file, 'fileno') else int(fd_or_file)
        handle = wintypes.HANDLE(msvcrt.get_osfhandle(fd))
        overlapped = _OVERLAPPED()
        if operation & LOCK_UN:
            _kernel32.UnlockFileEx(handle, 0, 1, 0, ctypes.byref(overlapped))
            return
        flags = 0
        if operation & LOCK_EX:
            flags |= 0x00000002  # LOCKFILE_EXCLUSIVE_LOCK
        if operation & LOCK_NB:
            flags |= 0x00000001  # LOCKFILE_FAIL_IMMEDIATELY
        if not _kernel32.LockFileEx(handle, flags, 0, 1, 0, ctypes.byref(overlapped)):
            err = ctypes.get_last_error()
            if operation & LOCK_NB:
                raise BlockingIOError(errno.EAGAIN, 'Resource temporarily unavailable', err)
            raise OSError(err, 'LockFileEx failed')

    class _FILETIME(ctypes.Structure):
        _fields_ = [('dwLowDateTime', wintypes.DWORD), ('dwHighDateTime', wintypes.DWORD)]

    _kernel32.GetProcessTimes.argtypes = [
        wintypes.HANDLE, ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME),
        ctypes.POINTER(_FILETIME), ctypes.POINTER(_FILETIME)
    ]
    _kernel32.GetProcessTimes.restype = wintypes.BOOL

    def process_start_ticks(pid):
        try:
            handle = _kernel32.OpenProcess(0x1000, False, int(pid))
            if not handle:
                return None
            try:
                code = wintypes.DWORD()
                if not _kernel32.GetExitCodeProcess(handle, ctypes.byref(code)) or code.value != 259:
                    return None
                ct, et, kt, ut = _FILETIME(), _FILETIME(), _FILETIME(), _FILETIME()
                if not _kernel32.GetProcessTimes(handle, ctypes.byref(ct), ctypes.byref(et), ctypes.byref(kt), ctypes.byref(ut)):
                    return None
                return str((int(ct.dwHighDateTime) << 32) | int(ct.dwLowDateTime))
            finally:
                _kernel32.CloseHandle(handle)
        except (OSError, ValueError, TypeError):
            return None

    sys.modules.setdefault('fcntl', sys.modules[__name__])
else:
    import fcntl as _fcntl
    flock = _fcntl.flock

    def process_start_ticks(pid):
        try:
            stat = Path('/proc', str(pid), 'stat').read_text().split(') ', 1)[1].split()
            return stat[19] if stat[0] != 'Z' else None
        except (OSError, IndexError):
            return None
