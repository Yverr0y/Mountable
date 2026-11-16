"""The catalog of downloadable images.

The catalog is a JSON document published separately from the app, so images
can be added or removed without an app update. The newest of the bundled copy
and the last successfully fetched copy is used.
"""

import json
import re
import urllib.request
from pathlib import Path

from . import __version__
from .config import BUNDLED_CATALOG, CACHE_DIR, IMAGE_EXTENSIONS

SCHEMA = 1
CACHED_CATALOG = CACHE_DIR / "catalog.json"
MAX_CATALOG_BYTES = 2 * 1024 * 1024
COMPRESSION_SUFFIX = {"xz": ".xz", "gz": ".gz", "bz2": ".bz2"}
USER_AGENT = f"Mountable/{__version__}"

_FILENAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,200}")
_SHA256 = re.compile(r"[0-9a-f]{64}")


class CatalogError(Exception):
    pass


def final_filename(entry):
    """Name of the mountable file an entry produces, after any decompression."""
    name = entry["filename"]
    suffix = COMPRESSION_SUFFIX.get(entry.get("compression") or "")
    if suffix and name.lower().endswith(suffix):
        name = name[: -len(suffix)]
    return name


def _valid_entry(entry, categories):
    try:
        return (
            isinstance(entry["id"], str)
            and isinstance(entry["name"], str)
            and entry["category"] in categories
            and entry["url"].startswith("https://")
            and _FILENAME.fullmatch(entry["filename"])
            and isinstance(entry["size"], int) and entry["size"] > 0
            and _SHA256.fullmatch(entry["sha256"])
            and entry.get("compression") in (None, *COMPRESSION_SUFFIX)
            and entry.get("mode", "disk") in ("disk", "cdrom")
            and Path(final_filename(entry)).suffix.lower() in IMAGE_EXTENSIONS
        )
    except (KeyError, TypeError, AttributeError):
        return False


def validate(data):
    """Check a parsed catalog and drop entries the app cannot use safely."""
    if not isinstance(data, dict) or data.get("schema") != SCHEMA:
        raise CatalogError("unsupported catalog format")
    try:
        categories = [
            {"id": c["id"], "name": c["name"], "description": c.get("description", "")}
            for c in data["categories"]
        ]
        ids = {c["id"] for c in categories}
        seen, images = set(), []
        for entry in data["images"]:
            if not _valid_entry(entry, ids) or entry["id"] in seen:
                continue
            seen.add(entry["id"])
            images.append(entry)
    except (KeyError, TypeError) as e:
        raise CatalogError("malformed catalog") from e
    if not images:
        raise CatalogError("catalog has no usable images")
    used = {e["category"] for e in images}
    return {
        "schema": SCHEMA,
        "updated": str(data.get("updated", "")),
        "categories": [c for c in categories if c["id"] in used],
        "images": images,
    }


def _load_file(path):
    try:
        return validate(json.loads(Path(path).read_text()))
    except (OSError, ValueError, CatalogError):
        return None


def load():
    """Return the newest usable catalog, or an empty one."""
    candidates = [c for c in (_load_file(CACHED_CATALOG), _load_file(BUNDLED_CATALOG)) if c]
    if not candidates:
        return {"schema": SCHEMA, "updated": "", "categories": [], "images": []}
    return max(candidates, key=lambda c: c["updated"])


def refresh(url):
    """Fetch the published catalog and cache it. Returns the catalog now in use."""
    if not url.startswith("https://"):
        raise CatalogError("catalog URL must use https")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            raw = response.read(MAX_CATALOG_BYTES + 1)
    except OSError as e:
        raise CatalogError(f"could not fetch catalog: {e}") from e
    if len(raw) > MAX_CATALOG_BYTES:
        raise CatalogError("catalog is too large")
    try:
        validate(json.loads(raw))
    except ValueError as e:
        raise CatalogError("catalog is not valid JSON") from e
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = CACHED_CATALOG.with_suffix(".tmp")
    tmp.write_bytes(raw)
    tmp.replace(CACHED_CATALOG)
    return load()
