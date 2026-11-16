"""The files drive: a FAT32 or exFAT volume kept in one file.

It is presented over USB next to a mounted image (or on its own) so files such
as drivers and installers can travel with the image.
"""

import shutil
import subprocess

from .config import FILES_DRIVE

LABEL = "MOUNTABLE"
FORMATS = {
    "fat32": ["mkfs.vfat", "-F", "32", "-n", LABEL],
    "exfat": ["mkfs.exfat", "-L", LABEL],
}


class DriveError(Exception):
    pass


def info():
    """The existing drive's format and size, or None if it has not been created."""
    try:
        with FILES_DRIVE.open("rb") as f:
            boot = f.read(512)
        size = FILES_DRIVE.stat().st_size
    except OSError:
        return None
    return {"format": "exfat" if boot[3:11] == b"EXFAT   " else "fat32", "size_mb": size // (1024 * 1024)}


def create(fmt, size_mb):
    """Create the drive, replacing any existing one and everything on it."""
    if fmt not in FORMATS:
        raise DriveError("unknown format")
    size = size_mb * 1024 * 1024
    existing = FILES_DRIVE.stat().st_size if FILES_DRIVE.exists() else 0
    if shutil.disk_usage(FILES_DRIVE.parent).free + existing < size + 64 * 1024 * 1024:
        raise DriveError("not enough free space for the files drive")
    tmp = FILES_DRIVE.with_suffix(".new")
    try:
        with tmp.open("wb") as f:
            f.truncate(size)   # sparse: space is only used as files are added
        result = subprocess.run([*FORMATS[fmt], str(tmp)], capture_output=True, text=True)
        if result.returncode != 0:
            raise DriveError(f"could not format the files drive: {result.stderr.strip()[:120]}")
        tmp.replace(FILES_DRIVE)
    except FileNotFoundError as e:
        raise DriveError(f"{FORMATS[fmt][0]} is not installed") from e
    finally:
        tmp.unlink(missing_ok=True)
    return info()


def ensure(fmt, size_mb):
    """Return the drive's path, creating it with the given settings if missing."""
    if not FILES_DRIVE.exists():
        create(fmt, size_mb)
    return FILES_DRIVE
