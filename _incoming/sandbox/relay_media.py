"""Real photo staging for Relay.

Confined file ids only: a browser sends bytes to ``POST /api/relay/media``, Relay
stores them under ``data/relay-media/<sha256>`` and answers with a file id. Every
later read resolves that id back through the store, so no browser-supplied path ever
reaches the filesystem. SVG is refused (scriptable), the MIME type must match the
magic bytes, and the size is bounded.

The model input is the verified native content-part shape (``type: "image_url"`` with
a ``data:`` url plus the ``[Image attached at: ...]`` text handle) that the installed
Hermes image routing builds and its vision history budget recognises.
"""
from __future__ import annotations

import base64
import hashlib
import os
import re
from pathlib import Path

import relay_store

MEDIA_DIR = Path(__file__).resolve().parent / "data" / "relay-media"
MAX_BYTES = 8 * 1024 * 1024
ALLOWED_MIME = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/webp": (b"RIFF",),
}
NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
FILE_ID_RE = re.compile(r"^[a-f0-9]{64}$")


class MediaError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def sniff(raw: bytes) -> str | None:
    """Return the MIME type the bytes actually are, or None."""
    for mime, magic in ALLOWED_MIME.items():
        if raw.startswith(magic):
            if mime == "image/webp" and len(raw) >= 12 and raw[8:12] != b"WEBP":
                continue
            return mime
    return None


def clean_name(name: object) -> str:
    base = os.path.basename(str(name or "")).strip()[:80]
    base = NAME_RE.sub("_", base).strip("._")
    if not base:
        base = "photo"
    return base[:80]


def dimensions(raw: bytes, mime: str) -> tuple[int, int]:
    """Read width/height from the header without decoding the pixels."""
    try:
        if mime == "image/png" and len(raw) >= 24 and raw[12:16] == b"IHDR":
            import struct

            return struct.unpack(">II", raw[16:24])
        if mime == "image/jpeg":
            index = 2
            while index + 9 < len(raw):
                if raw[index] != 0xFF:
                    index += 1
                    continue
                marker = raw[index + 1]
                if marker in {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}:
                    import struct

                    height, width = struct.unpack(">HH", raw[index + 5 : index + 9])
                    return width, height
                if marker in {0xD8, 0x01} or 0xD0 <= marker <= 0xD9:
                    index += 2
                    continue
                size = int.from_bytes(raw[index + 2 : index + 4], "big")
                if size < 2:
                    break
                index += 2 + size
        if mime == "image/webp" and len(raw) >= 30:
            import struct

            if raw[12:16] == b"VP8X":
                width = 1 + int.from_bytes(raw[24:27], "little")
                height = 1 + int.from_bytes(raw[27:30], "little")
                return width, height
            if raw[12:16] == b"VP8 " and raw[23:26] == b"\x9d\x01\x2a":
                return int.from_bytes(raw[26:28], "little") & 0x3FFF, int.from_bytes(raw[28:30], "little") & 0x3FFF
            if raw[12:16] == b"VP8L" and raw[20] & 0xC0 == 0x80:
                bits = int.from_bytes(raw[21:25], "little")
                return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
    except Exception:
        pass
    return 0, 0


def stage(raw: bytes, name: object, session_id: str, store: relay_store.RelayStore | None = None) -> dict:
    """Validate and store photo bytes. Returns the stored metadata (no path)."""
    store = store or relay_store.get_store()
    if not relay_store.valid_room(session_id):
        raise MediaError("Unknown room.", 400)
    data = bytes(raw) if isinstance(raw, (bytes, bytearray)) else b""
    if not data:
        raise MediaError("That photo is empty.", 400)
    if len(data) > MAX_BYTES:
        raise MediaError("That photo is over the 8 MB limit.", 413)
    mime = sniff(data)
    if mime is None:
        # SVG and anything else scriptable or unrecognised never enters the store.
        raise MediaError("Relay takes JPEG, PNG, or WebP photos only.", 415)
    sha = hashlib.sha256(data).hexdigest()
    MEDIA_DIR.mkdir(parents=True, exist_ok=True)
    path = MEDIA_DIR / sha
    if not path.exists():
        temp = MEDIA_DIR / (sha + ".tmp")
        temp.write_bytes(data)
        os.replace(temp, path)
    width, height = dimensions(data, mime)
    meta = store.media_add(sha, session_id, clean_name(name), mime, len(data), sha, width, height)
    meta["data_url"] = f"data:{mime};base64,{base64.b64encode(data).decode('ascii')}"
    return meta


def resolve(file_id: object, session_id: str, *, store: relay_store.RelayStore | None = None,
            with_bytes: bool = False) -> dict:
    """Resolve a confined file id back to its metadata (and bytes when asked)."""
    store = store or relay_store.get_store()
    fid = str(file_id or "")
    if not FILE_ID_RE.match(fid):
        raise MediaError("That photo id is not a Relay photo.", 400)
    meta = store.media_get(fid)
    if meta is None:
        raise MediaError("That photo is not in this Relay store.", 404)
    if relay_store.valid_room(session_id) and meta["session_id"] != session_id:
        # A room may only read photos staged in that same room.
        raise MediaError("That photo belongs to another Relay room.", 403)
    path = MEDIA_DIR / fid
    if not path.is_file():
        raise MediaError("That photo is no longer on disk.", 404)
    if with_bytes:
        meta["bytes"] = path.read_bytes()
    return meta


def data_url(meta: dict, raw: bytes) -> str:
    return f"data:{meta['mime']};base64,{base64.b64encode(raw).decode('ascii')}"


def native_image_parts(caption: str, meta: dict, raw: bytes) -> list[dict]:
    """The installed Hermes native attachment shape for one user turn.

    Mirrors ``agent/image_routing.build_native_content_parts``: one text part carrying
    the caption and the ``[Image attached at: ...]`` handle the vision history budget
    recognises, then one ``image_url`` part per image with the actual pixels.
    """
    label = str(meta.get("name") or "photo")
    handle = f"[Image attached at: {label}]"
    text = (caption or "").strip() or "What do you see in this photo?"
    return [
        {"type": "text", "text": f"{text}\n\n{handle}"},
        {"type": "image_url", "image_url": {"url": data_url(meta, raw)}},
    ]
