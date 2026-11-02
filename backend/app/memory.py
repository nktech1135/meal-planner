"""Keep the process small on low-memory machines (glibc only; a no-op elsewhere).

Every thread that allocates can get its own glibc malloc arena, and freed memory often stays in
them: after a few dataset imports the process held on to 100+ MB it no longer used.
"""

import ctypes
import ctypes.util
import gc
import logging
import os
import tempfile

log = logging.getLogger(__name__)

M_ARENA_MAX = -8  # from glibc's malloc.h

try:
    _libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
    _mallopt, _malloc_trim = _libc.mallopt, _libc.malloc_trim
except (OSError, AttributeError):  # not glibc (e.g. musl, macOS)
    _mallopt = _malloc_trim = None


def limit_arenas(count: int = 2) -> None:
    """Cap the malloc arenas threads share, like MALLOC_ARENA_MAX=2."""
    if _mallopt is not None and not _mallopt(M_ARENA_MAX, count):
        log.warning("mallopt(M_ARENA_MAX) failed")


def release_free_memory() -> None:
    """Return freed heap memory to the operating system, e.g. after a large import."""
    gc.collect()
    if _malloc_trim is not None:
        _malloc_trim(0)


def disk_temp_dir(candidate: str = "/var/tmp") -> None:
    """Put temporary files (dataset downloads, uploaded activity archives) on disk.

    /tmp is often tmpfs, i.e. memory (Debian 13 does that by default), and a 200 MB download there
    would use 200 MB of RAM. /var/tmp is disk-backed, and the systemd unit's PrivateTmp gives the
    service a private, writable one. Respects an explicit TMPDIR.
    """
    if os.environ.get("TMPDIR"):
        return
    if os.path.isdir(candidate) and os.access(candidate, os.W_OK | os.X_OK):
        tempfile.tempdir = candidate
