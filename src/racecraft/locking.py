"""
One owner at a time, held by the operating system.

A lock here is an open handle with an OS lock on it: `flock` on POSIX, a
one-byte `msvcrt.locking` region on Windows. The OS gives it up when the handle
is closed, including when the process holding it is killed, so nothing ever has
to guess from a pid or an age whether a lock is stale, and nothing ever deletes
the file. Pid-file locks got that guess wrong twice: a young lock left by a
closed watcher held up Baku FP2, and two launches at the same instant could
both delete-and-recreate their way to "won".

The file also carries a little text (who holds it, which port) written through
the owning handle. On Windows the lock covers one sentinel byte far past that
text, so other processes can still read it while the lock is held.
"""

from __future__ import annotations

import os
import threading
from pathlib import Path

if os.name == "nt":
    import msvcrt
else:
    import fcntl

# Past any text a lock file will hold. Windows lets a region beyond the end of
# the file be locked, and the file stays small.
SENTINEL_OFFSET = 1 << 30


class FileLock:
    """An owned lock. `release()` gives it up and is safe to call again."""

    def __init__(self, path: Path, fd: int):
        self.path = path
        self._fd: int | None = fd
        self._guard = threading.Lock()

    @property
    def held(self) -> bool:
        return self._fd is not None

    def write(self, text: str) -> None:
        """Replace the file's text, through the owning handle."""
        with self._guard:
            if self._fd is None:
                raise RuntimeError(f"{self.path}: lock already released")
            data = text.encode("utf-8")
            os.lseek(self._fd, 0, os.SEEK_SET)
            os.write(self._fd, data)
            os.ftruncate(self._fd, len(data))

    def release(self) -> None:
        with self._guard:
            fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            os.ftruncate(fd, 0)                # the text described this owner
        except OSError:
            pass
        try:
            _unlock(fd)
        except OSError:
            pass                               # closing the handle releases it anyway
        finally:
            os.close(fd)

    def __enter__(self) -> FileLock:
        return self

    def __exit__(self, *exc) -> None:
        self.release()

    def __repr__(self) -> str:
        return f"FileLock({str(self.path)!r}, held={self.held})"


def acquire(path: Path, text: str | None = None) -> FileLock | None:
    """
    Take the lock at `path` without waiting, or return None if another handle
    holds it. `text`, if given, is written once the lock is ours.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0), 0o644)
    try:
        _lock(fd)
    except OSError:
        os.close(fd)
        return None
    except BaseException:
        os.close(fd)
        raise
    lock = FileLock(path, fd)
    if text is not None:
        try:
            lock.write(text)
        except BaseException:
            lock.release()
            raise
    return lock


if os.name == "nt":
    def _lock(fd: int) -> None:
        os.lseek(fd, SENTINEL_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)

    def _unlock(fd: int) -> None:
        os.lseek(fd, SENTINEL_OFFSET, os.SEEK_SET)
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    def _lock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
