"""The Mountable service.

Runs as root and owns everything that outlives the UI: the mounted image and
running downloads. Clients send one JSON request per connection over a Unix
socket and get one JSON reply.

It runs either all the time as a system service, or only while it is needed:
started by the app with --exit-when-idle, it stops once the app has closed
and nothing is mounted or downloading.
"""

import argparse
import grp
import json
import os
import shutil
import socketserver
import sys
import threading
import time

from . import catalog, drive, gadget, images, updates
from .config import (ACCESS_GROUP, CHOICES, IMAGES_DIR, RUN_DIR, SHARED_DIR, SOCKET_PATH,
                     load_settings, save_setting)
from .downloads import ACTIVE, DownloadManager, verified_files

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
    if not minutes or elapsed is None or gadget.TIMER_OFF.exists():
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
    state["shared_dir"] = str(SHARED_DIR)
    state["auto_unmount_in"] = _auto_unmount_in(settings) if state["mounted"] else None
    state["auto_unmount_off"] = bool(state["mounted"]) and gadget.TIMER_OFF.exists()
    state["update"] = updates.available()
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
        drive.detach()   # a computer is about to own the filesystem
    try:
        return gadget.mount(path, mode or "disk", writable, files)
    except gadget.GadgetError:
        _sync_shared_folder()
        raise


def _sync_shared_folder():
    """Attach the files drive at the shared folder exactly when that is safe."""
    current = gadget.mounted()
    try:
        if load_settings()["files_drive"] and not (current and current["files_drive"]):
            drive.attach()
        else:
            drive.detach()
    except drive.DriveError:
        pass


def cmd_unmount(_):
    state = gadget.unmount()
    _sync_shared_folder()
    return state


def cmd_keep(_):
    """Switch auto-unmount off for the current mount; the setting is unchanged."""
    if not gadget.mounted():
        raise ValueError("nothing is mounted")
    gadget.TIMER_OFF.touch()
    return {}


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
    if key == "files_drive":
        if value:
            settings = load_settings()
            drive.ensure(settings["files_drive_format"], settings["files_drive_size_mb"])
        _sync_shared_folder()
    return {}


def cmd_drive_create(_):
    """Create the files drive afresh with the current settings, erasing it."""
    current = gadget.mounted()
    if current and current["files_drive"]:
        raise ValueError("the files drive is mounted; unmount first")
    settings = load_settings()
    try:
        drive.create(settings["files_drive_format"], settings["files_drive_size_mb"])
    finally:
        _sync_shared_folder()
    return {}


def cmd_catalog(_):
    data = catalog.load()
    present = {i["name"] for i in images.list_images()}
    for entry in data["images"]:
        entry["file"] = catalog.final_filename(entry)
    verified = verified_files({e["file"]: e["sha256"] for e in data["images"] if e["file"] in present})
    for entry in data["images"]:
        entry["installed"] = entry["file"] in present
        entry["verified"] = entry["file"] in verified
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


def cmd_check(_):
    """Sent by the app when it opens: look for news unless that was done lately."""
    if time.monotonic() - _checked_at > 3600:
        _check_now.set()
    return {}


_catalog_checked = ""   # when the published catalog was last fetched successfully
_checked_at = 0.0       # when the updater last tried, on the monotonic clock
_check_now = threading.Event()


def _refresh_catalog(url):
    global _catalog_checked
    catalog.refresh(url)
    _catalog_checked = time.strftime("%Y-%m-%d %H:%M")


def _updater():
    """Fetch the published catalog and look for a new release of the app.

    Runs when the service starts, once a day, and when the app opens after
    more than an hour; while the catalog cannot be fetched it retries sooner.
    """
    global _checked_at
    while True:
        _checked_at = time.monotonic()
        try:
            _refresh_catalog(load_settings()["catalog_url"])
            wait = 24 * 3600
        except catalog.CatalogError:
            wait = 10 * 60
        updates.check()
        _check_now.wait(wait)
        _check_now.clear()


def _auto_unmounter():
    while True:
        time.sleep(5)
        try:
            if gadget.mounted() and _auto_unmount_in(load_settings()) == 0:
                gadget.unmount()
                _sync_shared_folder()
        except (gadget.GadgetError, OSError):
            pass


COMMANDS = {
    name[4:]: fn for name, fn in globals().items() if name.startswith("cmd_")
}


IDLE_EXIT = 90   # seconds with no app, mount or download before stopping
_last_request = time.monotonic()


def _exit_when_idle(server):
    global _last_request
    while True:
        time.sleep(15)
        if gadget.mounted() or any(d["state"] in ACTIVE for d in downloads.list()):
            _last_request = time.monotonic()
        elif time.monotonic() - _last_request > IDLE_EXIT:
            server.shutdown()
            return


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        global _last_request
        _last_request = time.monotonic()
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
    parser = argparse.ArgumentParser(prog="mountable.daemon", description="Mountable service")
    parser.add_argument("--exit-when-idle", action="store_true",
                        help="stop once the app has closed and nothing is mounted or downloading")
    args = parser.parse_args()
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

    _sync_shared_folder()
    threading.Thread(target=_updater, daemon=True).start()
    threading.Thread(target=_auto_unmounter, daemon=True).start()

    SOCKET_PATH.unlink(missing_ok=True)
    with Server(str(SOCKET_PATH), Handler) as server:
        os.chown(SOCKET_PATH, 0, gid)
        os.chmod(SOCKET_PATH, 0o660)
        if args.exit_when_idle:
            threading.Thread(target=_exit_when_idle, args=(server,), daemon=True).start()
        server.serve_forever()
    SOCKET_PATH.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
