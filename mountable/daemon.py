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

from . import catalog, gadget, images
from .config import ACCESS_GROUP, IMAGES_DIR, RUN_DIR, SOCKET_PATH, load_settings
from .downloads import DownloadManager

downloads = DownloadManager()


def _catalog_entry(entry_id):
    for entry in catalog.load()["images"]:
        if entry["id"] == entry_id:
            return entry
    raise ValueError("unknown catalog image")


def cmd_status(_):
    state = gadget.status()
    state["free"] = shutil.disk_usage(IMAGES_DIR).free
    state["downloads"] = downloads.list()
    state["images_dir"] = str(IMAGES_DIR)
    return state


def cmd_images(_):
    return {"images": images.list_images()}


def cmd_mount(request):
    path = images.resolve(request["name"])
    mode = request.get("mode") or images.default_mode(path)
    if mode not in ("disk", "cdrom"):
        raise ValueError("invalid mode")
    return gadget.mount(path, mode, bool(request.get("writable")))


def cmd_unmount(_):
    return gadget.unmount()


def cmd_delete(request):
    path = images.resolve(request["name"])
    current = gadget.mounted()
    if current and current["path"] == str(path):
        raise ValueError("image is mounted; unmount it first")
    path.unlink()
    return {}


def cmd_catalog(_):
    data = catalog.load()
    present = {i["name"] for i in images.list_images()}
    for entry in data["images"]:
        entry["file"] = catalog.final_filename(entry)
        entry["installed"] = entry["file"] in present
        entry["space_needed"] = catalog.space_needed(entry)
    data["can_refresh"] = bool(load_settings()["catalog_url"])
    return data


def cmd_catalog_refresh(_):
    url = load_settings()["catalog_url"]
    if not url:
        raise ValueError("no catalog URL configured")
    catalog.refresh(url)
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


COMMANDS = {
    name[4:]: fn for name, fn in globals().items() if name.startswith("cmd_")
}


class Handler(socketserver.StreamRequestHandler):
    def handle(self):
        try:
            request = json.loads(self.rfile.readline(65536))
            reply = {"ok": True, **COMMANDS[request["cmd"]](request)}
        except (ValueError, KeyError, TypeError, OSError,
                gadget.GadgetError, catalog.CatalogError) as e:
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

    SOCKET_PATH.unlink(missing_ok=True)
    with Server(str(SOCKET_PATH), Handler) as server:
        os.chown(SOCKET_PATH, 0, gid)
        os.chmod(SOCKET_PATH, 0o660)
        server.serve_forever()


if __name__ == "__main__":
    main()
