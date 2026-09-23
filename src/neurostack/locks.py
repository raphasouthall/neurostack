# SPDX-License-Identifier: Apache-2.0
# Copyright (c) 2024-2026 Raphael Southall
"""One exclusive file lock that works on Linux, macOS, and Windows (issue #221).

POSIX uses `fcntl.flock`; Windows locks the first byte with `msvcrt.locking`.
Both locks belong to the open handle, so the OS drops them when the process
exits and a lock file left behind by a dead process blocks nobody.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager
from pathlib import Path

if sys.platform == "win32":
    import msvcrt

    def _lock(fd: int, blocking: bool) -> bool:
        # LK_LOCK gives up after 10 one-second retries, so a blocking caller
        # keeps asking until the holder lets go.
        while True:
            try:
                msvcrt.locking(fd, msvcrt.LK_LOCK if blocking else msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                if not blocking:
                    return False

    def _unlock(fd: int) -> None:
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _lock(fd: int, blocking: bool) -> bool:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            return False
        return True

    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)


@contextmanager
def file_lock(path: Path, *, blocking: bool = True):
    """Hold an OS lock; stale lock filenames are harmless after process exit.

    Yields True while the lock is held. With `blocking=False` it yields False
    at once when another holder has the lock, and the body runs unlocked.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        # msvcrt locks bytes from the current position and "a+" opens at the
        # end, so every holder must start from byte 0 to contend for one range.
        handle.seek(0)
        if not _lock(handle.fileno(), blocking):
            yield False
            return
        try:
            yield True
        finally:
            _unlock(handle.fileno())
