"""A per-user runtime lock; does not install repository workflow enforcement."""

import os


class InstanceLock:
    def __init__(self, path):
        self.path = path
        self.handle = None

    def __enter__(self):
        self.handle = open(self.path, "a+b")
        self.handle.seek(0)
        if os.name == "nt":
            import msvcrt

            self.handle.seek(0, os.SEEK_END)
            if self.handle.tell() == 0:
                self.handle.write(b"0")
                self.handle.flush()
            self.handle.seek(0)
            try:
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                self.handle.close()
                raise RuntimeError(
                    "BidMaster is already running for this data directory."
                ) from None
        else:
            import fcntl

            try:
                fcntl.flock(self.handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                self.handle.close()
                raise RuntimeError(
                    "BidMaster is already running for this data directory."
                ) from None
        return self

    def __exit__(self, *_):
        if self.handle:
            if os.name == "nt":
                import msvcrt

                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            self.handle.close()


class InstallerGuard:
    """Advertise a running Windows app to Inno Setup without closing it forcibly."""

    def __init__(self):
        self.handle = None
        if os.name == "nt":
            import ctypes
            from ctypes import wintypes

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            kernel.CreateMutexW.argtypes = [
                ctypes.c_void_p,
                wintypes.BOOL,
                wintypes.LPCWSTR,
            ]
            kernel.CreateMutexW.restype = wintypes.HANDLE
            self.kernel = kernel
            self.handle = kernel.CreateMutexW(
                None, False, r"Local\BidMasterLocalApplication"
            )
            if not self.handle:
                raise RuntimeError(
                    "The installer safety guard could not be initialized."
                )

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.handle:
            from ctypes import wintypes

            self.kernel.CloseHandle.argtypes = [wintypes.HANDLE]
            self.kernel.CloseHandle(self.handle)
            self.handle = None
