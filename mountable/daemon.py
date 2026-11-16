"""The Mountable service.

Runs as root and owns everything that outlives the UI: the mounted image and
running downloads. Clients send one JSON request per connection over a Unix
socket and get one JSON reply.
"""

import grp
import json
import os
import shutil
import socketserver
import sys
import threading
import time

from . import catalog, drive, gadget, images
from .config import (ACCESS_GROUP, CHOICES, IMAGES_DIR, RUN_DIR, SOCKET_PATH,
                     load_settings, save_setting)
from .downloads import DownloadManager

downloads = DownloadManager()


def _catalog_entry(entry_id):
    for entry in catalog.load()["images"]:
        if entry["id"] == entry_id:
            return entry
    raise ValueError("unknown catalog image")


def _auto_unmount_in(settings):
    """Seconds until the mount is removed automatically, or None."""
    minutes = settings["auto_unmount_minutes"]
    elapsed = gadget.mounted_seconds()
    if not minutes or elapsed is None:
        return None
    return max(0, int(minutes * 60 - elapsed))


def cmd_status(_):
    settings = load_settings()
    state = gadget.status()
    state["free"] = shutil.disk_usage(IMAGES_DIR).free
    state["downloads"] = downloads.list()
    state["images_dir"] = str(IMAGES_DIR)
    state["settings"] = {k: v for k, v in settings.items() if k != "catalog_url"}
    state["files_drive"] = drive.info()
    state["auto_unmount_in"] = _auto_unmount_in(settings) if state["mounted"] else None
    return state


def cmd_images(_):
    return {"images": images.list_images()}


def cmd_mount(request):
    """Mount an image by name, the files drive alone ("files_only"), or both."""
    settings = load_settings()
    path = mode = None
    writable = False
    if not request.get("files_only"):
        path = images.resolve(request["name"])
        mode = request.get("mode") or images.default_mode(path)
        if mode not in ("disk", "cdrom"):
            raise ValueError("invalid mode")
        writable = bool(request.get("writable"))
    files = None
    if request.get("files_only") or settings["files_drive"]:
        files = drive.ensure(settings["files_drive_format"], settings["files_drive_size_mb"])
    return gadget.mount(path, mode or "disk", writable, files)


def cmd_unmount(_):
    return gadget.unmount()


def cmd_delete(request):
    path = images.resolve(request["name"])
    current = gadget.mounted()
    if current and current["path"] == str(path):
        raise ValueError("image is mounted; unmount it first")
    path.unlink()
    if load_settings()["default_image"] == request["name"]:
        save_setting("default_image", "")
    return {}


def cmd_set(request):
    """Change one setting."""
    key, value = request["key"], request["value"]
    if key == "default_image":
        if value != "":
            images.resolve(value)
    elif key not in CHOICES or value not in CHOICES[key] or type(value) is not type(CHOICES[key][0]):
        raise ValueError("invalid setting")
    save_setting(key, value)
    if key == "files_drive" and value:
        settings = load_settings()
        drive.ensure(settings["files_drive_format"], settings["files_drive_size_mb"])
    return {}


def cmd_drive_create(_):
    """Create the files drive afresh with the current settings, erasing it."""
    current = gadget.mounted()
    if current and current["files_drive"]:
        raise ValueError("the files drive is mounted; unmount first")
    settings = load_settings()
    drive.create(settings["files_drive_format"], settings["files_drive_size_mb"])
    return {}


def cmd_catalog(_):
    data = catalog.load()
    present = {i["name"] for i in images.list_images()}
    for entry in data["images"]:
        entry["file"] = catalog.final_filename(entry)
        entry["installed"] = entry["file"] in present
        entry["space_needed"] = catalog.space_needed(entry)
    data["can_refresh"] = bool(load_settings()["catalog_url"])
    data["checked"] = _catalog_checked
    return data


def cmd_catalog_refresh(_):
    url = load_settings()["catalog_url"]
    if not url:
        raise ValueError("no catalog URL configured")
    _refresh_catalog(url)
    return {}


def cmd_download(request):
    downloads.start(_catalog_entry(request["id"]))
    return {}


def cmd_cancel(request):
    downloads.cancel(request["id"])
    return {}


def cmd_dismiss(request):
    downloads.dismiss(request["id"])
    return {}


_catalog_checked = ""   # when the published catalog was last fetched successfully


def _refresh_catalog(url):
    global _catalog_checked
    catalog.refresh(url)
    _catalog_checked = time.strftime("%Y-%m-%d %H:%M")


def _catalog_updater():
    """Fetch the published catalog at startup and daily; retry sooner while offline."""
    while True:
        try:
            _refresh_catalog(load_settings()["catalog_url"])
            time.sleep(24 * 3600)
        except catalog.CatalogError:
            time.sleep(10 * 60)


def _auto_unmounter():
    while True:
        time.sleep(20)
        try:
            if gadget.mounted() and _auto_unmount_in(load_settings()) == 0:
                gadget.unmount()
        except (gadget.GadgetError, OSError):
            pass


COMMANDS = {
    name[4:]: fn for name, fn in globals().items() if name.startswith("cmd_")
}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            request = json.loads(self.rfile.readline(65536))
            reply = {"ok": True, **COMMANDS[request["cmd"]](request)}
        except (ValueError, KeyError, TypeError, OSError,
                gadget.GadgetError, catalog.CatalogError, drive.DriveError) as e:
            reply = {"ok": False, "error": str(e) or type(e).__name__}
        try:
            self.wfile.write(json.dumps(reply).encode() + b"\n")
        except OSError:
            pass


class Server(socketserver.ThreadingMixIn, socketserver.UnixStreamServer):
    daemon_threads = True


def main():
    if os.geteuid() != 0:
        sys.exit("mountable service must run as root")
    gid = grp.getgrnam(ACCESS_GROUP).gr_gid
    RUN_DIR.mkdir(parents=True, exist_ok=True)
    IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    os.chown(IMAGES_DIR, 0, gid)
    os.chmod(IMAGES_DIR, 0o2775)   # setgid: files created here stay group-manageable
    os.umask(0o002)
    for stale in IMAGES_DIR.glob("*.unpack"):
        stale.unlink()

    threading.Thread(target=_catalog_updater, daemon=True).start()
    threading.Thread(target=_auto_unmounter, daemon=True).start()

    SOCKET_PATH.unlink(missing_ok=True)
    with Server(str(SOCKET_PATH), Handler) as server:
        os.chown(SOCKET_PATH, 0, gid)
        os.chmod(SOCKET_PATH, 0o660)
        server.serve_forever()


if __name__ == "__main__":
    main()
