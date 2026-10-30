#!/usr/bin/env python3
"""Render a one-page PNG card for a display profile (display-profile/1 JSON).

The launcher's "HDR Display Profile" flow (qt-demo-launcher hdr-profile-worker.sh) measures a
profile and shows this card in touch-gallery: what the profile says about the display before it is
copied to a USB stick and uploaded to the HDR processor. Panels: the tone response (the ramps the
profile carries, nits per drive code), the primaries and white against BT.709 / BT.2020, the peak
by window size (local dimming) or by APL (OLED ABL), and the values, the creator's warnings and the
values a render assumes (--notes-file: make-display-profile.py --validate output).

    python3 src/display_profile_card.py --display-profile=P.json --output=card.png [--notes-file=F]
    python3 src/display_report_card.py --display-profile=P.json ...   (the same, through the main tool)
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import textwrap
from datetime import datetime
from pathlib import Path
from typing import Any

os.environ.setdefault("MPLCONFIGDIR", str(Path(tempfile.gettempdir()) / "disp-report-card-mpl"))
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt

A4_LANDSCAPE_INCHES = (11.69, 8.27)
BT709 = {"R": (0.640, 0.330), "G": (0.300, 0.600), "B": (0.150, 0.060)}
BT2020 = {"R": (0.708, 0.292), "G": (0.170, 0.797), "B": (0.131, 0.046)}
D65 = (0.3127, 0.3290)
INK = "#1F2328"
MUTED = "#5B6472"
RAMP_STYLES = (  # key, label, colour, width
    ("ramp_window", "window ramp", "#0969DA", 2.0),
    ("ramp_window_small", "small-window ramp", "#BF3989", 1.4),
    ("ramp", "full-field ramp", "#6E7781", 1.2),
)


def polygon_area(p: list[tuple[float, float]]) -> float:
    return abs(sum(p[i][0] * p[i - 1][1] - p[i - 1][0] * p[i][1] for i in range(len(p)))) / 2


def clip(subject: list[tuple[float, float]], clipper: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Sutherland-Hodgman: subject polygon clipped to a convex, counter-clockwise clipper."""
    def inside(p, a, b):
        return (b[0] - a[0]) * (p[1] - a[1]) - (b[1] - a[1]) * (p[0] - a[0]) >= 0

    def cut(p, q, a, b):
        x1, y1, x2, y2, x3, y3, x4, y4 = *p, *q, *a, *b
        d = (x1 - x2) * (y3 - y4) - (y1 - y2) * (x3 - x4)
        t = ((x1 - x3) * (y3 - y4) - (y1 - y3) * (x3 - x4)) / d
        return (x1 + t * (x2 - x1), y1 + t * (y2 - y1))

    out = subject
    for i in range(len(clipper)):
        a, b = clipper[i - 1], clipper[i]
        inp, out = out, []
        for j in range(len(inp)):
            p, q = inp[j - 1], inp[j]
            if inside(q, a, b):
                if not inside(p, a, b):
                    out.append(cut(p, q, a, b))
                out.append(q)
            elif inside(p, a, b):
                out.append(cut(p, q, a, b))
        if not out:
            break
    return out


def coverage(prim: dict[str, Any], ref: dict[str, tuple[float, float]]) -> float | None:
    """Share of the reference triangle the display's primaries cover (xy area)."""
    try:
        d = [tuple(prim[c]) for c in "RGB"]
    except (KeyError, TypeError):
        return None
    r = [ref[c] for c in "RGB"]
    return polygon_area(clip(d, r)) / polygon_area(r)


def uv(x: float, y: float) -> tuple[float, float]:
    d = -2 * x + 12 * y + 3
    return 4 * x / d, 9 * y / d


def duv(a, b) -> float:
    (u1, v1), (u2, v2) = uv(*a), uv(*b)
    return math.hypot(u1 - u2, v1 - v2)


def fmt(v: Any, nd: int = 1, unit: str = "") -> str:
    if v is None:
        return "-"
    try:
        return f"{float(v):,.{nd}f}{unit}"
    except (TypeError, ValueError):
        return str(v)


def panel_tone(ax: plt.Axes, p: dict[str, Any]) -> None:
    tr = p.get("tone_response") or {}
    model = tr.get("model_ramp") or "ramp"
    drawn = False
    for key, label, colour, width in RAMP_STYLES:
        ramp = tr.get(key)
        if not ramp:
            continue
        pts = [(c, n) for c, n in ramp if n and n > 0]
        if not pts:
            continue
        pct = tr.get(f"{key}_pct")
        lab = label + (f" ({float(pct):g} %)" if pct else "") + ("  [model]" if key == model else "")
        ax.plot([c for c, _ in pts], [n for _, n in pts], color=colour, lw=width + (0.8 if key == model else 0),
                label=lab, marker="o", ms=2.2)
        drawn = True
    blacks = (p.get("luminance") or {}).get("black_nits") or {}
    for key, label, style in (("in_scene", "in-scene black", "--"), ("full_screen", "full-screen black", ":")):
        v = blacks.get(key)
        if v and v > 0:
            ax.axhline(v, color=MUTED, ls=style, lw=1, label=f"{label} {v:.3g} nits")
    ax.set_yscale("log")
    ax.set_xlim(0, 255)
    ax.set_xlabel("panel drive code (8 bit)")
    ax.set_ylabel("nits")
    ax.set_title("Tone response", loc="left", fontsize=11, weight="bold", color=INK)
    ax.grid(True, which="both", alpha=0.25)
    if drawn:
        ax.legend(fontsize=7, loc="lower right")
    else:
        ax.text(0.5, 0.5, "no ramp in the profile", ha="center", transform=ax.transAxes, color=MUTED)


def panel_gamut(ax: plt.Axes, p: dict[str, Any]) -> None:
    col = p.get("colour") or {}
    prim = col.get("primaries_xy") or {}
    for ref, name, style in ((BT2020, "BT.2020", ":"), (BT709, "BT.709", "--")):
        xs = [ref[c][0] for c in "RGBR"]
        ys = [ref[c][1] for c in "RGBR"]
        ax.plot(xs, ys, color=MUTED, ls=style, lw=1, label=name)
    if all(c in prim for c in "RGB"):
        xs = [prim[c][0] for c in "RGBR"]
        ys = [prim[c][1] for c in "RGBR"]
        ax.plot(xs, ys, color="#0969DA", lw=2, marker="o", ms=4, label="display")
        ax.fill(xs, ys, color="#0969DA", alpha=0.08)
    wxy = (p.get("luminance") or {}).get("white_xy")
    ax.plot(*D65, marker="+", color=INK, ms=9, label="D65")
    if wxy:
        ax.plot(*wxy, marker="x", color="#CF222E", ms=7, label="white")
    ax.set_xlim(0, 0.8)
    ax.set_ylim(0, 0.9)
    ax.set_aspect("equal")
    ax.set_xlabel("x")
    ax.set_ylabel("y")
    ax.set_title("Primaries and white", loc="left", fontsize=11, weight="bold", color=INK)
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=7, loc="upper right")


def panel_peaks(ax: plt.Axes, p: dict[str, Any]) -> None:
    lum = p.get("luminance") or {}
    ts = p.get("type_specific") or {}
    oled = (ts.get("oled") or {}).get("abl") or {}
    if (p.get("display") or {}).get("type") == "oled" and oled.get("apl_pct_to_peak"):
        pts = sorted((float(a), float(n)) for a, n in oled["apl_pct_to_peak"])
        ax.plot([a for a, _ in pts], [n for _, n in pts], color="#0969DA", marker="o", ms=3)
        ax.set_xlabel("APL (%)")
        ax.set_title("Peak by APL (ABL)", loc="left", fontsize=11, weight="bold", color=INK)
    else:
        peaks = lum.get("peak_nits_by_window_pct") or {}
        pts = sorted((float(w), float(n)) for w, n in peaks.items())
        if pts:
            ax.plot([w for w, _ in pts], [n for _, n in pts], color="#0969DA", marker="o", ms=3)
            ax.set_xscale("log")
            if (p.get("display") or {}).get("type") == "edgelit":
                # one global backlight: the table should read as the flat line it is, not as
                # autoscaled meter noise
                ax.set_ylim(0, max(n for _, n in pts) * 1.15)
        ax.set_xlabel("window (% of the screen area)")
        ax.set_title("Peak by window size", loc="left", fontsize=11, weight="bold", color=INK)
    ax.set_ylabel("nits")
    ax.grid(True, which="both", alpha=0.25)


def state_lines(d: dict[str, Any], st: dict[str, Any]) -> list[str]:
    tail = (f"warm-up {st.get('warmup_min')} min, "
            f"player {st.get('signal_path')} (offset {st.get('player_code_offset')})")
    vcp = (st.get("display_settings") or {}).get("vcp") if isinstance(st.get("display_settings"), dict) else None
    if d.get("type") == "edgelit" and vcp:
        # an HDMI monitor: its settings are its VCPs (DDC/CI)
        g = lambda k: (vcp.get(k) or {}).get("value", "?")
        # two lines: one is wider than the card's text column
        return [f"State (VCP): brightness {g('0x10')}, contrast {g('0x12')}, preset "
                f"{st.get('picture_mode') or (vcp.get('0x14') or {}).get('label') or g('0x14')}, gains "
                f"{g('0x16')}/{g('0x18')}/{g('0x1a')}, sharpness {g('0x87')}",
                "   " + tail]
    return [f"State: backlight {st.get('backlight_percent')} %, local dimming {st.get('local_dimming')}, "
            f"panel {fmt(st.get('panel_temp_c'), 1, ' °C')}, " + tail]


def key_values(p: dict[str, Any]) -> list[str]:
    d = p.get("display") or {}
    st = p.get("state") or {}
    lum = p.get("luminance") or {}
    col = p.get("colour") or {}
    blacks = lum.get("black_nits") or {}
    peaks = lum.get("peak_nits_by_window_pct") or {}
    prim = col.get("primaries_xy") or {}
    tr = p.get("tone_response") or {}
    model = tr.get("model_ramp") or "ramp"
    white = (tr.get(model) or [[255, None]])[-1][1]
    wxy = lum.get("white_xy")
    lines = [
        f"White (model ramp, code 255): {fmt(white, 0, ' nits')}" + (f"   xy {wxy[0]:.4f}, {wxy[1]:.4f}"
                                                                    f"   Δu′v′ to D65 {duv(wxy, D65):.4f}" if wxy else ""),
        "Peak by window: " + ("  ".join(f"{float(w):g} % {float(n):,.0f}" for w, n in
                                        sorted(peaks.items(), key=lambda t: float(t[0]))
                                        if float(w) in (2, 3, 5, 10, 25, 50, 100)) or "-"),
        f"Black: full screen {fmt(blacks.get('full_screen'), 4, ' nits')}   in scene "
        f"{fmt(blacks.get('in_scene'), 4, ' nits')}" + (f" ({blacks.get('in_scene_source')})" if blacks.get("in_scene") else ""),
        "Primaries: " + "  ".join(f"{c} {prim[c][0]:.4f}, {prim[c][1]:.4f}" for c in "RGB" if c in prim),
        f"Coverage of BT.709 {fmt((coverage(prim, BT709) or 0) * 100, 1, ' %')}   of BT.2020 "
        f"{fmt((coverage(prim, BT2020) or 0) * 100, 1, ' %')}   additivity error {fmt(col.get('additivity_error_pct'), 2, ' %')}",
        *state_lines(d, st),
    ]
    loc = next((m for m in p.get("measurements") or [] if m.get("kind") == "sensor-location"), None)
    if loc:
        lines.append(f"Sensor: {loc.get('offset_mm') or loc.get('offset_px')} {'mm' if loc.get('offset_mm') else 'px'} "
                     f"from the centre, footprint {fmt(loc.get('footprint_px'), 0, ' px')}")
    return lines


def render_profile_card(profile: dict[str, Any], output: Path, notes: list[str] | None = None,
                        dpi: int = 200, title: str = "HDR Display Profile") -> None:
    d = profile.get("display") or {}
    fig = plt.figure(figsize=A4_LANDSCAPE_INCHES, dpi=dpi)
    fig.patch.set_facecolor("white")
    serial = d.get("serial") or "-"
    fig.text(0.03, 0.965, f"{title}: {d.get('model', '?')}  {serial}", fontsize=16, weight="bold", color=INK, va="top")
    fig.text(0.03, 0.928, f"{profile.get('id')}   type {d.get('type')}   created {profile.get('created')}"
             + ("   approximate" if profile.get("approximate") else ""), fontsize=9, color=MUTED, va="top")
    grid = fig.add_gridspec(2, 3, left=0.06, right=0.98, top=0.88, bottom=0.07, hspace=0.38, wspace=0.32,
                            height_ratios=[1.15, 1])
    panel_tone(fig.add_subplot(grid[0, 0:2]), profile)
    panel_gamut(fig.add_subplot(grid[0, 2]), profile)
    panel_peaks(fig.add_subplot(grid[1, 0]), profile)
    tx = fig.add_subplot(grid[1, 1:3])
    tx.axis("off")
    y = 1.0
    for line in key_values(profile):
        tx.text(0, y, line, fontsize=8.2, color=INK, va="top", transform=tx.transAxes)
        y -= 0.075
    warn = [w for w in (profile.get("warnings") or [])]
    extra = [n for n in (notes or []) if n.strip()]
    if warn or extra:
        y -= 0.02
        tx.text(0, y, f"Warnings ({len(warn)})" + (" and assumed values" if extra else ""), fontsize=8.6,
                weight="bold", color="#9A6700", va="top", transform=tx.transAxes)
        y -= 0.07
        for w in (warn + extra)[:12]:
            for i, part in enumerate(textwrap.wrap(w, 120)[:3]):
                tx.text(0, y, ("• " if i == 0 else "   ") + part, fontsize=6.8, color=INK, va="top",
                        transform=tx.transAxes)
                y -= 0.052
            if y < 0:
                break
    stamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S %Z").strip()
    fig.text(0.992, 0.006, f"Serial: {serial} | Generated: {stamp}", ha="right", va="bottom", fontsize=6, color=MUTED)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=dpi, facecolor="white")
    plt.close(fig)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Render a display profile card PNG.")
    ap.add_argument("--display-profile", required=True, type=Path)
    ap.add_argument("--output", type=Path, default=None)
    ap.add_argument("--notes-file", type=Path, default=None,
                    help="extra lines for the warnings block (make-display-profile.py --validate output)")
    ap.add_argument("--dpi", type=int, default=200)
    ap.add_argument("--title", default="HDR Display Profile")
    a, _ = ap.parse_known_args(argv)
    try:
        profile = json.loads(a.display_profile.read_text())
    except (OSError, ValueError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1
    notes = None
    if a.notes_file:
        try:
            notes = [l.rstrip() for l in a.notes_file.read_text().splitlines()]
        except OSError as ex:
            print(f"warning: {ex}", file=sys.stderr)
    out = a.output or a.display_profile.with_suffix(".png")
    render_profile_card(profile, out, notes, a.dpi, a.title)
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
