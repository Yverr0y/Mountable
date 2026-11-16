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

DEFAULTS = {
    # URL of the published catalog. Empty: use only the catalog shipped with the app.
    "catalog_url": "",
}


def load_settings():
    settings = dict(DEFAULTS)
    try:
        settings.update(json.loads(CONFIG_FILE.read_text()))
    except (OSError, ValueError):
        pass
    return settings
