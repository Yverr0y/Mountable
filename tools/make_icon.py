#!/usr/bin/env python3
"""Draws the app icon as a PNG.

Usage: make_icon.py OUTPUT.png [SIZE] [--square]

The launcher icon is 100 pixels with rounded corners (the default). The store
listing wants a larger one without rounded corners: 256 --square.
"""

import os
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

args = [a for a in sys.argv[1:] if a != "--square"]
SIZE = int(args[1]) if len(args) > 1 else 100
ROUNDED = "--square" not in sys.argv
# Shapes are drawn several times larger and scaled down, which smooths edges.
OVERSAMPLE = 4
BG = (22, 26, 36)
AMBER = (255, 176, 46)
DARK = (14, 16, 22)


def s(value):
    """Scale a measurement from the 100-pixel design."""
    return round(value * SIZE * OVERSAMPLE / 100)


def rect(color, x, y, w, h, radius=0):
    pygame.draw.rect(icon, color, (s(x), s(y), s(w), s(h)), border_radius=s(radius))


icon = pygame.Surface((SIZE * OVERSAMPLE, SIZE * OVERSAMPLE), pygame.SRCALPHA)
rect(BG, 0, 0, 100, 100, 22 if ROUNDED else 0)

# A USB stick: plug on top, body below, with a disc on the body.
rect(AMBER, 38, 12, 24, 22, 3)
rect(DARK, 43, 18, 5, 7)
rect(DARK, 52, 18, 5, 7)
rect(AMBER, 28, 32, 44, 56, 9)
for color, radius in ((DARK, 15), (AMBER, 9), (DARK, 3)):
    pygame.draw.circle(icon, color, (s(50), s(60)), s(radius))

pygame.image.save(pygame.transform.smoothscale(icon, (SIZE, SIZE)), args[0])
