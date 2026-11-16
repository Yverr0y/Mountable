"""Output to the built-in LCD through the Linux framebuffer."""

import os
from pathlib import Path

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

WIDTH, HEIGHT = 320, 170


def new_surface():
    # 16 bits per pixel in pygame is RGB565, the panel's native format.
    return pygame.Surface((WIDTH, HEIGHT), depth=16)


class Framebuffer:
    def __init__(self):
        device = next(p for p in ("/dev/fb_lcd", "/dev/fb0") if os.path.exists(p))
        sysfs = Path("/sys/class/graphics") / os.path.basename(os.path.realpath(device))
        size = (sysfs / "virtual_size").read_text().strip()
        depth = (sysfs / "bits_per_pixel").read_text().strip()
        if size != f"{WIDTH},{HEIGHT}" or depth != "16":
            raise RuntimeError(f"unsupported display: {size} at {depth} bpp")
        self._fd = os.open(device, os.O_WRONLY)

    def show(self, surface):
        os.pwrite(self._fd, surface.get_buffer().raw, 0)


class ImageFile:
    """Saves each frame to an image file instead of the screen, for testing."""

    def __init__(self, path):
        self._path = path

    def show(self, surface):
        pygame.image.save(surface, self._path)
