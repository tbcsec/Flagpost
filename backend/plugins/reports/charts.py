"""Pure-Python SVG chart builders for post-event reports (#134, ADR-0030).

Deterministic, dependency-free SVG (no JS, no matplotlib) so WeasyPrint renders
the same bytes every time and the HTML deliverable needs no client runtime.

Security: only derived/numeric text (dates, counts, percentages) is ever drawn
inside the SVG. Every user-supplied label (team name, category, challenge title)
is rendered as autoescaped HTML in the template legend — never here — so these
builders can't carry an injection even though the template emits them with
``| safe``.
"""

from __future__ import annotations

from typing import Sequence

_W = 640  # logical canvas width; scales to the container via viewBox


def _n(v: float) -> str:
    """Compact coordinate: trim trailing zeros so the SVG stays small and stable."""
    return f"{v:.2f}".rstrip("0").rstrip(".")


def _x_positions(count: int, left: float, right: float) -> list[float]:
    if count <= 1:
        return [(left + right) / 2]
    step = (right - left) / (count - 1)
    return [left + i * step for i in range(count)]


def area(labels: Sequence[str], values: Sequence[float], color: str) -> str:
    """A single cumulative line with a soft area fill (e.g. solves over time)."""
    if not values:
        return ""
    h, top, bottom, left, right = 200, 16, 168, 8, _W - 8
    peak = max(values) or 1
    xs = _x_positions(len(values), left, right)
    ys = [bottom - (v / peak) * (bottom - top) for v in values]
    line = " ".join(f"{'M' if i == 0 else 'L'}{_n(x)},{_n(y)}" for i, (x, y) in enumerate(zip(xs, ys)))
    area_path = f"{line} L{_n(xs[-1])},{_n(bottom)} L{_n(xs[0])},{_n(bottom)} Z"
    dots = "".join(f'<circle cx="{_n(x)}" cy="{_n(y)}" r="3" fill="{color}"/>' for x, y in zip(xs, ys))
    return (
        f'<svg viewBox="0 0 {_W} {h}" role="img" xmlns="http://www.w3.org/2000/svg">'
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#e4e7ec"/>'
        f'<path d="{area_path}" fill="{color}" fill-opacity="0.10"/>'
        f'<path d="{line}" fill="none" stroke="{color}" stroke-width="2.2" '
        f'stroke-linejoin="round" stroke-linecap="round"/>{dots}'
        f"{_x_axis(labels, xs, bottom + 20)}</svg>"
    )


def lines(series: Sequence[Sequence[float]], colors: Sequence[str]) -> str:
    """Several cumulative lines sharing one x-axis (e.g. a top-N score race).

    Legends (which line is whose) are rendered as HTML by the caller."""
    flat = [v for s in series for v in s]
    if not flat:
        return ""
    h, top, bottom, left, right = 200, 16, 168, 8, _W - 8
    peak = max(flat) or 1
    paths = []
    for s, color in zip(series, colors):
        if not s:
            continue
        xs = _x_positions(len(s), left, right)
        ys = [bottom - (v / peak) * (bottom - top) for v in s]
        d = " ".join(f"{'M' if i == 0 else 'L'}{_n(x)},{_n(y)}" for i, (x, y) in enumerate(zip(xs, ys)))
        paths.append(
            f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2.2" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )
    return (
        f'<svg viewBox="0 0 {_W} {h}" role="img" xmlns="http://www.w3.org/2000/svg">'
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#e4e7ec"/>'
        f'{"".join(paths)}</svg>'
    )


def donut(values: Sequence[float], colors: Sequence[str], center_label: str = "") -> str:
    """A ring split by proportion (e.g. solves by category). Uses the pathLength
    trick so each arc length is a plain percentage."""
    total = sum(values)
    if total <= 0:
        return ""
    r, cx, cy, sw = 60, 90, 90, 22
    arcs = []
    offset = 0.0
    # Cycle the palette so EVERY segment gets an arc (a competition can have more
    # categories than colours); the template legend cycles the same way, so arcs
    # and legend swatches stay in sync. Clamp at 0 so a stray negative can never
    # emit an invalid stroke-dasharray.
    for i, v in enumerate(values):
        color = colors[i % len(colors)]
        pct = max(0.0, v / total * 100)
        arcs.append(
            f'<circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="{color}" '
            f'stroke-width="{sw}" pathLength="100" stroke-dasharray="{_n(pct)} {_n(100 - pct)}" '
            f'stroke-dashoffset="{_n(-offset)}"/>'
        )
        offset += pct
    label = (
        f'<text x="{cx}" y="{cy + 5}" text-anchor="middle" font-size="22" '
        f'font-weight="700" fill="#191c24">{center_label}</text>'
        if center_label
        else ""
    )
    return (
        f'<svg viewBox="0 0 180 180" role="img" xmlns="http://www.w3.org/2000/svg">'
        f'<g transform="rotate(-90 {cx} {cy})">{"".join(arcs)}</g>{label}</svg>'
    )


def heatmap(hours: Sequence[int], color: str) -> str:
    """24 cells, one per hour of day, opacity scaled to volume."""
    if not hours or max(hours) == 0:
        return ""
    peak = max(hours)
    cell, gap = 22, 4
    rects = []
    for i, v in enumerate(hours):
        x = i * (cell + gap) + 8
        op = 0.06 + 0.94 * (v / peak)
        rects.append(
            f'<rect x="{x}" y="16" width="{cell}" height="34" rx="3" '
            f'fill="{color}" fill-opacity="{_n(op)}"/>'
        )
    width = 24 * (cell + gap) + 16
    marks = (
        f'<g fill="#9aa1ad" font-size="10" font-family="monospace">'
        f'<text x="8" y="66">00:00</text>'
        f'<text x="{width / 2 - 20:.0f}" y="66">12:00</text>'
        f'<text x="{width - 44:.0f}" y="66">23:00</text></g>'
    )
    return (
        f'<svg viewBox="0 0 {width} 76" role="img" xmlns="http://www.w3.org/2000/svg">'
        f'{"".join(rects)}{marks}</svg>'
    )


def histogram(counts: Sequence[int], color: str) -> str:
    """Vertical bars (e.g. score distribution across bins)."""
    if not counts or max(counts) == 0:
        return ""
    peak = max(counts)
    n = len(counts)
    h, top, bottom, left, right = 160, 12, 130, 8, _W - 8
    slot = (right - left) / n
    bw = slot * 0.72
    bars = []
    for i, c in enumerate(counts):
        bh = (c / peak) * (bottom - top)
        x = left + i * slot + (slot - bw) / 2
        y = bottom - bh
        bars.append(
            f'<rect x="{_n(x)}" y="{_n(y)}" width="{_n(bw)}" height="{_n(bh)}" rx="2" fill="{color}"/>'
        )
    return (
        f'<svg viewBox="0 0 {_W} {h}" role="img" xmlns="http://www.w3.org/2000/svg">'
        f'<line x1="{left}" y1="{bottom}" x2="{right}" y2="{bottom}" stroke="#e4e7ec"/>'
        f'{"".join(bars)}</svg>'
    )


def _x_axis(labels: Sequence[str], xs: Sequence[float], y: float) -> str:
    """First / middle / last tick labels only, to avoid crowding."""
    if not labels:
        return ""
    picks = {0, len(labels) // 2, len(labels) - 1}
    ticks = "".join(
        f'<text x="{_n(xs[i])}" y="{_n(y)}" text-anchor="middle" font-size="10" '
        f'fill="#9aa1ad" font-family="monospace">{labels[i]}</text>'
        for i in sorted(picks)
    )
    return f"<g>{ticks}</g>"
