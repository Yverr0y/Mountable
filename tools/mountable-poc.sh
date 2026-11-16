#!/usr/bin/env bash
#
# mountable-poc.sh - expose a disk image over USB as a mass-storage device.
#
# Proof of concept for the Cardputer Zero (Raspberry Pi CM0). Run on the
# device as root, with the Host/Slave switch set to Slave and the cable in
# the OTG-capable USB-C port.
#
#   mountable-poc.sh fetch-alpine [dir]       download a small bootable test ISO
#   mountable-poc.sh mount <image> [--cdrom] [--rw]
#   mountable-poc.sh status
#   mountable-poc.sh unmount
#
# By default the image is presented as a read-only USB flash drive, which is
# what hybrid ISOs (most Linux distributions) expect. Use --cdrom for plain
# ISO9660 images that are not hybrid, and --rw for writable disk images.

set -euo pipefail

CONFIGFS=/sys/kernel/config
GADGET=$CONFIGFS/usb_gadget/mountable
FUNC=$GADGET/functions/mass_storage.usb0
CONF=$GADGET/configs/c.1
LUN=$FUNC/lun.0
PAUSED=/run/mountable-paused-gadgets
WAIT_SECONDS=60
BOUND=0    # set once the image is live, so a failed mount cleans up on exit

die() { echo "error: $*" >&2; exit 1; }
need_root() { [ "$(id -u)" -eq 0 ] || die "must be run as root"; }

find_udc() {
    local d
    for d in /sys/class/udc/*; do
        [ -e "$d" ] && { basename "$d"; return 0; }
    done
    return 1
}

udc_attr() { cat "/sys/class/udc/$1/$2" 2>/dev/null || echo unknown; }

# The OS image runs its own gadget (adb) on the controller, managed by these
# services. Only one gadget can be bound at a time, so they are stopped while
# an image is mounted and started again on unmount. Any other gadget found
# bound to the controller is unbound and rebound the same way.
VENDOR_UNITS="cardputer-adb-hotplug.service adbd.service"

pause_other_gadgets() {
    local udc=$1 unit d
    for unit in $VENDOR_UNITS; do
        systemctl is-active --quiet "$unit" 2>/dev/null || continue
        echo "unit $unit" >> "$PAUSED"
        systemctl stop "$unit"
        echo "Stopped $unit."
    done
    for d in "$CONFIGFS"/usb_gadget/*; do
        [ -d "$d" ] && [ "$d" != "$GADGET" ] || continue
        [ "$(cat "$d/UDC" 2>/dev/null)" = "$udc" ] || continue
        echo "gadget $(basename "$d")" >> "$PAUSED"
        echo "" > "$d/UDC"
        echo "Paused existing USB gadget '$(basename "$d")'."
    done
}

resume_other_gadgets() {
    local udc kind name
    [ -f "$PAUSED" ] || return 0
    udc=$(find_udc) || return 0
    # Restore in reverse order of pausing.
    while read -r kind name; do
        case $kind in
            unit)   systemctl start "$name" 2>/dev/null ;;
            gadget) echo "$udc" > "$CONFIGFS/usb_gadget/$name/UDC" 2>/dev/null ;;
        esac && echo "Resumed $name." \
             || echo "warning: could not resume $name; a reboot will restore it." >&2
    done < <(tac "$PAUSED")
    rm -f "$PAUSED"
}

teardown() {
    if [ -d "$GADGET" ]; then
        echo "" > "$GADGET/UDC" 2>/dev/null || true
        rm -f "$CONF/mass_storage.usb0"
        rmdir "$CONF/strings/0x409" "$CONF" "$FUNC" \
              "$GADGET/strings/0x409" "$GADGET" 2>/dev/null || true
        [ ! -d "$GADGET" ] || die "could not fully remove gadget at $GADGET"
    fi
    resume_other_gadgets
}

# A hybrid ISO carries an MBR boot signature, so it can be served as a disk.
has_mbr_signature() {
    [ "$(od -An -tx1 -j510 -N2 "$1" | tr -d ' \n')" = "55aa" ]
}

wait_for_host() {
    local udc=$1 i state
    echo "Waiting up to ${WAIT_SECONDS}s for a host to connect..."
    for ((i = 0; i < WAIT_SECONDS; i++)); do
        state=$(udc_attr "$udc" state)
        if [ "$state" = "configured" ]; then
            echo "Host connected ($(udc_attr "$udc" current_speed))."
            return 0
        fi
        sleep 1
    done
    cat <<EOF
No host has connected yet (controller state: $state).
The image stays mounted. Check that:
  - the Host/Slave switch is set to Slave
  - the cable is in the OTG-capable USB-C port
  - the cable carries data, not just power
EOF
}

cmd_mount() {
    local image="" cdrom=0 ro=1 arg udc serial
    for arg in "$@"; do
        case $arg in
            --cdrom) cdrom=1 ;;
            --rw)    ro=0 ;;
            -*)      die "unknown option: $arg" ;;
            *)       [ -z "$image" ] || die "only one image can be mounted"
                     image=$arg ;;
        esac
    done
    [ -n "$image" ] || die "usage: mount <image> [--cdrom] [--rw]"
    need_root
    [ -f "$image" ] || die "no such file: $image"
    image=$(realpath "$image")
    [ "$cdrom" -eq 0 ] || ro=1

    [ ! -d "$GADGET" ] || die "an image is already mounted; run 'unmount' first"

    modprobe libcomposite 2>/dev/null || true
    mountpoint -q "$CONFIGFS" || mount -t configfs none "$CONFIGFS"
    [ -d "$CONFIGFS/usb_gadget" ] || die "kernel has no USB gadget configfs support"

    udc=$(find_udc) || die "no USB device controller found.
Device mode is probably not enabled: add 'dtoverlay=dwc2' to
/boot/firmware/config.txt, reboot, and try again."

    if [ "$cdrom" -eq 0 ] && ! has_mbr_signature "$image"; then
        echo "warning: $image has no MBR boot signature; it is probably not a" >&2
        echo "         hybrid image and may need --cdrom to boot." >&2
    fi

    serial=$(head -c 16 /etc/machine-id 2>/dev/null || echo 0000000000000001)

    trap '[ "$BOUND" -eq 1 ] || teardown' EXIT

    mkdir "$GADGET"
    echo 0x1d6b > "$GADGET/idVendor"     # Linux Foundation
    echo 0x0104 > "$GADGET/idProduct"    # Multifunction Composite Gadget
    echo 0x0200 > "$GADGET/bcdUSB"
    mkdir "$GADGET/strings/0x409"
    echo "$serial"       > "$GADGET/strings/0x409/serialnumber"
    echo "Mountable"     > "$GADGET/strings/0x409/manufacturer"
    echo "Virtual Drive" > "$GADGET/strings/0x409/product"

    mkdir "$CONF"
    mkdir "$CONF/strings/0x409"
    echo "Mass Storage" > "$CONF/strings/0x409/configuration"
    echo 250 > "$CONF/MaxPower"

    mkdir "$FUNC"
    echo 0 > "$FUNC/stall"
    echo 1 > "$LUN/removable"
    echo "$cdrom" > "$LUN/cdrom"
    echo "$ro" > "$LUN/ro"
    echo "$image" > "$LUN/file"

    ln -s "$FUNC" "$CONF/"

    # Pausing the existing gadget can drop the session this runs in (e.g. an
    # adb shell); keep going so the controller is never left with nothing.
    trap '' HUP
    pause_other_gadgets "$udc"

    echo "$udc" > "$GADGET/UDC" || die "could not bind to controller $udc.
Something else is still using it: run '$0 status' to see what."
    BOUND=1

    echo "Mounted $image"
    echo "  as:         $([ "$cdrom" -eq 1 ] && echo "CD-ROM" || echo "disk"), $([ "$ro" -eq 1 ] && echo "read-only" || echo "read-write")"
    echo "  controller: $udc"
    wait_for_host "$udc"
}

cmd_unmount() {
    need_root
    [ -d "$GADGET" ] || [ -f "$PAUSED" ] || { echo "Nothing is mounted."; return 0; }
    teardown
    echo "Unmounted."
}

cmd_status() {
    local udc d
    if udc=$(find_udc); then
        echo "Controller:  $udc"
        echo "State:       $(udc_attr "$udc" state)"
        echo "Speed:       $(udc_attr "$udc" current_speed)"
        echo "Bound to:    $(udc_attr "$udc" function)"
    else
        echo "Controller:  none (device mode not enabled?)"
    fi

    # Anything else that could be holding the controller.
    echo "Gadgets in configfs:"
    for d in "$CONFIGFS"/usb_gadget/*; do
        [ -d "$d" ] || continue
        echo "  $(basename "$d"): UDC='$(cat "$d/UDC" 2>/dev/null || true)' functions: $(ls "$d/functions" 2>/dev/null | tr '\n' ' ')"
    done
    echo "Gadget modules loaded:"
    lsmod | awk '$1 ~ /^(g_|usb_f_|libcomposite|dwc2)/ { print "  " $1 }'
    echo "Kernel command line: $(cat /proc/cmdline)"

    if [ -d "$GADGET" ]; then
        echo "Image:       $(cat "$LUN/file")"
        echo "Mode:        $([ "$(cat "$LUN/cdrom")" = 1 ] && echo "CD-ROM" || echo "disk"), $([ "$(cat "$LUN/ro")" = 1 ] && echo "read-only" || echo "read-write")"
    else
        echo "Image:       none"
    fi

    # Devices on the Cardputer's own USB bus. Anything listed here means the
    # port is acting as a host, i.e. the switch is not set to Slave.
    echo "Attached USB devices (host side):"
    for d in /sys/bus/usb/devices/*; do
        [ -f "$d/idVendor" ] || continue
        case $(basename "$d") in usb*) continue ;; esac   # skip root hubs
        echo "  $(cat "$d/idVendor"):$(cat "$d/idProduct") $(cat "$d/product" 2>/dev/null || true)"
    done
}

cmd_fetch_alpine() {
    local dir=${1:-.} base file sum
    base=https://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64
    read -r file sum < <(curl -fsSL "$base/latest-releases.yaml" | awk '
        $1 == "file:" && $2 ~ /^alpine-standard-.*\.iso$/ { f = $2 }
        $1 == "sha256:" && f != "" { print f, $2; exit }') \
        || die "could not find the current Alpine release"
    [ -n "$file" ] && [ -n "$sum" ] || die "could not parse the Alpine release list"

    mkdir -p "$dir"
    echo "Downloading $file..."
    curl -fL --progress-bar -C - -o "$dir/$file" "$base/$file"
    echo "Verifying checksum..."
    echo "$sum  $dir/$file" | sha256sum -c - >/dev/null \
        || die "checksum mismatch for $dir/$file; delete it and retry"
    echo "Saved $dir/$file"
}

# Configuring the USB gadget needs root; re-run through sudo when needed.
case ${1:-} in
    mount|unmount) [ "$(id -u)" -eq 0 ] || exec sudo "$0" "$@" ;;
esac

case ${1:-} in
    mount)       shift; cmd_mount "$@" ;;
    unmount)      cmd_unmount ;;
    status)       cmd_status ;;
    fetch-alpine) shift; cmd_fetch_alpine "$@" ;;
    *)            sed -n '3,15p' "$0" | sed 's/^# \{0,1\}//'; exit 1 ;;
esac
