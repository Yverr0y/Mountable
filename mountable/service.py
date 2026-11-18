"""Starting the service from the app.

Installs without an always-on service start it when the app opens. That needs
root, so it goes through sudo with the device password.
"""

import os
import subprocess
import time

from .client import ServiceError, call
from .config import START_HELPER


def running():
    try:
        call("status", timeout=5)
        return True
    except ServiceError:
        return False


def start(password=None):
    """Start the service; return "" on success or what went wrong.

    Without a password this succeeds only where sudo is set up never to ask
    for one. A password sudo still remembers from a recent use elsewhere does
    not count (-k), so the app asks the same way every time. The password goes
    to sudo on its standard input and is kept nowhere.
    """
    command = ["sudo", "-n", "-k"] if password is None else ["sudo", "-S", "-k", "-p", ""]
    try:
        result = subprocess.run(
            [*command, str(START_HELPER)], input="" if password is None else password + "\n",
            capture_output=True, text=True, timeout=30, env={**os.environ, "LC_ALL": "C"})
    except FileNotFoundError:
        return "sudo is not installed"
    except subprocess.TimeoutExpired:
        return "Starting the service timed out"
    if result.returncode == 0:
        for _ in range(40):
            if running():
                return ""
            time.sleep(0.25)
        return "The service did not start"
    message = result.stderr.strip()
    if "sudoers" in message or "not allowed" in message:
        return "This user may not use sudo"
    if "password" in message or "try again" in message:
        return "Wrong password"
    return message.splitlines()[-1][:60] if message else "Could not start the service"
