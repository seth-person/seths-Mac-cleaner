"""Draw the app icon (1024x1024 PNG) with the standard library only.

  python3 macos/make_icon.py out.png

A rounded blue square with four "storage bars" of decreasing length: the
dashboard's space-by-type bar, tidied up.
"""
import math
import struct
import sys
import zlib

SIZE = 1024
MARGIN = 100           # macOS icons leave transparent space around the tile
RADIUS = 185
TOP = (0x3B, 0x8E, 0xEA)
BOTTOM = (0x1C, 0x5C, 0xAB)
BARS = [  # (y, length as a fraction, colour)
    (330, 0.78, (255, 255, 255)),
    (460, 0.60, (0xCD, 0xE2, 0xFB)),
    (590, 0.44, (0x9E, 0xC5, 0xF4)),
    (720, 0.28, (0x86, 0xB6, 0xEF)),
]
BAR_H = 74
BAR_X = 230
BAR_MAX = SIZE - 2 * BAR_X


def rounded_rect_coverage(x, y, x0, y0, x1, y1, r):
    """Approximate pixel coverage (0..1) of a rounded rectangle, anti-aliased."""
    cx = min(max(x, x0 + r), x1 - r)
    cy = min(max(y, y0 + r), y1 - r)
    d = math.hypot(x - cx, y - cy) - r
    return max(0.0, min(1.0, 0.5 - d))


def render() -> bytes:
    rows = []
    for py in range(SIZE):
        y = py + 0.5
        t = (py - MARGIN) / (SIZE - 2 * MARGIN)
        base = tuple(round(a + (b - a) * min(max(t, 0), 1)) for a, b in zip(TOP, BOTTOM))
        row = bytearray([0])  # PNG filter: none
        for px in range(SIZE):
            x = px + 0.5
            a = rounded_rect_coverage(x, y, MARGIN, MARGIN, SIZE - MARGIN, SIZE - MARGIN, RADIUS)
            if a <= 0:
                row += b"\0\0\0\0"
                continue
            r, g, b = base
            for by, frac, col in BARS:
                cov = rounded_rect_coverage(x, y, BAR_X, by, BAR_X + BAR_MAX * frac, by + BAR_H, BAR_H / 2)
                if cov > 0:
                    r, g, b = (round(c0 + (c1 - c0) * cov) for c0, c1 in zip((r, g, b), col))
            row += bytes((r, g, b, round(a * 255)))
        rows.append(bytes(row))
    raw = b"".join(rows)

    def chunk(kind, data):
        c = kind + data
        return struct.pack(">I", len(data)) + c + struct.pack(">I", zlib.crc32(c) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", SIZE, SIZE, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


if __name__ == "__main__":
    with open(sys.argv[1], "wb") as f:
        f.write(render())
