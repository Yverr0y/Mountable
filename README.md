# Mountable

Turns a Cardputer Zero into a USB drive that can present any disk image. Pick
an ISO or disk image on the device, plug it into a computer, and boot from it.

- Mount ISOs and raw disk images as a USB disk or CD-ROM, read-only or writable
- Download images from a built-in catalog, verified by SHA-256
- Mounts and downloads keep running after you leave the app
- On-screen guidance when the Host/Slave switch is in the wrong position

## Install

On the Cardputer Zero, from a checkout of this repository:

    sudo ./install.sh

Mountable then appears in the app launcher.

## Use

Navigate with `F` (up), `X` (down), `Z` (left) and `C` (right), or the arrow
keys. `Enter` selects and `Esc` goes back.

Your own images go in `/srv/mountable/images`.

While an image is mounted the device's adb connection is paused; it comes back
when you unmount.

## Settings

Settings are in the app's menu:

- Auto-unmount after a set time
- Mount disk images read-only or writable by default
- An image to mount whenever the app opens (set from an image's options)
- A files drive: an extra FAT32 or exFAT USB drive presented next to the
  mounted image, or on its own, for carrying drivers and other files

While the files drive is not being presented over USB, its contents are in
`/srv/mountable/shared`. Copy files there and they are on the drive at the
next mount; files a computer saved to the drive appear there after unmounting.

## Catalog

The download list is `catalog/catalog.json`. Devices fetch the published copy
when they start and once a day, and from Settings on request, so the list can
change without an app update. The URL is `catalog_url` in
`/etc/mountable/config.json`; it must be reachable without a login.

Check the catalog after editing it:

    python3 tools/check_catalog.py --online
