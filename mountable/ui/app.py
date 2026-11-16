"""The Mountable user interface for the 320x170 built-in screen."""

import argparse
import os
import time

from .. import __version__
from ..client import ServiceError, call
from ..config import CHOICES
from . import display
from .display import HEIGHT, WIDTH, pygame

FONT_DIR = "/usr/share/fonts/truetype/dejavu/"

BG = (14, 16, 22)
PANEL = (30, 34, 46)
SELECTED = (44, 62, 104)
TEXT = (236, 239, 246)
DIM = (142, 150, 168)
ACCENT = (255, 176, 46)
GOOD = (84, 214, 124)
BAD = (244, 96, 96)

HEADER_H = 20
FOOTER_H = 15
ROW_H = 22
BODY_TOP = HEADER_H + 2
ROWS = (HEIGHT - HEADER_H - FOOTER_H - 2) // ROW_H

ACTIVE_STATES = ("queued", "downloading", "verifying", "unpacking")


def human_size(n):
    for unit in ("B", "KB", "MB"):
        if n < 1000:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} GB" if n < 100 else f"{n:.0f} GB"


def mounted_name(mounted):
    return os.path.basename(mounted["path"]) if mounted.get("path") else "Files drive"


def minutes_label(minutes):
    if not minutes:
        return "off"
    if minutes < 60:
        return f"{minutes} min"
    return "1 hour" if minutes == 60 else f"{minutes // 60} hours"


def megabytes_label(mb):
    return f"{mb} MB" if mb < 1024 else f"{mb // 1024} GB"


FORMAT_LABEL = {"fat32": "FAT32", "exfat": "exFAT"}


def download_label(d):
    if d["state"] == "downloading":
        pct = 100 * d["received"] // max(d["total"], 1)
        return f"{pct}%  {human_size(d['speed'])}/s" if d["speed"] else f"{pct}%"
    return {"queued": "waiting", "done": "done", "error": "failed"}.get(d["state"], d["state"])


class UI:
    """Drawing helpers shared by all screens."""

    def __init__(self):
        pygame.font.init()
        self.surface = display.new_surface()
        self.font = pygame.font.Font(FONT_DIR + "DejaVuSans.ttf", 12)
        self.bold = pygame.font.Font(FONT_DIR + "DejaVuSans-Bold.ttf", 12)
        self.small = pygame.font.Font(FONT_DIR + "DejaVuSans.ttf", 10)
        self.big = pygame.font.Font(FONT_DIR + "DejaVuSans-Bold.ttf", 15)

    def fit(self, text, font, width):
        if font.size(text)[0] <= width:
            return text
        while text and font.size(text + "…")[0] > width:
            text = text[:-1]
        return text.rstrip() + "…"

    def text(self, text, pos, font=None, color=TEXT, width=None, align="left"):
        font = font or self.font
        if width is not None:
            text = self.fit(text, font, width)
        image = font.render(text, True, color)
        x, y = pos
        if align == "right":
            x -= image.get_width()
        elif align == "center":
            x -= image.get_width() // 2
        self.surface.blit(image, (x, y))
        return image.get_width()

    def wrap(self, text, font, width, max_lines):
        lines, line = [], ""
        for word in text.split():
            trial = f"{line} {word}".strip()
            if font.size(trial)[0] <= width:
                line = trial
                continue
            lines.append(line)
            line = word
        lines.append(line)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = self.fit(lines[-1] + " …", font, width)
        return [l for l in lines if l]

    def paragraph(self, text, pos, width, font=None, color=TEXT, max_lines=3, align="left"):
        font = font or self.font
        x, y = pos
        for line in self.wrap(text, font, width, max_lines):
            self.text(line, (x, y), font, color, align=align)
            y += font.get_linesize()
        return y

    def bar(self, rect, fraction, color=ACCENT):
        pygame.draw.rect(self.surface, PANEL, rect, border_radius=3)
        x, y, w, h = rect
        filled = int(w * max(0.0, min(1.0, fraction)))
        if filled > 2:
            pygame.draw.rect(self.surface, color, (x, y, filled, h), border_radius=3)

    def icon(self, kind, x, y, color=TEXT):
        """An 11x11 pictogram: a disc, a USB stick or a folder."""
        s = self.surface
        if kind == "cdrom":
            pygame.draw.circle(s, color, (x + 5, y + 5), 5)
            pygame.draw.circle(s, PANEL, (x + 5, y + 5), 1)
        elif kind == "disk":
            pygame.draw.rect(s, color, (x, y + 1, 8, 9), border_radius=1)
            pygame.draw.rect(s, color, (x + 8, y + 3, 3, 5))
        else:
            pygame.draw.rect(s, color, (x, y + 1, 5, 3), border_radius=1)
            pygame.draw.rect(s, color, (x, y + 3, 11, 7), border_radius=1)

    def mount_tags(self, mounted):
        """Draw what is mounted in the middle of the header; return its left edge."""
        tags = []
        if mounted and mounted.get("path"):
            writable = mounted.get("writable")
            tags.append((mounted.get("mode", "disk"), "R/W" if writable else "R", BAD if writable else GOOD))
        if mounted and mounted.get("files_drive"):
            tags.append(("files", "R/W", BAD))
        if not tags:
            return WIDTH
        gap = 9
        widths = [11 + 3 + self.small.size(label)[0] for _, label, _ in tags]
        left = x = (WIDTH - sum(widths) - gap * (len(tags) - 1)) // 2
        for (kind, label, color), width in zip(tags, widths):
            self.icon(kind, x, 4)
            self.text(label, (x + 14, 3), self.small, color)
            x += width + gap
        return left

    def frame(self, title, right="", right_color=DIM, hints="", mounted=None):
        s = self.surface
        s.fill(BG)
        pygame.draw.rect(s, PANEL, (0, 0, WIDTH, HEADER_H))
        used = self.text(right, (WIDTH - 6, 3), self.small, right_color, align="right") if right else 0
        left = self.mount_tags(mounted)
        self.text(title, (6, 2), self.bold, ACCENT, width=min(WIDTH - 20 - used, left - 14))
        pygame.draw.rect(s, PANEL, (0, HEIGHT - FOOTER_H, WIDTH, FOOTER_H))
        self.text(hints, (6, HEIGHT - FOOTER_H + 1), self.small, DIM, width=WIDTH - 12)


class Screen:
    title = "Mountable"
    hints = ""
    animated = False

    def __init__(self, app):
        self.app = app

    def refresh(self):
        """Reload this screen's data; called when shown and about once a second."""

    def key(self, key):
        if key == "esc":
            self.app.pop()

    def header_right(self):
        return "", DIM

    def draw(self, ui):
        right, color = self.header_right()
        ui.frame(self.title, right, color, self.hints, self.app.status.get("mounted"))
        self.body(ui)

    def body(self, ui):
        pass


class ListScreen(Screen):
    """A scrolling list of rows: (label, right text, right colour, payload)."""

    hints = "F/X move   Enter select   Esc back"
    empty = "Nothing here."
    list_top = BODY_TOP   # where the rows start, and how many fit
    list_rows = ROWS

    def __init__(self, app):
        super().__init__(app)
        self.rows = []
        self.index = 0
        self.top = 0

    def key(self, key):
        count = len(self.rows)
        if key in ("up", "down", "pageup", "pagedown") and count:
            step = {"up": -1, "down": 1, "pageup": -self.list_rows, "pagedown": self.list_rows}[key]
            if key in ("up", "down"):
                self.index = (self.index + step) % count
            else:
                self.index = max(0, min(count - 1, self.index + step))
        elif key in ("enter", "right") and count:
            self.activate(self.rows[self.index][3])
        elif key in ("esc", "left"):
            self.app.pop()

    def activate(self, payload):
        pass

    def body(self, ui):
        if not self.rows:
            ui.paragraph(self.empty, (WIDTH // 2, BODY_TOP + 30), WIDTH - 40, color=DIM,
                         max_lines=5, align="center")
            return
        self.index = max(0, min(self.index, len(self.rows) - 1))
        if self.index < self.top:
            self.top = self.index
        elif self.index >= self.top + self.list_rows:
            self.top = self.index - self.list_rows + 1
        for i, (label, right, color, _) in enumerate(self.rows[self.top:self.top + self.list_rows]):
            y = self.list_top + i * ROW_H
            selected = self.top + i == self.index
            if selected:
                pygame.draw.rect(ui.surface, SELECTED, (3, y, WIDTH - 10, ROW_H - 2), border_radius=4)
            used = ui.text(right, (WIDTH - 14, y + 4), ui.small, color or DIM, width=170,
                           align="right") if right else 0
            ui.text(label, (10, y + 3), ui.bold if selected else ui.font, TEXT, width=WIDTH - 34 - used)
        if len(self.rows) > self.list_rows:   # scroll indicator
            track = self.list_rows * ROW_H - 2
            size = max(10, track * self.list_rows // len(self.rows))
            offset = (track - size) * self.top // (len(self.rows) - self.list_rows)
            pygame.draw.rect(ui.surface, DIM, (WIDTH - 4, self.list_top + offset, 2, size))


class Confirm(Screen):
    hints = "Z/C choose   Enter confirm   Esc cancel"

    def __init__(self, app, title, message, action, yes="Yes"):
        super().__init__(app)
        self.title, self.message, self.action, self.yes = title, message, action, yes
        self.choice = 0

    def key(self, key):
        if key in ("left", "right", "up", "down"):
            self.choice ^= 1
        elif key == "y" or (key == "enter" and self.choice == 1):
            self.app.pop()
            self.action()
        elif key in ("esc", "n", "enter"):
            self.app.pop()

    def body(self, ui):
        ui.paragraph(self.message, (WIDTH // 2, BODY_TOP + 14), WIDTH - 30, max_lines=4, align="center")
        for i, label in enumerate(("Cancel", self.yes)):
            rect = pygame.Rect(40 + i * 130, HEIGHT - FOOTER_H - 36, 110, 24)
            active = self.choice == i
            pygame.draw.rect(ui.surface, SELECTED if active else PANEL, rect, border_radius=5)
            ui.text(label, (rect.centerx, rect.y + 5), ui.bold if active else ui.font,
                    TEXT if active else DIM, align="center")


def connection_summary(status):
    """(text, colour): where a mounted image stands with the computer."""
    if status.get("switch") == "host":
        return "Flip switch to SLAVE", ACCENT
    state = status.get("udc_state")
    if state == "configured":
        return "Connected to computer", GOOD
    if state == "suspended":
        return "Connected, computer idle", GOOD
    return "Not plugged in", ACCENT


class Home(ListScreen):
    BANNER_H = 42
    list_top = BODY_TOP + BANNER_H + 2
    list_rows = (HEIGHT - FOOTER_H - list_top) // ROW_H

    def header_right(self):
        free = self.app.status.get("free")
        return (f"{human_size(free)} free", DIM) if free is not None else ("", DIM)

    def refresh(self):
        status = self.app.status
        rows = []
        if status.get("mounted"):
            rows.append(("Unmount", "", None, "unmount"))
            rows.append(("Connection status", "", None, "status"))
            self.hints = "F/X move   Enter select   U unmount   Esc exit"
        else:
            self.hints = "F/X move   Enter select   Esc exit"
        rows.append(("My images", str(self.app.image_count), None, "images"))
        rows.append(("Download images", "", None, "catalog"))
        if not status.get("mounted") and self.app.settings.get("files_drive"):
            rows.append(("Mount files drive only", "", None, "files"))
        downloads = status.get("downloads", [])
        if downloads:
            active = [d for d in downloads if d["state"] in ACTIVE_STATES]
            label = download_label(active[0]) if active else f"{len(downloads)} finished"
            rows.append(("Downloads", label, ACCENT if active else None, "downloads"))
        rows.append(("Settings", "", None, "settings"))
        if [r[3] for r in rows] != [r[3] for r in self.rows]:
            self.index = self.top = 0   # the menu changed shape; do not leave the cursor on a different action
        self.rows = rows

    def key(self, key):
        if key == "esc":
            self.app.running = False
        elif key == "u":
            self.app.confirm_unmount()
        elif key != "left":
            super().key(key)

    def activate(self, target):
        if target == "unmount":
            self.app.confirm_unmount()
            return
        if target == "files":
            if self.app.request("mount", files_only=True) is not None:
                self.app.push(Status(self.app))
            return
        screens = {"status": Status, "images": Images, "catalog": Categories,
                   "downloads": Downloads, "settings": Settings}
        self.app.push(screens[target](self.app))

    def body(self, ui):
        status = self.app.status
        mounted = status.get("mounted")
        rect = pygame.Rect(4, BODY_TOP, WIDTH - 8, self.BANNER_H)
        pygame.draw.rect(ui.surface, PANEL, rect, border_radius=6)
        if mounted:
            pygame.draw.rect(ui.surface, GOOD, rect, 2, border_radius=6)
            label = "● MOUNTED"
            if mounted["files_drive"] and mounted["path"]:
                label += " + FILES"
            remaining = status.get("auto_unmount_in")
            if remaining is not None:
                label += f" · {max(1, round(remaining / 60))} min left"
            ui.text(label, (rect.x + 9, rect.y + 5), ui.small, GOOD)
            text, color = connection_summary(status)
            ui.text(text, (rect.right - 9, rect.y + 5), ui.small, color, align="right")
            ui.text(mounted_name(mounted), (rect.x + 9, rect.y + 20), ui.big, TEXT, width=rect.w - 18)
        else:
            ui.text("Nothing mounted", (rect.x + 9, rect.y + 5), ui.bold, DIM)
            ui.text("Choose an image to present it as a USB drive.", (rect.x + 9, rect.y + 23),
                    ui.small, DIM, width=rect.w - 18)
        super().body(ui)


SETTING_HELP = {
    "auto_unmount_minutes": (
        "Unmounts by itself once this much time has passed since you mounted, so a drive is "
        "not left presented by accident. The home screen shows the time left. It does not "
        "check whether a computer is still using the drive, so leave it off for long jobs "
        "such as installing a system."),
    "default_writable": (
        "Decides which option comes first when you mount a disk image. Read-only keeps the "
        "image exactly as it is. Writable lets the computer save changes into the image, "
        "which some live systems use to keep your files. ISO images are always read-only."),
    "default_image": (
        "The image that is mounted as soon as you open Mountable, when nothing else is "
        "mounted. Pick it from an image's options under My images. Pressing Enter here "
        "clears it."),
    "files_drive": (
        "Adds a second, small USB drive next to the image you mount, for drivers, installers "
        "or anything else you want at hand. The computer can read and write it. While nothing "
        "is mounted, the same files are in the shared folder on this device."),
    "files_drive_format": (
        "FAT32 is read by nearly everything, including boot menus and old systems, but no "
        "single file can be larger than 4 GB. exFAT has no such limit and suits modern "
        "Windows, macOS and Linux. A change only takes effect when you erase the files drive."),
    "files_drive_size_mb": (
        "How much the files drive can hold. Space on the SD card is only used as you add "
        "files, so a large drive costs nothing while it is empty. A change only takes effect "
        "when you erase the files drive."),
    "erase": (
        "Makes a new, empty files drive using the format and size chosen above. Everything "
        "on the current one is deleted, so copy anything you need out of the shared folder "
        "first. Your images are not touched."),
    "catalog": (
        "Fetches the newest list of images you can download. This also happens by itself "
        "when the device starts and once a day while it is online. Images you have already "
        "downloaded stay as they are."),
    "about": "Shows the version of Mountable and where your images and shared files are kept.",
}


class Help(Screen):
    hints = "Esc back"

    def __init__(self, app, title, message):
        super().__init__(app)
        self.title, self.message = title, message

    def key(self, key):
        if key in ("esc", "left", "enter", "h"):
            self.app.pop()

    def body(self, ui):
        ui.paragraph(self.message, (10, BODY_TOP + 4), WIDTH - 20, max_lines=9)


class Settings(ListScreen):
    title = "Settings"
    hints = "F/X move   Enter change   H help   Esc back"

    def key(self, key):
        if key == "h" and self.rows:
            label, _, _, setting = self.rows[self.index]
            self.app.push(Help(self.app, label, SETTING_HELP[setting]))
        else:
            super().key(key)

    def refresh(self):
        s = self.app.settings
        drive = self.app.status.get("files_drive")
        wanted = (s.get("files_drive_format"), s.get("files_drive_size_mb"))
        if not drive:
            actual, colour = "not created", None
        else:
            actual = f"{FORMAT_LABEL[drive['format']]} {megabytes_label(drive['size_mb'])}"
            # Format and size only take effect when the drive is created again.
            colour = None if (drive["format"], drive["size_mb"]) == wanted else ACCENT
        updated = self.app.load_catalog().get("updated", "")
        self.rows = [
            ("Auto-unmount", minutes_label(s.get("auto_unmount_minutes")), None, "auto_unmount_minutes"),
            ("Mount disk images", "writable" if s.get("default_writable") else "read-only", None,
             "default_writable"),
            ("Image mounted on open", s.get("default_image") or "none", None, "default_image"),
            ("Files drive", "on" if s.get("files_drive") else "off", None, "files_drive"),
            ("Files drive format", FORMAT_LABEL.get(s.get("files_drive_format"), ""), None,
             "files_drive_format"),
            ("Files drive size", megabytes_label(s.get("files_drive_size_mb", 0)), None,
             "files_drive_size_mb"),
            ("Erase files drive", actual if colour is None else f"now {actual}", colour, "erase"),
            ("Update image list", updated, None, "catalog"),
            ("About", __version__, None, "about"),
        ]

    def activate(self, key):
        app = self.app
        if key == "about":
            app.push(About(app))
        elif key == "catalog":
            if app.request("catalog_refresh") is not None:
                app.catalog = {}
                app.toast("Image list updated")
        elif key == "erase":
            app.push(Confirm(app, "Erase files drive",
                             "Create a new, empty files drive with the current format and size? "
                             "Everything on it is erased.", self.erase, yes="Erase"))
        elif key == "default_image":
            if not app.settings.get("default_image"):
                app.toast("Choose one from an image's options")
            elif app.request("set", key=key, value="") is not None:
                app.toast("No image mounts on open")
        else:
            choices = CHOICES[key]
            value = choices[(choices.index(app.settings[key]) + 1) % len(choices)]
            if app.request("set", key=key, value=value) is not None and key.startswith("files_drive"):
                if key == "files_drive" and app.status.get("mounted"):
                    app.toast("Applies the next time you mount")

    def erase(self):
        if self.app.request("drive_create", timeout=120) is not None:
            self.app.toast("Files drive erased")


class About(Screen):
    title = "About"
    hints = "Esc back"

    def body(self, ui):
        status = self.app.status
        ui.text(f"Mountable {__version__}", (10, BODY_TOP + 6), ui.big)
        y = ui.paragraph("Presents disk images over USB so a computer can boot from them.",
                         (10, BODY_TOP + 30), WIDTH - 20, color=DIM)
        ui.text("Images:", (10, y + 6), ui.small, DIM)
        ui.text(status.get("images_dir", ""), (70, y + 5), ui.font, TEXT, width=WIDTH - 80)
        ui.text("Files drive:", (10, y + 24), ui.small, DIM)
        ui.text(status.get("shared_dir", ""), (70, y + 23), ui.font, TEXT, width=WIDTH - 80)
        if "free" in status:
            ui.text(f"{human_size(status['free'])} free", (10, y + 42), ui.small, DIM)


class Status(Screen):
    """Shows the mounted image and walks the user through connecting it."""

    title = "USB drive"
    animated = True

    def key(self, key):
        mounted = self.app.status.get("mounted")
        if key in ("u", "enter") and mounted:
            self.app.confirm_unmount(then=self.app.pop)
        elif key in ("esc", "left"):
            self.app.pop()

    def draw(self, ui):
        mounted = self.app.status.get("mounted")
        self.hints = "U unmount   Esc back (stays mounted)" if mounted else "Esc back"
        super().draw(ui)

    def arrow(self, ui, left):
        """A flashing arrow at the screen edge next to the part to operate."""
        if int(time.monotonic() * 2.5) % 2:
            return
        y = HEIGHT // 2 + 4
        if left:
            points = [(6, y), (34, y - 22), (34, y - 9), (58, y - 9), (58, y + 9), (34, y + 9), (34, y + 22)]
        else:
            points = [(WIDTH - 6, y), (WIDTH - 34, y - 22), (WIDTH - 34, y - 9), (WIDTH - 58, y - 9),
                      (WIDTH - 58, y + 9), (WIDTH - 34, y + 9), (WIDTH - 34, y + 22)]
        pygame.draw.polygon(ui.surface, ACCENT, points)

    def body(self, ui):
        status = self.app.status
        mounted = status.get("mounted")
        if not mounted:
            ui.text("Nothing is mounted", (WIDTH // 2, BODY_TOP + 44), ui.big, DIM, align="center")
            return
        kind = "CD-ROM" if mounted["mode"] == "cdrom" else "USB disk"
        access = "writable" if mounted["writable"] else "read-only"
        if not mounted["path"]:
            access = "writable"
        elif mounted["files_drive"]:
            access += " · + files drive"
        ui.text(mounted_name(mounted), (WIDTH // 2, BODY_TOP + 4), ui.bold, TEXT,
                width=WIDTH - 20, align="center")
        ui.text(f"{kind} · {access}", (WIDTH // 2, BODY_TOP + 20), ui.small, DIM, align="center")

        top = BODY_TOP + 44
        state = status.get("udc_state")
        if status.get("switch") == "host":
            self.arrow(ui, left=True)
            ui.text("Flip the switch", (190, top), ui.big, ACCENT, align="center")
            ui.paragraph("Set the Host/Slave switch on the left side to SLAVE.",
                         (190, top + 24), 190, max_lines=3, align="center")
        elif state == "configured":
            ui.text("✔ Connected", (WIDTH // 2, top), ui.big, GOOD, align="center")
            ui.paragraph("The computer sees the drive. Choose it in the boot menu.",
                         (WIDTH // 2, top + 24), 260, color=DIM, max_lines=3, align="center")
        elif state == "suspended":
            ui.text("Connected, idle", (WIDTH // 2, top), ui.big, GOOD, align="center")
            ui.paragraph("The computer is off or asleep. Power it on and choose the drive in the boot menu.",
                         (WIDTH // 2, top + 24), 270, color=DIM, max_lines=3, align="center")
        else:
            self.arrow(ui, left=False)
            ui.text("Plug in USB", (130, top), ui.big, ACCENT, align="center")
            ui.paragraph("Connect the right-hand USB-C port to the computer.",
                         (130, top + 24), 190, max_lines=3, align="center")


class Images(ListScreen):
    title = "My images"
    hints = "Enter options   D delete   Esc back"

    def key(self, key):
        if key == "d" and self.rows:
            image = self.rows[self.index][3]
            self.app.push(Confirm(self.app, "Delete", f"Delete {image['name']}? This cannot be undone.",
                                  lambda: self.delete(image), yes="Delete"))
        else:
            super().key(key)

    def delete(self, image):
        if self.app.request("delete", name=image["name"]) is not None:
            self.app.catalog = {}   # its catalog entry is no longer installed
            self.app.toast("Deleted")
            self.refresh()

    def refresh(self):
        reply = self.app.request("images")
        if reply is None:
            return
        self.images = reply["images"]
        self.app.image_count = len(self.images)
        mounted = (self.app.status.get("mounted") or {}).get("path")
        self.rows = [
            (("● " if i["path"] == mounted else "") + i["name"], human_size(i["size"]),
             GOOD if i["path"] == mounted else None, i)
            for i in self.images
        ]
        self.empty = (f"No images yet. Use Download images, or copy files to "
                      f"{self.app.status.get('images_dir', '')}")

    def activate(self, image):
        self.app.push(ImageActions(self.app, image))


class ImageActions(ListScreen):
    def __init__(self, app, image):
        super().__init__(app)
        self.image = image
        self.title = image["name"]

    def refresh(self):
        image = self.image
        mounted = (self.app.status.get("mounted") or {}).get("path") == image["path"]
        if mounted:
            self.rows = [("Show connection status", "", None, "status"), ("Unmount", "", None, "unmount")]
            return
        other = "cdrom" if image["mode"] == "disk" else "disk"
        label = {"disk": "USB disk", "cdrom": "CD-ROM"}
        read_only = (f"Mount as {label[image['mode']]}", "read-only", None, (image["mode"], False))
        writable = ("Mount writable", "changes are saved", None, ("disk", True))
        if image["kind"] == "iso":
            rows = [read_only]
        elif self.app.settings.get("default_writable"):
            rows = [writable, read_only]
        else:
            rows = [read_only, writable]
        rows.append((f"Mount as {label[other]}", "read-only", None, (other, False)))
        if self.app.settings.get("default_image") == image["name"]:
            rows.append(("Stop mounting when the app opens", "default", GOOD, "undefault"))
        else:
            rows.append(("Mount when the app opens", "", None, "default"))
        rows.append(("Delete", human_size(image["size"]), None, "delete"))
        self.rows = rows

    def activate(self, action):
        app, image = self.app, self.image
        if action == "status":
            app.push(Status(app))
        elif action == "unmount":
            app.confirm_unmount(then=app.pop)
        elif action == "delete":
            app.push(Confirm(app, "Delete", f"Delete {image['name']}? This cannot be undone.",
                             self.delete, yes="Delete"))
        elif action in ("default", "undefault"):
            value = image["name"] if action == "default" else ""
            if app.request("set", key="default_image", value=value) is not None:
                app.toast("Will mount when the app opens" if value else "No longer the default")
        else:
            mode, writable = action
            current = app.status.get("mounted")
            if current:
                name = mounted_name(current)
                app.push(Confirm(app, "Replace", f"Unmount {name} and mount this image instead?",
                                 lambda: self.mount(mode, writable, replace=True), yes="Replace"))
            else:
                self.mount(mode, writable)

    def mount(self, mode, writable, replace=False):
        app = self.app
        if replace and app.request("unmount") is None:
            return
        if app.request("mount", name=self.image["name"], mode=mode, writable=writable) is not None:
            app.pop()
            app.push(Status(app))

    def delete(self):
        if self.app.request("delete", name=self.image["name"]) is not None:
            self.app.catalog = {}   # its catalog entry is no longer installed
            self.app.toast("Deleted")
            self.app.pop()


class Categories(ListScreen):
    title = "Download images"

    def refresh(self):
        catalog = self.app.load_catalog()
        counts = {}
        for entry in catalog.get("images", []):
            counts[entry["category"]] = counts.get(entry["category"], 0) + 1
        self.rows = [(c["name"], str(counts.get(c["id"], 0)), None, c) for c in catalog.get("categories", [])]
        self.can_refresh = catalog.get("can_refresh", False)
        self.hints = "Enter open   R update list   Esc back" if self.can_refresh else ListScreen.hints
        self.empty = "The image catalog is empty."

    def header_right(self):
        updated = self.app.catalog.get("updated", "")
        return (f"list {updated}", DIM) if updated else ("", DIM)

    def key(self, key):
        if key == "r" and self.can_refresh:
            if self.app.request("catalog_refresh") is not None:
                self.app.catalog = {}
                self.app.toast("Image list updated")
        else:
            super().key(key)

    def activate(self, category):
        self.app.push(CatalogList(self.app, category))


def entry_state(app, entry):
    """(label, colour) describing an entry: downloading, installed or its size."""
    for d in app.status.get("downloads", []):
        if d["id"] == entry["id"] and d["state"] != "done":
            return download_label(d), BAD if d["state"] == "error" else ACCENT
    if entry.get("installed"):
        return "✔ downloaded", GOOD
    return human_size(entry["size"]), None


class CatalogList(ListScreen):
    """A category's images. Versions of one system (a family) share a row that
    opens a list of just those versions."""

    def __init__(self, app, category, family=None):
        super().__init__(app)
        self.category = category
        self.family = family
        self.title = category["name"]

    def refresh(self):
        entries = [e for e in self.app.load_catalog().get("images", []) if e["category"] == self.category["id"]]
        if self.family:
            entries = [e for e in entries if e.get("family") == self.family]
            if entries:
                self.title = entries[0]["name"]
            self.rows = [(e.get("version", ""), *entry_state(self.app, e), e) for e in entries]
            return
        families = {}
        for e in entries:
            if e.get("family"):
                families.setdefault(e["family"], []).append(e)
        rows = []
        for e in entries:
            versions = families.get(e.get("family"), [])
            if len(versions) < 2:
                rows.append((f"{e['name']}  {e.get('version', '')}", *entry_state(self.app, e), e))
            elif versions[0] is e:   # one row per family, at its newest version
                rows.append((e["name"], *family_state(self.app, versions), e["family"]))
        self.rows = rows

    def activate(self, target):
        if isinstance(target, str):
            self.app.push(CatalogList(self.app, self.category, family=target))
        else:
            self.app.push(Entry(self.app, target["id"]))


def family_state(app, versions):
    """(label, colour) for a family row: activity first, else how many versions."""
    states = [entry_state(app, e) for e in versions]
    for label, color in states:
        if color in (ACCENT, BAD):
            return label, color
    downloaded = sum(1 for _, color in states if color == GOOD)
    if downloaded:
        return f"✔ {downloaded} of {len(versions)}", GOOD
    return f"{len(versions)} versions ›", None


class Entry(Screen):
    def __init__(self, app, entry_id):
        super().__init__(app)
        self.entry_id = entry_id
        self.entry = None
        self.download = None

    def refresh(self):
        for entry in self.app.load_catalog().get("images", []):
            if entry["id"] == self.entry_id:
                self.entry = entry
        self.download = next((d for d in self.app.status.get("downloads", [])
                              if d["id"] == self.entry_id and d["state"] != "done"), None)
        self.animated = bool(self.download)
        if self.entry:
            self.title = self.entry["name"]
        if self.download and self.download["state"] in ACTIVE_STATES:
            self.hints = "Enter cancel download   Esc back"
        elif self.entry and self.entry.get("installed"):
            self.hints = "Enter mount or delete   Esc back"
        else:
            self.hints = "Enter download   Esc back"

    def key(self, key):
        app, entry = self.app, self.entry
        if key in ("esc", "left") or not entry:
            app.pop()
        elif key != "enter":
            return
        elif self.download and self.download["state"] in ACTIVE_STATES:
            app.push(Confirm(app, "Cancel download", f"Stop downloading {entry['name']}?",
                             lambda: app.request("cancel", id=entry["id"]), yes="Stop"))
        else:
            if entry.get("installed"):
                path = os.path.join(app.status.get("images_dir", ""), entry["file"])
                image = {"name": entry["file"], "path": path, "mode": entry.get("mode", "disk"),
                         "kind": entry["file"].rsplit(".", 1)[-1].lower(), "size": entry["size"]}
                app.push(ImageActions(app, image))
            elif app.request("download", id=entry["id"]) is not None:
                app.catalog = {}
                app.toast("Download started")

    def body(self, ui):
        entry = self.entry
        if not entry:
            return
        ui.text(f"{entry['name']} {entry.get('version', '')}", (10, BODY_TOP + 2), ui.big, TEXT, width=WIDTH - 20)
        kind = "CD-ROM image" if entry.get("mode") == "cdrom" else "USB disk image"
        ui.text(f"{entry.get('arch', '')} · {human_size(entry['size'])} · {kind}",
                (10, BODY_TOP + 22), ui.small, DIM, width=WIDTH - 20)
        ui.paragraph(entry.get("description", ""), (10, BODY_TOP + 40), WIDTH - 20, max_lines=3)

        y = HEIGHT - FOOTER_H - 34
        d = self.download
        if d and d["state"] == "error":
            ui.paragraph(d["error"], (10, y), WIDTH - 20, ui.small, BAD, max_lines=2)
        elif d:
            ui.bar((10, y + 16, WIDTH - 20, 8), d["received"] / max(d["total"], 1))
            done = f"{human_size(d['received'])} of {human_size(d['total'])}"
            label = {"verifying": "Verifying checksum…", "unpacking": "Unpacking…",
                     "queued": "Waiting for another download…"}.get(d["state"], done)
            ui.text(label, (10, y), ui.small, TEXT)
            if d["state"] == "downloading" and d["speed"]:
                ui.text(f"{human_size(d['speed'])}/s", (WIDTH - 10, y), ui.small, DIM, align="right")
        elif entry.get("installed"):
            ui.text("✔ Downloaded and verified", (10, y + 10), ui.font, GOOD)
        elif entry.get("space_needed", 0) > self.app.status.get("free", entry["size"] * 100):
            ui.text("Not enough free space", (10, y + 10), ui.font, BAD)


class Downloads(ListScreen):
    title = "Downloads"
    hints = "Enter open   D clear finished   Esc back"
    empty = "No downloads."

    def refresh(self):
        self.rows = [
            (d["name"], download_label(d),
             {"error": BAD, "done": GOOD}.get(d["state"], ACCENT), d)
            for d in self.app.status.get("downloads", [])
        ]

    def key(self, key):
        if key == "d":
            for d in self.app.status.get("downloads", []):
                if d["state"] not in ACTIVE_STATES:
                    self.app.request("dismiss", id=d["id"])
            self.app.poll()
        else:
            super().key(key)

    def activate(self, download):
        self.app.push(Entry(self.app, download["id"]))


class App:
    POLL_INTERVAL = 1.0

    def __init__(self, screen, keyboard):
        self.ui = UI()
        self.screen = screen
        self.keyboard = keyboard
        self.status = {}
        self.catalog = {}
        self.image_count = 0
        self.running = True
        self.service_down = False
        self._toast = ("", 0, TEXT)
        self.stack = []
        self.poll()
        try:
            self.image_count = len(call("images")["images"])
        except ServiceError:
            pass
        self.push(Home(self))
        self.mount_default_image()

    @property
    def settings(self):
        return self.status.get("settings", {})

    def mount_default_image(self):
        """Mount the image chosen in settings when the app opens with nothing mounted."""
        name = self.settings.get("default_image")
        if not name or self.status.get("mounted") or self.service_down:
            return
        writable = bool(self.settings.get("default_writable")) and not name.lower().endswith(".iso")
        if self.request("mount", name=name, writable=writable) is not None:
            self.push(Status(self))

    def push(self, screen):
        self.stack.append(screen)
        screen.refresh()

    def pop(self):
        if len(self.stack) > 1:
            self.stack.pop()
            self.stack[-1].refresh()

    def confirm_unmount(self, then=None):
        """Ask before unmounting; warn harder when a computer is using the drive."""
        mounted = self.status.get("mounted")
        if not mounted:
            return
        name = mounted_name(mounted)
        if self.status.get("switch") != "host" and self.status.get("udc_state") == "configured":
            message = f"A computer is using {name}. Unmounting now can crash it or lose its data. Unmount anyway?"
        else:
            message = f"Unmount {name}?"

        def unmount():
            if self.request("unmount") is not None:
                self.toast("Unmounted")
                if then:
                    then()

        self.push(Confirm(self, "Unmount", message, unmount, yes="Unmount"))

    def toast(self, message, error=False):
        self._toast = (message, time.monotonic() + (4 if error else 2), BAD if error else GOOD)

    def request(self, cmd, timeout=30, **params):
        """Call the service; on failure show the error and return None."""
        try:
            reply = call(cmd, timeout=timeout, **params)
        except ServiceError as e:
            self.toast(str(e), error=True)
            return None
        self.poll()
        return reply

    def load_catalog(self):
        if not self.catalog:
            try:
                self.catalog = call("catalog")
            except ServiceError as e:
                self.toast(str(e), error=True)
        return self.catalog

    def poll(self):
        try:
            previous = {d["id"]: d["state"] for d in self.status.get("downloads", [])}
            self.status = call("status", timeout=5)
            self.service_down = False
            for d in self.status.get("downloads", []):
                if d["state"] == "done" and previous.get(d["id"], "done") != "done":
                    self.catalog = {}   # installed flags changed
                    self.image_count += 1
                    self.toast(f"{d['name']} downloaded")
        except ServiceError:
            self.service_down = True

    def draw(self):
        ui = self.ui
        self.stack[-1].draw(ui)
        if self.service_down:
            pygame.draw.rect(ui.surface, BAD, (0, HEIGHT - FOOTER_H, WIDTH, FOOTER_H))
            ui.text("Mountable service is not running", (6, HEIGHT - FOOTER_H + 1), ui.small, BG)
        message, until, color = self._toast
        if message and time.monotonic() < until:
            width = min(WIDTH - 20, ui.font.size(message)[0] + 20)
            rect = pygame.Rect((WIDTH - width) // 2, HEIGHT - FOOTER_H - 26, width, 22)
            pygame.draw.rect(ui.surface, PANEL, rect, border_radius=6)
            pygame.draw.rect(ui.surface, color, rect, 1, border_radius=6)
            ui.text(message, (rect.centerx, rect.y + 4), ui.font, color, width=width - 12, align="center")
        self.screen.show(ui.surface)

    def run(self):
        last_poll = 0.0
        while self.running:
            self.draw()
            top = self.stack[-1]
            busy = top.animated or time.monotonic() < self._toast[1]
            for key in self.keyboard.read(0.2 if busy else self.POLL_INTERVAL):
                self.stack[-1].key(key)
                self.stack[-1].refresh()
            if getattr(self.keyboard, "finished", False):
                break
            if time.monotonic() - last_poll >= self.POLL_INTERVAL:
                last_poll = time.monotonic()
                self.poll()
                self.stack[-1].refresh()
        self.draw()


def main():
    parser = argparse.ArgumentParser(prog="mountable", description="Mountable user interface")
    parser.add_argument("--keys", help="comma-separated keys to replay, then exit (for testing)")
    parser.add_argument("--image", help="write the last frame to this file instead of the screen")
    args = parser.parse_args()

    from . import keys
    screen = display.ImageFile(args.image) if args.image else display.Framebuffer()
    keyboard = keys.ScriptedKeys(args.keys.split(",")) if args.keys is not None else keys.Keyboard()
    App(screen, keyboard).run()


if __name__ == "__main__":
    main()
