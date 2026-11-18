#!/bin/sh
# Builds the Mountable package from this checkout and installs it on a
# Cardputer Zero. Run on the device: sudo ./install.sh [full|store]
# "full" (the default) runs the service all the time; "store" is the build
# published in the Cardputer Zero store, which asks for the device password
# when the app opens. See packaging/build-deb.sh.
set -eu

[ "$(id -u)" -eq 0 ] || { echo "run as root: sudo $0" >&2; exit 1; }
cd "$(dirname "$0")"

# Earlier versions of this script copied files into place without a package.
if [ -d /opt/mountable ]; then
    systemctl disable --now mountable.service >/dev/null 2>&1 || true
    rm -rf /opt/mountable
    rm -f /etc/systemd/system/mountable.service
fi

OUTDIR=$(mktemp -d)
trap 'rm -rf "$OUTDIR"' EXIT
chmod 755 "$OUTDIR"
DEB=$(OUTDIR=$OUTDIR packaging/build-deb.sh "${1:-full}")
apt-get install -y --reinstall --allow-downgrades -o Dpkg::Options::=--force-confold "$DEB"
echo "Mountable installed. Images go in /srv/mountable/images."
