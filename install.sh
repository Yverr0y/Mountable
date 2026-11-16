#!/bin/sh
# Installs or updates Mountable on a Cardputer Zero. Run from the repository
# root on the device: sudo ./install.sh
set -eu

[ "$(id -u)" -eq 0 ] || { echo "run as root: sudo $0" >&2; exit 1; }
cd "$(dirname "$0")"

PREFIX=/opt/mountable
LAUNCHER=/usr/share/APPLaunch

for module in pygame evdev; do
    PYGAME_HIDE_SUPPORT_PROMPT=1 python3 -c "import $module" >/dev/null 2>&1 || {
        echo "missing Python module '$module': apt install python3-$module" >&2; exit 1; }
done

rm -rf "$PREFIX"
install -d "$PREFIX" /etc/mountable /srv/mountable/images /var/cache/mountable
cp -r mountable catalog "$PREFIX/"
find "$PREFIX" -name __pycache__ -prune -exec rm -rf {} +
python3 -m compileall -q "$PREFIX/mountable"

install -m 755 packaging/mountable /usr/bin/mountable
install -m 644 packaging/mountable.service /etc/systemd/system/mountable.service
[ -e /etc/mountable/config.json ] || echo '{}' > /etc/mountable/config.json

if [ -d "$LAUNCHER/applications" ]; then
    install -m 644 packaging/mountable.png "$LAUNCHER/share/images/mountable.png"
    install -m 644 packaging/mountable.desktop "$LAUNCHER/applications/mountable.desktop"
fi

systemctl daemon-reload
systemctl enable --quiet mountable.service
systemctl restart mountable.service
echo "Mountable installed. Images go in /srv/mountable/images."
