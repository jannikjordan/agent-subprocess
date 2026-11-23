"""Check process exit by acquiring a lock the fixture process held."""

import os
from typing import BinaryIO


def lock_byte(stream: BinaryIO) -> None:
    """Acquire a nonblocking lock released when the owning process exits."""
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl

        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
