#!/bin/sh
# Builds the Debian package for the Cardputer Zero.
# Usage: packaging/build-deb.sh [store|full]
#
#   store  (default) no system service: the app asks for the device password
#          when it opens and starts the service for as long as it is needed.
#          This is the build the Cardputer Zero store accepts.
#   full   also installs the service to run all the time as root, so the app
#          never asks for a password.
#
# Writes dist/mountable_<version>_arm64.deb, or mountable-full_<version>_arm64.deb
# for the full build, and prints its path. Both are the package "mountable"
# at the same version. Set OUTDIR to change the directory. Needs dpkg-deb.
set -eu
cd "$(dirname "$0")/.."

PACKAGE=mountable
VERSION=$(sed -n 's/^__version__ = "\(.*\)"$/\1/p' mountable/__init__.py)
VARIANT=${1:-store}
case $VARIANT in
    store) FILE=$PACKAGE ;;
    full) FILE=$PACKAGE-full ;;
    *) echo "usage: $0 [store|full]" >&2; exit 1 ;;
esac
OUTDIR=${OUTDIR:-dist}
[ -n "$VERSION" ] || { echo "could not read the version from mountable/__init__.py" >&2; exit 1; }

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
chmod 755 "$STAGE"

LIB=$STAGE/usr/lib/$PACKAGE
LAUNCHER=$STAGE/usr/share/APPLaunch

install -d "$LIB/mountable/ui" "$LIB/catalog"
install -m 644 mountable/*.py "$LIB/mountable/"
install -m 644 mountable/ui/*.py "$LIB/mountable/ui/"
install -m 644 catalog/catalog.json "$LIB/catalog/"

install -m 755 packaging/start-service "$LIB/start-service"
install -D -m 755 packaging/mountable "$STAGE/usr/bin/mountable"
if [ "$VARIANT" = full ]; then
    install -D -m 644 packaging/mountable.service "$STAGE/usr/lib/systemd/system/mountable.service"
fi
install -D -m 644 packaging/mountable.desktop "$LAUNCHER/applications/mountable.desktop"
install -D -m 644 packaging/mountable.png "$LAUNCHER/share/images/mountable.png"
install -D -m 644 packaging/debian/copyright "$STAGE/usr/share/doc/$PACKAGE/copyright"

# Settings start empty; the app fills the file in as they are changed.
install -d "$STAGE/etc/mountable"
echo '{}' > "$STAGE/etc/mountable/config.json"
chmod 644 "$STAGE/etc/mountable/config.json"

install -d "$STAGE/DEBIAN"
install -m 755 packaging/debian/postinst packaging/debian/prerm packaging/debian/postrm "$STAGE/DEBIAN/"
echo /etc/mountable/config.json > "$STAGE/DEBIAN/conffiles"
SIZE=$(du -sk --exclude=DEBIAN "$STAGE" | cut -f1)
cat > "$STAGE/DEBIAN/control" <<CONTROL
Package: $PACKAGE
Version: $VERSION
Architecture: arm64
Maintainer: Pedro Santos <8346634+s0liton@users.noreply.github.com>
Section: utils
Priority: optional
Installed-Size: $SIZE
Depends: python3 (>= 3.9), python3-pygame, python3-evdev, fonts-dejavu-core, dosfstools, kmod, systemd, sudo
Recommends: exfatprogs
Homepage: https://github.com/s0liton/Mountable
Description: Present disk images over USB as a bootable drive
 Turns a Cardputer Zero into a USB drive that can present any ISO or disk
 image, so a computer can boot from it. Images can be downloaded on the
 device from a built-in catalog and are verified by SHA-256.
CONTROL

mkdir -p "$OUTDIR"
DEB=$OUTDIR/${FILE}_${VERSION}_arm64.deb
dpkg-deb --root-owner-group -Zxz --build "$STAGE" "$DEB" >/dev/null
echo "$DEB"
