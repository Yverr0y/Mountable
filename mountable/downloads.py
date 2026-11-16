"""Background image downloads with resume, checksum verification and unpacking."""

import bz2
import gzip
import hashlib
import lzma
import os
import shutil
import threading
import time
import urllib.error
import urllib.request
import zipfile

from .catalog import USER_AGENT, final_filename, space_needed
from .config import IMAGES_DIR

CHUNK = 1024 * 1024
RETRIES = 5


def _open_zip(path, mode):
    """Open the disk image inside a zip archive: its largest member."""
    archive = zipfile.ZipFile(path)
    return archive.open(max(archive.infolist(), key=lambda m: m.file_size))


OPENERS = {"xz": lzma.open, "gz": gzip.open, "bz2": bz2.open, "zip": _open_zip}
ACTIVE = ("queued", "downloading", "verifying", "unpacking")


class Cancelled(Exception):
    pass


class Download:
    def __init__(self, entry):
        self.entry = entry
        self.state = "queued"
        self.received = 0
        self.total = entry["size"]
        self.speed = 0
        self.error = ""
        self.cancel = threading.Event()

    def info(self):
        return {
            "id": self.entry["id"],
            "name": self.entry["name"],
            "state": self.state,
            "received": self.received,
            "total": self.total,
            "speed": self.speed,
            "error": self.error,
        }


class DownloadManager:
    """Runs downloads one at a time; Wi-Fi and the SD card gain nothing from more."""

    def __init__(self):
        self._downloads = {}
        self._queue = []
        self._lock = threading.Lock()
        self._wake = threading.Condition(self._lock)
        threading.Thread(target=self._worker, daemon=True).start()

    def list(self):
        with self._lock:
            return [d.info() for d in self._downloads.values()]

    def start(self, entry):
        IMAGES_DIR.mkdir(parents=True, exist_ok=True)
        if shutil.disk_usage(IMAGES_DIR).free < space_needed(entry) + 64 * CHUNK:
            raise ValueError("not enough free space")
        with self._lock:
            current = self._downloads.get(entry["id"])
            if current and current.state in ACTIVE:
                return
            download = Download(entry)
            self._downloads[entry["id"]] = download
            self._queue.append(download)
            self._wake.notify()

    def cancel(self, entry_id):
        with self._lock:
            download = self._downloads.get(entry_id)
            if not download:
                return
            download.cancel.set()
            if download in self._queue:
                self._queue.remove(download)
                del self._downloads[entry_id]

    def dismiss(self, entry_id):
        with self._lock:
            download = self._downloads.get(entry_id)
            if download and download.state not in ACTIVE:
                del self._downloads[entry_id]

    def _worker(self):
        while True:
            with self._lock:
                while not self._queue:
                    self._wake.wait()
                download = self._queue.pop(0)
            part = IMAGES_DIR / (download.entry["filename"] + ".part")
            try:
                self._run(download, part)
                download.state = "done"
            except Cancelled:
                part.unlink(missing_ok=True)
                with self._lock:
                    self._downloads.pop(download.entry["id"], None)
            except Exception as e:  # reported to the user, never fatal to the service
                part.unlink(missing_ok=True) if isinstance(e, ValueError) else None
                download.state = "error"
                download.error = str(e) or type(e).__name__

    def _run(self, download, part):
        entry = download.entry
        self._fetch(download, part)

        download.state = "verifying"
        digest = hashlib.sha256()
        with part.open("rb") as f:
            while chunk := f.read(CHUNK):
                if download.cancel.is_set():
                    raise Cancelled
                digest.update(chunk)
        if digest.hexdigest() != entry["sha256"]:
            part.unlink(missing_ok=True)
            raise ValueError("checksum mismatch; download discarded")

        final = IMAGES_DIR / final_filename(entry)
        if entry.get("compression"):
            download.state = "unpacking"
            unpacked = final.with_name(final.name + ".unpack")
            try:
                with OPENERS[entry["compression"]](part, "rb") as src, unpacked.open("wb") as dst:
                    while chunk := src.read(CHUNK):
                        if download.cancel.is_set():
                            raise Cancelled
                        dst.write(chunk)
                unpacked.replace(final)
            finally:
                unpacked.unlink(missing_ok=True)
            part.unlink(missing_ok=True)
        else:
            part.replace(final)
        os.chmod(final, 0o664)

    def _fetch(self, download, part):
        entry = download.entry
        download.state = "downloading"
        failures = 0
        while True:
            download.received = part.stat().st_size if part.exists() else 0
            if download.received == entry["size"]:
                return
            if download.received > entry["size"]:
                part.unlink()
                continue
            request = urllib.request.Request(entry["url"], headers={"User-Agent": USER_AGENT})
            if download.received:
                request.add_header("Range", f"bytes={download.received}-")
            try:
                with urllib.request.urlopen(request, timeout=30) as response:
                    if download.received and response.status != 206:
                        part.unlink()   # server ignored the range; start over
                        continue
                    self._copy(download, response, part)
            except (Cancelled, ValueError):
                raise
            except (OSError, urllib.error.URLError) as e:
                failures += 1
                if failures > RETRIES:
                    raise ValueError(f"download failed: {getattr(e, 'reason', e)}") from e
                if download.cancel.wait(3 * failures):
                    raise Cancelled from None

    def _copy(self, download, response, part):
        window_start, window_bytes = time.monotonic(), 0
        with part.open("ab") as f:
            while chunk := response.read(256 * 1024):
                if download.cancel.is_set():
                    raise Cancelled
                f.write(chunk)
                download.received += len(chunk)
                if download.received > download.total:
                    raise ValueError("download is larger than the catalog says; discarded")
                window_bytes += len(chunk)
                elapsed = time.monotonic() - window_start
                if elapsed >= 2:
                    download.speed = int(window_bytes / elapsed)
                    window_start, window_bytes = time.monotonic(), 0
