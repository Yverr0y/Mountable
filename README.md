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

## Catalog

The download list is `catalog/catalog.json`. To have devices pick up catalog
changes without an app update, publish that file and set its URL as
`catalog_url` in `/etc/mountable/config.json`.

Check the catalog after editing it:

    python3 tools/check_catalog.py --online
