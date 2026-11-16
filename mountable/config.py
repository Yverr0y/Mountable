"""Paths and settings shared by the service and the UI."""

import json
import os
from pathlib import Path

IMAGES_DIR = Path(os.environ.get("MOUNTABLE_IMAGES_DIR", "/srv/mountable/images"))
CACHE_DIR = Path(os.environ.get("MOUNTABLE_CACHE_DIR", "/var/cache/mountable"))
RUN_DIR = Path(os.environ.get("MOUNTABLE_RUN_DIR", "/run/mountable"))
SOCKET_PATH = RUN_DIR / "mountable.sock"
CONFIG_FILE = Path(os.environ.get("MOUNTABLE_CONFIG", "/etc/mountable/config.json"))
BUNDLED_CATALOG = Path(__file__).resolve().parent.parent / "catalog" / "catalog.json"

# Group allowed to talk to the service and to manage files in IMAGES_DIR.
ACCESS_GROUP = "users"

# File types offered for mounting. Anything else in IMAGES_DIR is ignored.
IMAGE_EXTENSIONS = {".iso", ".img", ".raw", ".dd", ".bin", ".ima", ".dsk", ".hdd", ".usb"}

# The optional extra drive for carrying files next to a mounted image.
FILES_DRIVE = IMAGES_DIR.parent / "files-drive.img"

CATALOG_URL = "https://raw.githubusercontent.com/s0liton/Mountable/main/catalog/catalog.json"

DEFAULTS = {
    # Where the published catalog is fetched from.
    "catalog_url": CATALOG_URL,
    # Unmount automatically this many minutes after mounting; 0 disables.
    "auto_unmount_minutes": 0,
    # Mount disk images (not ISOs) writable unless told otherwise.
    "default_writable": False,
    # Image mounted when the app opens with nothing mounted; "" for none.
    "default_image": "",
    # Present an extra read-write drive for files alongside the image.
    "files_drive": False,
    "files_drive_format": "fat32",
    "files_drive_size_mb": 1024,
}

# Settings the user may change, and the values each accepts.
CHOICES = {
    "auto_unmount_minutes": [0, 30, 60, 120, 240, 480],
    "default_writable": [False, True],
    "files_drive": [False, True],
    "files_drive_format": ["fat32", "exfat"],
    "files_drive_size_mb": [256, 1024, 2048, 4096, 8192],
}


def load_settings():
    settings = dict(DEFAULTS)
    try:
        stored = json.loads(CONFIG_FILE.read_text())
        settings.update({k: v for k, v in stored.items() if k in DEFAULTS})
    except (OSError, ValueError, AttributeError):
        pass
    if not settings["catalog_url"]:
        settings["catalog_url"] = CATALOG_URL
    return settings


def save_setting(key, value):
    """Persist one setting, keeping the rest of the file as it is."""
    try:
        stored = json.loads(CONFIG_FILE.read_text())
    except (OSError, ValueError):
        stored = {}
    stored[key] = value
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = CONFIG_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(stored, indent=2) + "\n")
    tmp.replace(CONFIG_FILE)
