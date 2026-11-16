"""The local image library: files in IMAGES_DIR that can be mounted."""

from pathlib import Path

from .config import IMAGE_EXTENSIONS, IMAGES_DIR


def has_boot_signature(path):
    """True if the file starts with an MBR/GPT boot sector (bytes 510-511 = 55 AA)."""
    try:
        with open(path, "rb") as f:
            f.seek(510)
            return f.read(2) == b"\x55\xaa"
    except OSError:
        return False


def default_mode(path):
    """How an image should be presented when the user does not choose.

    Hybrid ISOs and raw disk images boot as a plain USB disk. An ISO without a
    boot sector only makes sense as an optical drive.
    """
    if Path(path).suffix.lower() == ".iso" and not has_boot_signature(path):
        return "cdrom"
    return "disk"


def resolve(name):
    """Map a library-relative name to a path, refusing anything outside IMAGES_DIR."""
    root = IMAGES_DIR.resolve()
    path = (root / name).resolve()
    if root not in path.parents or not path.is_file():
        raise ValueError(f"no such image: {name}")
    return path


def list_images():
    images = []
    if not IMAGES_DIR.is_dir():
        return images
    for path in sorted(IMAGES_DIR.rglob("*"), key=lambda p: p.name.lower()):
        if path.suffix.lower() not in IMAGE_EXTENSIONS or not path.is_file():
            continue
        images.append({
            "name": str(path.relative_to(IMAGES_DIR)),
            "path": str(path.resolve()),
            "size": path.stat().st_size,
            "mode": default_mode(path),
            "kind": path.suffix.lower().lstrip("."),
        })
    return images
