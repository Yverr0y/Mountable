"""The files drive: a FAT32 or exFAT volume kept in one file.

It is presented over USB next to a mounted image (or on its own) so files such
as drivers and installers can travel with the image.

A filesystem must only be used from one side at a time. While the drive is not
presented over USB it is attached at SHARED_DIR, where files can be added and
read on this device; it is detached before a computer gets it.
"""

import grp
import os

import shutil
import subprocess

from .config import ACCESS_GROUP, FILES_DRIVE, SHARED_DIR

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
    detach()
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


def attached():
    return os.path.ismount(SHARED_DIR)


def attach():
    """Make the drive's contents available at SHARED_DIR."""
    if not FILES_DRIVE.exists() or attached():
        return
    # Unattached, the folder is read-only so nothing is saved where it would
    # be hidden once the drive is attached over it.
    SHARED_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(SHARED_DIR, 0o555)
    gid = grp.getgrnam(ACCESS_GROUP).gr_gid
    options = f"loop,uid=0,gid={gid},umask=002,noatime"
    result = subprocess.run(["mount", "-o", options, str(FILES_DRIVE), str(SHARED_DIR)],
                            capture_output=True, text=True)
    if result.returncode != 0:
        raise DriveError(f"could not open the files drive: {result.stderr.strip()[:120]}")


def detach():
    """Flush and release the drive so it can be presented over USB or replaced."""
    if not attached():
        return
    result = subprocess.run(["umount", str(SHARED_DIR)], capture_output=True, text=True)
    if result.returncode != 0:
        raise DriveError("the shared folder is in use on this device; close its files first")
