"""Lossless "tile-delta" codec for a session's keyframes.

Consecutive screenshots of someone working are mostly identical: the same window chrome,
taskbar and page, with a small region changed. Keyframes are stored as JPEGs; decoding them
and comparing 16x16 tiles (aligned with JPEG's 16x16 MCUs, so unchanged regions decode to
identical pixels) finds exactly what changed.

For each frame, every tile is classified:
- SAME: identical to the same position in the previous frame (costs nothing);
- REF:  identical to a tile seen earlier anywhere (e.g. switching back to a window);
- NEW:  drawn on an otherwise black canvas saved as lossless WebP, which keeps the new tiles'
        spatial context (good compression) while the black areas cost almost nothing.
Never expand: if that isn't smaller than the original JPEG, the JPEG bytes are kept as-is.

Encoder and decoder update the same tile table (`_State`) in the same order, so references
resolve identically. Decoding reproduces the decoded pixels bit for bit, verified per frame
with SHA-256. Analysis works on pixels, not file bytes, so restored sessions analyze the same.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

import cv2
import numpy as np
import zstandard

TILE = 16
SAME, NEW = 0, 1  # tile codes; code >= 2 references tile-table entry (code - 2)


@dataclass
class EncodedFrame:
    name: str
    kind: str  # "jpeg" (original bytes kept) or "delta"
    data: bytes  # JPEG bytes, or the WebP canvas of new tiles (may be empty)
    tile_map: bytes  # zstd-compressed int32 codes (delta frames only)
    sha256: str  # of the decoded pixels
    shape: tuple[int, int]  # (height, width) before padding


def _decode_jpeg(data: bytes) -> np.ndarray:
    img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("cannot decode keyframe image")
    return img


def _pad(img: np.ndarray) -> np.ndarray:
    h, w = img.shape[:2]
    ph, pw = -h % TILE, -w % TILE
    return np.pad(img, ((0, ph), (0, pw), (0, 0))) if ph or pw else img


def _tile(img: np.ndarray, ty: int, tx: int) -> np.ndarray:
    return img[ty * TILE:(ty + 1) * TILE, tx * TILE:(tx + 1) * TILE]


def pixels_hash(img: np.ndarray) -> str:
    return hashlib.sha256(np.ascontiguousarray(img).tobytes() + repr(img.shape).encode()).hexdigest()


def _key(tile: np.ndarray) -> bytes:
    return hashlib.blake2b(np.ascontiguousarray(tile).tobytes(), digest_size=16).digest()


class _State:
    """Tile table + previous frame, updated identically by encoder and decoder."""

    def __init__(self):
        self.table: dict[bytes, int] = {}
        self.locations: list[tuple[int, int, int]] = []  # table index -> (frame, ty, tx)
        self.frames: list[np.ndarray] = []  # padded pixels of every frame so far

    def _register(self, frame_index: int, padded: np.ndarray, ty: int, tx: int) -> None:
        key = _key(_tile(padded, ty, tx))
        if key not in self.table:
            self.table[key] = len(self.locations)
            self.locations.append((frame_index, ty, tx))

    def classify(self, padded: np.ndarray) -> tuple[np.ndarray, np.ndarray, int]:
        """Codes for a frame, a canvas holding its NEW tiles, and how many there are."""
        fi = len(self.frames)
        prev = self.frames[-1] if self.frames and self.frames[-1].shape == padded.shape else None
        gh, gw = padded.shape[0] // TILE, padded.shape[1] // TILE
        codes = np.empty((gh, gw), np.int32)
        canvas = np.zeros_like(padded)
        new = 0
        for ty in range(gh):
            for tx in range(gw):
                tile = _tile(padded, ty, tx)
                if prev is not None and np.array_equal(tile, _tile(prev, ty, tx)):
                    codes[ty, tx] = SAME
                    continue
                ref = self.table.get(_key(tile))
                if ref is not None:
                    codes[ty, tx] = ref + 2
                    continue
                codes[ty, tx] = NEW
                canvas[ty * TILE:(ty + 1) * TILE, tx * TILE:(tx + 1) * TILE] = tile
                self._register(fi, padded, ty, tx)
                new += 1
        self.frames.append(padded)
        return codes, canvas, new

    def reconstruct(self, codes: np.ndarray, canvas: np.ndarray | None, padded_shape: tuple[int, ...]) -> np.ndarray:
        fi = len(self.frames)
        prev = self.frames[-1] if self.frames else None
        out = np.zeros(padded_shape, np.uint8)
        gh, gw = codes.shape
        for ty in range(gh):
            for tx in range(gw):
                code = codes[ty, tx]
                ys, xs = slice(ty * TILE, (ty + 1) * TILE), slice(tx * TILE, (tx + 1) * TILE)
                if code == SAME:
                    out[ys, xs] = prev[ys, xs]
                elif code == NEW:
                    out[ys, xs] = canvas[ys, xs]
                    self._register(fi, out, ty, tx)
                else:
                    sf, sty, stx = self.locations[code - 2]
                    # A reference can point earlier into this same frame (raster order), e.g. repeated blank tiles.
                    out[ys, xs] = _tile(out if sf == fi else self.frames[sf], sty, stx)
        self.frames.append(out)
        return out


def encode(frames: list[tuple[str, bytes]]) -> list[EncodedFrame]:
    """frames: (name, jpeg bytes) in chronological order."""
    cctx = zstandard.ZstdCompressor(level=19)
    state = _State()
    out: list[EncodedFrame] = []
    for name, jpeg in frames:
        img = _decode_jpeg(jpeg)
        codes, canvas, new = state.classify(_pad(img))
        delta = b""
        if new:
            ok, buf = cv2.imencode(".webp", canvas, [cv2.IMWRITE_WEBP_QUALITY, 101])  # >100 = lossless
            if not ok:
                raise RuntimeError("WebP encoding failed")
            delta = buf.tobytes()
        tile_map = cctx.compress(codes.tobytes())
        kind = "delta" if len(out) and len(delta) + len(tile_map) < len(jpeg) else "jpeg"
        out.append(EncodedFrame(name, kind, delta if kind == "delta" else jpeg,
                                tile_map if kind == "delta" else b"", pixels_hash(img), img.shape[:2]))
    return out


def decode(encoded: list[EncodedFrame]):
    """Yield (name, file bytes): JPEG frames byte-identical, delta frames as PNG with exact pixels."""
    dctx = zstandard.ZstdDecompressor()
    state = _State()
    for ef in encoded:
        h, w = ef.shape
        if ef.kind == "jpeg":
            img = _decode_jpeg(ef.data)
            state.classify(_pad(img))  # keep the tile table in step with the encoder
            data = ef.data
        else:
            padded_shape = (h + (-h % TILE), w + (-w % TILE), 3)
            codes = np.frombuffer(dctx.decompress(ef.tile_map), np.int32).reshape(padded_shape[0] // TILE, padded_shape[1] // TILE)
            canvas = cv2.imdecode(np.frombuffer(ef.data, np.uint8), cv2.IMREAD_COLOR) if ef.data else None
            img = state.reconstruct(codes, canvas, padded_shape)[:h, :w]
            ok, buf = cv2.imencode(".png", img)
            data = buf.tobytes()
        if pixels_hash(img) != ef.sha256:
            raise ValueError(f"keyframe {ef.name} failed its integrity check")
        yield ef.name, data


def pack(encoded: list[EncodedFrame]) -> tuple[bytes, dict[str, bytes]]:
    """Serialise to an index (JSON) plus named blobs."""
    index, blobs = [], {}
    for i, ef in enumerate(encoded):
        entry = {"name": ef.name, "kind": ef.kind, "sha256": ef.sha256, "shape": list(ef.shape),
                 "data": f"kf/{i:05d}.{'jpg' if ef.kind == 'jpeg' else 'webp'}"}
        blobs[entry["data"]] = ef.data
        if ef.kind == "delta":
            entry["map"] = f"kf/{i:05d}.map"
            blobs[entry["map"]] = ef.tile_map
        index.append(entry)
    return json.dumps(index).encode(), blobs


def unpack(index_json: bytes, blobs: dict[str, bytes]) -> list[EncodedFrame]:
    return [
        EncodedFrame(e["name"], e["kind"], blobs[e["data"]], blobs.get(e.get("map", ""), b""), e["sha256"], tuple(e["shape"]))
        for e in json.loads(index_json)
    ]
