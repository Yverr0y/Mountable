#!/usr/bin/env python3
"""Draws the launcher icon (100x100 PNG). Usage: make_icon.py OUTPUT.png"""

import os
import sys

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
import pygame  # noqa: E402

SIZE = 100
BG = (22, 26, 36)
AMBER = (255, 176, 46)
DARK = (14, 16, 22)

icon = pygame.Surface((SIZE, SIZE), pygame.SRCALPHA)
pygame.draw.rect(icon, BG, (0, 0, SIZE, SIZE), border_radius=22)

# A USB stick: plug on top, body below, with a disc on the body.
pygame.draw.rect(icon, AMBER, (38, 12, 24, 22), border_radius=3)
pygame.draw.rect(icon, DARK, (43, 18, 5, 7))
pygame.draw.rect(icon, DARK, (52, 18, 5, 7))
pygame.draw.rect(icon, AMBER, (28, 32, 44, 56), border_radius=9)
pygame.draw.circle(icon, DARK, (50, 60), 15)
pygame.draw.circle(icon, AMBER, (50, 60), 9)
pygame.draw.circle(icon, DARK, (50, 60), 3)

pygame.image.save(icon, sys.argv[1])
