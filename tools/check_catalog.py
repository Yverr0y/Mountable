#!/usr/bin/env python3
"""Validate the Mountable image catalog.

Usage:
    check_catalog.py [--online] [--jobs N] [--timeout SEC] [CATALOG]

Without flags only the structure of the JSON file is checked. With --online
every entry is additionally checked against its download server:

  * the URL (after redirects) answers HTTP 200,
  * Content-Length equals the "size" field,
  * the first 512 bytes of the (decompressed) image carry the 55 AA boot
    signature at offset 510 if "mode" is "disk", and do not if it is "cdrom",
  * for "zip" entries the archive's central directory is readable, the image
    is taken to be its largest member, and "unpacked_size" (if present)
    equals that member's size,
  * for "gz" entries "unpacked_size" (if present) agrees with the size
    recorded in the gzip trailer (modulo 4 GiB).

Only the first bytes of each image (and the end of zip and gz files) are
fetched; checksums are not recomputed.
The exit status is 0 if everything passed and 1 otherwise.
"""

import argparse
import bz2
import concurrent.futures
import datetime
import json
import lzma
import os
import re
import struct
import sys
import urllib.error
import urllib.request
import zlib

DEFAULT_CATALOG = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "catalog", "catalog.json"
)

SCHEMA_VERSION = 1
NAME_MAX = 24
DESCRIPTION_MAX = 90
COMPRESSIONS = (None, "xz", "gz", "bz2", "zip")
COMPRESSION_SUFFIXES = {"xz": ".xz", "gz": ".gz", "bz2": ".bz2", "zip": ".zip"}
IMAGE_EXTENSIONS = (
    ".iso", ".img", ".raw", ".dd", ".bin", ".ima", ".dsk", ".hdd", ".usb",
)
MODES = ("disk", "cdrom")

ID_RE = re.compile(r"^[a-z0-9-]+$")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")

TOP_KEYS = {"schema": int, "updated": str, "categories": list, "images": list}
CATEGORY_KEYS = {"id": str, "name": str, "description": str}
IMAGE_KEYS = {
    "id": str,
    "name": str,
    "version": str,
    "category": str,
    "arch": str,
    "description": str,
    "homepage": str,
    "url": str,
    "filename": str,
    "size": int,
    "sha256": str,
    "compression": (str, type(None)),
    "mode": str,
}
# Keys that may be left out of an image entry.
IMAGE_OPTIONAL_KEYS = {"unpacked_size": int}

USER_AGENT = "mountable-catalog-check/1"
# Compressed bytes fetched to recover the first sector of a compressed image.
COMPRESSED_PROBE_BYTES = 4 * 1024 * 1024


def check_keys(obj, spec, where, errors, optional=None):
    """Check that obj is a dict with exactly the keys/types in spec.

    Keys listed in optional may be absent but are type-checked when present.
    """
    optional = optional or {}
    if not isinstance(obj, dict):
        errors.append(f"{where}: must be an object")
        return False
    ok = True
    for key, typ in spec.items():
        if key not in obj:
            errors.append(f"{where}: missing key '{key}'")
            ok = False
            continue
        value = obj[key]
        # bool is a subclass of int; never accept it where a number is wanted.
        if isinstance(value, bool) or not isinstance(value, typ):
            errors.append(f"{where}: '{key}' has wrong type {type(value).__name__}")
            ok = False
    for key, typ in optional.items():
        if key not in obj:
            continue
        value = obj[key]
        if isinstance(value, bool) or not isinstance(value, typ):
            errors.append(f"{where}: '{key}' has wrong type {type(value).__name__}")
            ok = False
    for key in obj:
        if key not in spec and key not in optional:
            errors.append(f"{where}: unknown key '{key}'")
            ok = False
    return ok


def validate(catalog):
    """Return a list of structural problems found in the catalog."""
    errors = []
    if not check_keys(catalog, TOP_KEYS, "catalog", errors):
        return errors

    if catalog["schema"] != SCHEMA_VERSION:
        errors.append(f"catalog: 'schema' must be {SCHEMA_VERSION}")
    try:
        datetime.date.fromisoformat(catalog["updated"])
    except ValueError:
        errors.append("catalog: 'updated' must be a YYYY-MM-DD date")

    category_ids = set()
    for index, category in enumerate(catalog["categories"]):
        where = f"categories[{index}]"
        if not check_keys(category, CATEGORY_KEYS, where, errors):
            continue
        cid = category["id"]
        where = f"category '{cid}'"
        if not ID_RE.match(cid):
            errors.append(f"{where}: id must match [a-z0-9-]+")
        if cid in category_ids:
            errors.append(f"{where}: duplicate id")
        category_ids.add(cid)
        if not category["name"].strip():
            errors.append(f"{where}: empty name")
        if not category["description"].strip():
            errors.append(f"{where}: empty description")
    if not catalog["categories"]:
        errors.append("catalog: no categories")
    if not catalog["images"]:
        errors.append("catalog: no images")

    image_ids = set()
    used_categories = set()
    for index, image in enumerate(catalog["images"]):
        where = f"images[{index}]"
        if not check_keys(image, IMAGE_KEYS, where, errors, IMAGE_OPTIONAL_KEYS):
            continue
        iid = image["id"]
        where = f"image '{iid}'"
        if not ID_RE.match(iid):
            errors.append(f"{where}: id must match [a-z0-9-]+")
        if iid in image_ids:
            errors.append(f"{where}: duplicate id")
        image_ids.add(iid)

        name = image["name"]
        if not name.strip():
            errors.append(f"{where}: empty name")
        if len(name) > NAME_MAX:
            errors.append(f"{where}: name is {len(name)} chars (max {NAME_MAX})")

        description = image["description"]
        if not description.strip():
            errors.append(f"{where}: empty description")
        if len(description) > DESCRIPTION_MAX:
            errors.append(
                f"{where}: description is {len(description)} chars "
                f"(max {DESCRIPTION_MAX})"
            )
        if "\n" in description or "\r" in description:
            errors.append(f"{where}: description must be a single line")

        for key in ("version", "arch"):
            if not image[key].strip():
                errors.append(f"{where}: empty {key}")

        if image["category"] not in category_ids:
            errors.append(f"{where}: unknown category '{image['category']}'")
        used_categories.add(image["category"])

        for key in ("homepage", "url"):
            if not re.match(r"^https://[^\s/]+(/\S*)?$", image[key]):
                errors.append(f"{where}: {key} must be an https:// URL")

        filename = image["filename"]
        if (
            not filename
            or filename in (".", "..")
            or "/" in filename
            or "\\" in filename
            or "\0" in filename
        ):
            errors.append(f"{where}: filename must be a plain file name")

        if image["size"] <= 0:
            errors.append(f"{where}: size must be a positive integer")
        if not SHA256_RE.match(image["sha256"]):
            errors.append(f"{where}: sha256 must be 64 lowercase hex chars")
        compression = image["compression"]
        if compression not in COMPRESSIONS:
            errors.append(
                f"{where}: compression must be null, xz, gz, bz2 or zip"
            )
        else:
            # The app strips the compression suffix to name the final image,
            # and only offers files with a known image extension.
            suffix = COMPRESSION_SUFFIXES.get(compression, "")
            final = filename if isinstance(filename, str) else ""
            if suffix:
                if final.lower().endswith(suffix):
                    final = final[: -len(suffix)]
                else:
                    errors.append(
                        f"{where}: filename must end in '{suffix}' "
                        f"for {compression} compression"
                    )
                    final = ""
            if final and not final.lower().endswith(IMAGE_EXTENSIONS):
                errors.append(
                    f"{where}: image name '{final}' must end in one of "
                    + " ".join(IMAGE_EXTENSIONS)
                )
        if "unpacked_size" in image:
            if compression is None:
                errors.append(
                    f"{where}: unpacked_size is only allowed on compressed entries"
                )
            if image["unpacked_size"] <= 0:
                errors.append(f"{where}: unpacked_size must be a positive integer")
        if image["mode"] not in MODES:
            errors.append(f"{where}: mode must be 'disk' or 'cdrom'")

    for cid in sorted(category_ids - used_categories):
        errors.append(f"category '{cid}': no images use it")
    return errors


def _open(url, timeout, method="GET", byte_range=None):
    request = urllib.request.Request(url, method=method)
    request.add_header("User-Agent", USER_AGENT)
    request.add_header("Accept", "*/*")
    if byte_range is not None:
        request.add_header("Range", f"bytes={byte_range[0]}-{byte_range[1]}")
    return urllib.request.urlopen(request, timeout=timeout)


def _read_prefix(url, timeout, count):
    """Return the first count bytes of url (fewer if the file is shorter)."""
    with _open(url, timeout, byte_range=(0, count - 1)) as response:
        # A server that ignores Range answers 200 with the whole file; reading
        # a bounded amount and closing keeps the transfer small either way.
        chunks = []
        remaining = count
        while remaining > 0:
            chunk = response.read(min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


def _read_range(url, timeout, start, count):
    """Return count bytes of url starting at offset start.

    Unlike _read_prefix this needs a server that honours Range requests.
    """
    with _open(url, timeout, byte_range=(start, start + count - 1)) as response:
        if response.status != 206:
            raise OSError("server does not support range requests")
        chunks = []
        remaining = count
        while remaining > 0:
            chunk = response.read(min(remaining, 65536))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks)


def _zip64_extra(extra, wanted):
    """Decode the zip64 extended information field.

    wanted lists, in order, the names of the 32-bit header fields that were
    saturated and therefore stored as 64-bit values in the extra field.
    """
    offset = 0
    while offset + 4 <= len(extra):
        tag, length = struct.unpack_from("<HH", extra, offset)
        body = extra[offset + 4:offset + 4 + length]
        if tag == 0x0001:
            values = {}
            position = 0
            for name in wanted:
                if position + 8 > len(body):
                    raise ValueError("truncated zip64 extra field")
                values[name] = struct.unpack_from("<Q", body, position)[0]
                position += 8
            return values
        offset += 4 + length
    if wanted:
        raise ValueError("zip64 extra field missing")
    return {}


def _zip_largest_member(url, total_size, timeout):
    """Return (name, method, compressed, uncompressed, header_offset) of the
    largest file in the zip archive at url, read from its central directory."""
    tail_length = min(total_size, 65536 + 22 + 20)
    tail_start = total_size - tail_length
    tail = _read_range(url, timeout, tail_start, tail_length)
    eocd = tail.rfind(b"PK\x05\x06")
    if eocd < 0 or eocd + 22 > len(tail):
        raise ValueError("zip end-of-central-directory record not found")
    entries, cd_size, cd_offset = struct.unpack_from("<HII", tail, eocd + 10)
    if entries == 0xFFFF or cd_size == 0xFFFFFFFF or cd_offset == 0xFFFFFFFF:
        locator = eocd - 20
        if locator < 0 or tail[locator:locator + 4] != b"PK\x06\x07":
            raise ValueError("zip64 locator not found")
        record_offset = struct.unpack_from("<Q", tail, locator + 8)[0]
        record = _read_range(url, timeout, record_offset, 56)
        if record[:4] != b"PK\x06\x06" or len(record) < 56:
            raise ValueError("zip64 end-of-central-directory record not found")
        entries, cd_size, cd_offset = struct.unpack_from("<QQQ", record, 32)
    if cd_size > 16 * 1024 * 1024:
        raise ValueError("zip central directory is unreasonably large")
    if cd_offset >= tail_start and cd_offset + cd_size <= total_size:
        directory = tail[cd_offset - tail_start:cd_offset - tail_start + cd_size]
    else:
        directory = _read_range(url, timeout, cd_offset, cd_size)

    best = None
    position = 0
    for _ in range(entries):
        if directory[position:position + 4] != b"PK\x01\x02":
            raise ValueError("corrupt zip central directory")
        (method, compressed, uncompressed, name_length, extra_length,
         comment_length) = struct.unpack_from("<H8xIIHHH", directory, position + 10)
        header_offset = struct.unpack_from("<I", directory, position + 42)[0]
        name_end = position + 46 + name_length
        name = directory[position + 46:name_end].decode("utf-8", "replace")
        extra = directory[name_end:name_end + extra_length]
        wanted = []
        if uncompressed == 0xFFFFFFFF:
            wanted.append("uncompressed")
        if compressed == 0xFFFFFFFF:
            wanted.append("compressed")
        if header_offset == 0xFFFFFFFF:
            wanted.append("header_offset")
        if wanted:
            values = _zip64_extra(extra, wanted)
            uncompressed = values.get("uncompressed", uncompressed)
            compressed = values.get("compressed", compressed)
            header_offset = values.get("header_offset", header_offset)
        if not name.endswith("/") and (best is None or uncompressed > best[3]):
            best = (name, method, compressed, uncompressed, header_offset)
        position = name_end + extra_length + comment_length
    if best is None:
        raise ValueError("zip archive contains no files")
    return best


def _zip_first_sector(url, member, timeout):
    """Return the first 512 bytes of a zip member located by its header."""
    _name, method, compressed, _uncompressed, header_offset = member
    header = _read_range(url, timeout, header_offset, 30)
    if header[:4] != b"PK\x03\x04" or len(header) < 30:
        raise ValueError("zip local file header not found")
    name_length, extra_length = struct.unpack_from("<HH", header, 26)
    data_offset = header_offset + 30 + name_length + extra_length
    count = min(compressed, COMPRESSED_PROBE_BYTES)
    if method == 0:
        return _read_range(url, timeout, data_offset, min(count, 512))
    if method != 8:
        raise ValueError(f"unsupported zip compression method {method}")
    data = _read_range(url, timeout, data_offset, count)
    return zlib.decompressobj(wbits=-zlib.MAX_WBITS).decompress(data, 512)


def _first_sector(url, compression, timeout):
    """Return the first 512 bytes of the image, decompressing if needed."""
    if compression is None:
        return _read_prefix(url, timeout, 512)
    data = _read_prefix(url, timeout, COMPRESSED_PROBE_BYTES)
    if compression == "xz":
        decompressor = lzma.LZMADecompressor()
        return decompressor.decompress(data, max_length=512)
    if compression == "bz2":
        decompressor = bz2.BZ2Decompressor()
        return decompressor.decompress(data, max_length=512)
    if compression == "gz":
        decompressor = zlib.decompressobj(wbits=zlib.MAX_WBITS | 16)
        return decompressor.decompress(data, 512)
    raise ValueError(f"unsupported compression '{compression}'")


def check_online(image, timeout):
    """Return a list of problems found for one image on its server."""
    problems = []
    url = image["url"]

    try:
        with _open(url, timeout, method="HEAD") as response:
            status = response.status
            length = response.headers.get("Content-Length")
    except urllib.error.HTTPError as exc:
        return [f"HTTP {exc.code} for {url}"]
    except (urllib.error.URLError, OSError) as exc:
        return [f"request failed: {exc}"]

    if status != 200:
        problems.append(f"HTTP status {status}, expected 200")
    if length is None:
        problems.append("server sent no Content-Length")
    elif not length.isdigit() or int(length) != image["size"]:
        problems.append(f"Content-Length {length} != size {image['size']}")

    compression = image["compression"]
    unpacked_size = image.get("unpacked_size")
    try:
        if compression == "zip":
            member = _zip_largest_member(url, image["size"], timeout)
            if not member[0].lower().endswith(IMAGE_EXTENSIONS):
                problems.append(
                    f"largest zip member '{member[0]}' is not a disk image"
                )
            if unpacked_size is not None and unpacked_size != member[3]:
                problems.append(
                    f"unpacked_size {unpacked_size} != zip member size {member[3]}"
                )
            sector = _zip_first_sector(url, member, timeout)
        else:
            if compression == "gz" and unpacked_size is not None:
                trailer = _read_range(url, timeout, image["size"] - 4, 4)
                isize = struct.unpack("<I", trailer)[0]
                if unpacked_size % (1 << 32) != isize:
                    problems.append(
                        f"unpacked_size {unpacked_size} does not match "
                        f"gzip trailer size {isize}"
                    )
            sector = _first_sector(url, compression, timeout)
    except urllib.error.HTTPError as exc:
        problems.append(f"HTTP {exc.code} reading first sector")
        return problems
    except (urllib.error.URLError, OSError, EOFError) as exc:
        problems.append(f"reading first sector failed: {exc}")
        return problems
    except (lzma.LZMAError, zlib.error, ValueError, struct.error) as exc:
        problems.append(f"cannot decompress start of image: {exc}")
        return problems

    if len(sector) < 512:
        problems.append(f"only {len(sector)} bytes of first sector available")
        return problems
    has_signature = sector[510:512] == b"\x55\xaa"
    if image["mode"] == "disk" and not has_signature:
        problems.append("mode is 'disk' but 55 AA boot signature is missing")
    if image["mode"] == "cdrom" and has_signature:
        problems.append("mode is 'cdrom' but image has a 55 AA boot signature")
    return problems


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate the image catalog.")
    parser.add_argument("catalog", nargs="?", default=DEFAULT_CATALOG,
                        help="path to catalog.json (default: ../catalog/catalog.json)")
    parser.add_argument("--online", action="store_true",
                        help="also check URLs, sizes and boot signatures")
    parser.add_argument("--jobs", type=int, default=8,
                        help="parallel connections for --online (default: 8)")
    parser.add_argument("--timeout", type=float, default=45.0,
                        help="network timeout in seconds (default: 45)")
    args = parser.parse_args(argv)

    try:
        with open(args.catalog, encoding="utf-8") as handle:
            catalog = json.load(handle)
    except (OSError, ValueError) as exc:
        print(f"error: cannot read {args.catalog}: {exc}", file=sys.stderr)
        return 1

    errors = validate(catalog)
    if errors:
        for error in errors:
            print(f"FAIL  {error}")
        print(f"\nschema: {len(errors)} problem(s)")
        return 1

    images = catalog["images"]
    counts = {}
    for image in images:
        counts[image["category"]] = counts.get(image["category"], 0) + 1
    summary = ", ".join(
        f"{category['id']} {counts.get(category['id'], 0)}"
        for category in catalog["categories"]
    )
    print(f"schema: OK ({len(images)} images; {summary})")
    if not args.online:
        return 0

    failed = 0
    with concurrent.futures.ThreadPoolExecutor(max(1, args.jobs)) as pool:
        results = pool.map(lambda image: check_online(image, args.timeout), images)
        for image, problems in zip(images, results):
            if problems:
                failed += 1
                print(f"FAIL  {image['id']}")
                for problem in problems:
                    print(f"        {problem}")
            else:
                print(f"ok    {image['id']:<24} {image['size']:>11}  {image['mode']}")
    print(f"\nonline: {len(images) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
