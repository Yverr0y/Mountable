"""Looking for a newer release of Mountable.

The newest release is read from the project's releases on GitHub and
remembered, so the app can say an update is available without waiting for
the network.
"""

import json
import re
import urllib.request

from . import __version__
from .catalog import USER_AGENT
from .config import CACHE_DIR

RELEASES_PAGE = "github.com/s0liton/Mountable/releases"
LATEST_RELEASE = "https://api.github.com/repos/s0liton/Mountable/releases/latest"
CACHE = CACHE_DIR / "latest-release"

_VERSION = re.compile(r"v?(\d+(?:\.\d+){0,3})")


def _numbers(version):
    return tuple(int(part) for part in version.split("."))


def check():
    """Ask GitHub for the newest release and remember it. Never raises."""
    request = urllib.request.Request(LATEST_RELEASE, headers={
        "User-Agent": USER_AGENT, "Accept": "application/vnd.github+json"})
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            match = _VERSION.fullmatch(str(json.loads(response.read(1024 * 1024))["tag_name"]))
        if match:
            CACHE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = CACHE.with_suffix(".tmp")
            tmp.write_text(match.group(1) + "\n")
            tmp.replace(CACHE)
    except (OSError, ValueError, KeyError, TypeError):
        pass   # offline, no release yet, or an answer we do not understand


def available():
    """The newest release's version if it is newer than this one, else ""."""
    try:
        latest = CACHE.read_text().strip()
        if _VERSION.fullmatch(latest) and _numbers(latest) > _numbers(__version__):
            return latest
    except (OSError, ValueError):
        pass
    return ""
