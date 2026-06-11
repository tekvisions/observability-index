#!/usr/bin/env python3
"""Render og.png (1200x630) for The Observability Index — "telemetry console" card.
Dark on-call console, phosphor-amber signal accent, a sparkline mark + a live waveform trace.
Pillow only; graceful fallback if unavailable."""
from __future__ import annotations

import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
BG = (10, 13, 18)        # #0a0d12 console black
INK = (233, 238, 246)    # #e9eef6
MUTED = (139, 152, 171)  # #8b98ab
AMBER = (255, 176, 46)   # #ffb02e phosphor
AMBER_DIM = (128, 90, 30)
GRID = (23, 30, 42)
BAR = (40, 52, 68)


def _font(paths, size):
    from PIL import ImageFont
    for p in paths:
        if os.path.exists(p):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                pass
    return ImageFont.load_default()


def main() -> int:
    try:
        from PIL import Image, ImageDraw
    except Exception:
        print("Pillow not available — skipping og.png")
        return 0
    try:
        data = json.load(open(os.path.join(HERE, "data.json"), encoding="utf-8"))
        count, cats = data.get("count", 0), len(data.get("categories", []))
    except Exception:
        count, cats = 0, 0

    W, H = 1200, 630
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    # faint instrument grid
    for x in range(0, W, 46):
        d.line([(x, 0), (x, H)], fill=GRID, width=1)
    for y in range(0, H, 46):
        d.line([(0, y), (W, y)], fill=GRID, width=1)

    bold = ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"]
    mono = ["/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/Monaco.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"]
    f_h1 = _font(bold, 88)
    f_kick = _font(mono, 24)
    f_stat = _font(mono, 27)

    # sparkline / signal-bars mark + wordmark
    gx, base_y, bw, gap, maxh = 70, 108, 8, 6, 36
    heights = [0.34, 0.58, 0.42, 1.0, 0.66, 0.80, 0.48]
    for i, hf in enumerate(heights):
        x = gx + i * (bw + gap)
        top = base_y - int(hf * maxh)
        d.rounded_rectangle([x, top, x + bw, base_y], radius=2, fill=AMBER if i == 3 else BAR)
    d.text((gx + 7 * (bw + gap) + 16, base_y - 30), "THE OBSERVABILITY INDEX", font=f_kick, fill=MUTED)

    # heavy title — "on watch" in amber
    d.text((66, 196), "The AI observability", font=f_h1, fill=INK)
    d.text((66, 300), "stack, ", font=f_h1, fill=INK)
    try:
        w_stack = d.textlength("stack, ", font=f_h1)
    except Exception:
        w_stack = 290
    d.text((66 + w_stack, 300), "on watch.", font=f_h1, fill=AMBER)

    # a live telemetry waveform (signal trace) across the lower band
    wy = 472
    d.line([(66, wy), (1134, wy)], fill=GRID, width=1)
    pattern = [0, 0, -6, 0, 0, 10, -4, 0, 0, 0, -40, 46, -12, 0, 0, 6, -6, 0, 0,
               0, -8, 0, 0, 22, -30, 8, 0, 0, 0, -5, 0, 0, 14, -10, 0, 0, -34, 40, -8, 0, 0, 0, -6, 0]
    pts = []
    n = len(pattern)
    for i, dv in enumerate(pattern):
        x = 66 + int(i * (1068 / (n - 1)))
        pts.append((x, wy + dv))
    d.line(pts, fill=AMBER_DIM, width=8, joint="curve")   # glow underlay
    d.line(pts, fill=AMBER, width=3, joint="curve")        # sharp trace

    d.text((70, 552), f"{count} tools  ·  {cats} categories  ·  ranked daily by GitHub momentum",
           font=f_stat, fill=MUTED)

    img.save(os.path.join(HERE, "og.png"))
    print(f"wrote og.png ({count} tools)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
