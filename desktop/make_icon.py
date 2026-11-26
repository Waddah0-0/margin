"""Generate desktop/assets/margin.ico directly from the margin mark geometry (no external deps).

Draws the exact ``ui/public/mark.svg`` vector (32x32 grid: dark ink square with rounded corners,
vermilion vertical margin rule, red margin note dash, and three warm paper text lines) into
multi-resolution PNG-encoded ICO frames (16, 24, 32, 48, 64, 128, 256 px).
"""

from __future__ import annotations

import struct
import zlib
from pathlib import Path

BG = (0x14, 0x14, 0x13, 0xFF)
RED = (0xFF, 0x5A, 0x43, 0xFF)
PAPER = (0xF5, 0xF5, 0xF1, 0xFF)
CLEAR = (0x00, 0x00, 0x00, 0x00)

SIZES = (16, 24, 32, 48, 64, 128, 256)


def _sample(x: float, y: float) -> tuple[int, int, int, int]:
    """Return RGBA colour at coordinate (x, y) in the 32x32 mark viewBox."""
    r = 4.0
    if x < r and y < r and (x - r) ** 2 + (y - r) ** 2 > r * r:
        return CLEAR
    if x > 32.0 - r and y < r and (x - (32.0 - r)) ** 2 + (y - r) ** 2 > r * r:
        return CLEAR
    if x < r and y > 32.0 - r and (x - r) ** 2 + (y - (32.0 - r)) ** 2 > r * r:
        return CLEAR
    if x > 32.0 - r and y > 32.0 - r and (x - (32.0 - r)) ** 2 + (y - (32.0 - r)) ** 2 > r * r:
        return CLEAR

    # vertical red margin line: x = 11.5, stroke-width = 1.5
    if 10.75 <= x <= 12.25:
        return RED
    # red note in left margin: M4.5 16h4, stroke-width = 2.5
    if 4.5 <= x <= 8.5 and 14.75 <= y <= 17.25:
        return RED
    # three content lines right of the margin: stroke-width = 2.5
    if 15.5 <= x <= 25.5 and 8.25 <= y <= 10.75:
        return PAPER
    if 15.5 <= x <= 23.5 and 14.75 <= y <= 17.25:
        return PAPER
    if 15.5 <= x <= 25.5 and 21.25 <= y <= 23.75:
        return PAPER
    return BG


def _render_png(size: int) -> bytes:
    """Render one ``size x size`` RGBA PNG with 2x2 supersampling."""
    raw = bytearray()
    scale = 32.0 / size
    offsets = (0.25, 0.75)
    for py in range(size):
        raw.append(0)  # PNG filter type 0 (None)
        for px in range(size):
            r_sum = g_sum = b_sum = a_sum = 0
            for oy in offsets:
                for ox in offsets:
                    r, g, b, a = _sample((px + ox) * scale, (py + oy) * scale)
                    r_sum += r * a
                    g_sum += g * a
                    b_sum += b * a
                    a_sum += a
            if a_sum == 0:
                raw.extend((0, 0, 0, 0))
            else:
                raw.extend((r_sum // a_sum, g_sum // a_sum, b_sum // a_sum, a_sum // 4))

    def chunk(kind: bytes, data: bytes) -> bytes:
        crc = zlib.crc32(kind + data) & 0xFFFFFFFF
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", crc)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw), level=9)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", idat) + chunk(b"IEND", b"")


def write_ico(dest: Path) -> Path:
    """Write a multi-resolution Windows ``.ico`` file to ``dest``."""
    frames = [(size, _render_png(size)) for size in SIZES]
    dest.parent.mkdir(parents=True, exist_ok=True)
    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = 6 + 16 * len(frames)
    entries = bytearray()
    payload = bytearray()
    for size, png in frames:
        dim = 0 if size >= 256 else size
        entries.extend(struct.pack("<BBBBHHII", dim, dim, 0, 0, 1, 32, len(png), offset))
        payload.extend(png)
        offset += len(png)
    dest.write_bytes(header + bytes(entries) + bytes(payload))
    return dest


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "assets" / "margin.ico"
    write_ico(out)
    print(f"wrote {out} ({out.stat().st_size} bytes)")
