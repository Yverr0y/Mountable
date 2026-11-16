"""Client for the Mountable service socket."""

import json
import socket

from .config import SOCKET_PATH


class ServiceError(Exception):
    pass


def call(cmd, timeout=30, **params):
    """Send one command to the service and return its reply."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(timeout)
            s.connect(str(SOCKET_PATH))
            s.sendall(json.dumps({"cmd": cmd, **params}).encode() + b"\n")
            reply = json.loads(s.makefile("rb").readline())
    except (OSError, ValueError) as e:
        raise ServiceError("Mountable service is not running") from e
    if not reply.get("ok"):
        raise ServiceError(reply.get("error", "request failed"))
    return reply
