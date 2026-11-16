"""USB mass-storage gadget control through configfs. Requires root."""

import subprocess
import threading
from pathlib import Path

from .config import RUN_DIR

CONFIGFS = Path("/sys/kernel/config")
GADGETS = CONFIGFS / "usb_gadget"
GADGET = GADGETS / "mountable"
FUNC = GADGET / "functions" / "mass_storage.usb0"
CONF = GADGET / "configs" / "c.1"
LUN = FUNC / "lun.0"
PAUSED = RUN_DIR / "paused-gadgets"

# The OS image runs its own gadget (adb) on the controller, managed by these
# services. Only one gadget can be bound at a time, so they are stopped while
# an image is mounted and started again on unmount.
VENDOR_UNITS = ("cardputer-adb-hotplug.service", "adbd.service")

_lock = threading.Lock()


class GadgetError(Exception):
    pass


def _read(path, default=""):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def _write(path, value):
    Path(path).write_text(f"{value}\n")


def find_udc():
    try:
        return next(iter(sorted(p.name for p in Path("/sys/class/udc").iterdir())), None)
    except OSError:
        return None


def host_devices():
    """Devices on the unit's own USB bus.

    The internal hub is only connected to the SoC when the Host/Slave switch
    is set to Host, so any device here means the port cannot act as a drive.
    """
    found = []
    try:
        entries = sorted(Path("/sys/bus/usb/devices").iterdir())
    except OSError:
        return found
    for dev in entries:
        if dev.name.startswith("usb") or not (dev / "idVendor").exists():
            continue
        found.append(f"{_read(dev / 'idVendor')}:{_read(dev / 'idProduct')}")
    return found


def mounted():
    if not LUN.is_dir():
        return None
    return {
        "path": _read(LUN / "file"),
        "mode": "cdrom" if _read(LUN / "cdrom") == "1" else "disk",
        "writable": _read(LUN / "ro") == "0",
    }


def status():
    udc = find_udc()
    return {
        "udc": udc,
        "udc_state": _read(f"/sys/class/udc/{udc}/state", "unknown") if udc else "none",
        "speed": _read(f"/sys/class/udc/{udc}/current_speed", "unknown") if udc else "unknown",
        "switch": "host" if host_devices() else "device",
        "mounted": mounted(),
    }


def _systemctl(*args):
    return subprocess.run(["systemctl", *args], capture_output=True, text=True).returncode == 0


def _pause_others(udc):
    paused = []
    for unit in VENDOR_UNITS:
        if _systemctl("is-active", "--quiet", unit):
            _systemctl("stop", unit)
            paused.append(f"unit {unit}")
    for gadget in GADGETS.iterdir():
        if gadget != GADGET and _read(gadget / "UDC") == udc:
            try:
                _write(gadget / "UDC", "")
                paused.append(f"gadget {gadget.name}")
            except OSError:
                pass
    if paused:
        with PAUSED.open("a") as f:
            f.write("\n".join(paused) + "\n")


def _resume_others():
    if not PAUSED.exists():
        return
    udc = find_udc()
    for line in reversed(PAUSED.read_text().split("\n")):
        kind, _, name = line.partition(" ")
        if kind == "unit":
            _systemctl("start", name)
        elif kind == "gadget" and udc:
            try:
                _write(GADGETS / name / "UDC", udc)
            except OSError:
                pass
    PAUSED.unlink(missing_ok=True)


def _teardown():
    if GADGET.is_dir():
        try:
            _write(GADGET / "UDC", "")
        except OSError:
            pass
        (CONF / "mass_storage.usb0").unlink(missing_ok=True)
        for d in (CONF / "strings" / "0x409", CONF, FUNC, GADGET / "strings" / "0x409", GADGET):
            try:
                d.rmdir()
            except OSError:
                pass
        if GADGET.is_dir():
            raise GadgetError("could not remove the USB gadget")
    _resume_others()


def mount(path, mode="disk", writable=False):
    """Expose the file at `path` as a USB drive (mode "disk") or CD-ROM."""
    path = Path(path)
    cdrom = mode == "cdrom"
    with _lock:
        if GADGET.is_dir():
            raise GadgetError("an image is already mounted")
        if not path.is_file():
            raise GadgetError(f"no such image: {path.name}")
        subprocess.run(["modprobe", "libcomposite"], capture_output=True)
        if not GADGETS.is_dir():
            subprocess.run(["mount", "-t", "configfs", "none", str(CONFIGFS)], capture_output=True)
        if not GADGETS.is_dir():
            raise GadgetError("kernel has no USB gadget support")
        udc = find_udc()
        if not udc:
            raise GadgetError("no USB device controller (is dtoverlay=dwc2 set?)")

        serial = _read("/etc/machine-id", "0000000000000001")[:16]
        try:
            GADGET.mkdir()
            _write(GADGET / "idVendor", "0x1d6b")   # Linux Foundation
            _write(GADGET / "idProduct", "0x0104")  # Multifunction Composite Gadget
            _write(GADGET / "bcdUSB", "0x0200")
            (GADGET / "strings" / "0x409").mkdir()
            _write(GADGET / "strings" / "0x409" / "serialnumber", serial)
            _write(GADGET / "strings" / "0x409" / "manufacturer", "Mountable")
            _write(GADGET / "strings" / "0x409" / "product", "Virtual Drive")
            CONF.mkdir()
            (CONF / "strings" / "0x409").mkdir()
            _write(CONF / "strings" / "0x409" / "configuration", "Mass Storage")
            _write(CONF / "MaxPower", "250")
            FUNC.mkdir()
            _write(FUNC / "stall", "0")
            _write(LUN / "removable", "1")
            _write(LUN / "cdrom", "1" if cdrom else "0")
            _write(LUN / "ro", "0" if writable and not cdrom else "1")
            _write(LUN / "file", path)
            (CONF / "mass_storage.usb0").symlink_to(FUNC)
            _pause_others(udc)
            _write(GADGET / "UDC", udc)
        except OSError as e:
            try:
                _teardown()
            except GadgetError:
                pass
            raise GadgetError(f"could not mount: {e.strerror or e}") from e
    return status()


def unmount():
    with _lock:
        _teardown()
    return status()
