#!/usr/bin/env python3
"""
Digonto - competition figure generator.

Regenerates every figure in the media gallery for the Kaggle writeup
(paper/kaggle_writeup.md) from this one script. Pure matplotlib: no seaborn,
no external images, no network access. Deterministic output.

Run:
    python3 make_figures.py

Output:
    docs/figures/out/fig01_problem_scale.png ... fig11_cost_model.png
    docs/figures/README.md  (captions, widths, measured/illustrative labels)

Style rules (binding, from writing_instructions.md Part 3):
  - Palette: Blue #2563EB, Orange #E8710A, Green #059669, Neutral grey #6B7280,
    text #111827, gridlines #E5E7EB. One palette across every figure; a series
    keeps the same colour everywhere it recurs.
  - Flat 2D only. No drop shadows, no gradients, no 3D, no decorative
    backgrounds. White background, no transparency.
  - Type: Arial / Helvetica / DejaVu Sans. Titles and primary labels 9.5 pt,
    everything else 9 pt. Nothing smaller, ever.
  - Design at true print width: IEEE single column 3.5 in, double column
    7.16 in. Export 300 dpi PNG, white background.
  - Must read correctly in greyscale: lightness varies between series and
    values are labelled directly, never relying on hue alone.
  - Every caption states what is shown, the conditions, and marks MEASURED
    versus ILLUSTRATIVE. Most numbers in this project are design targets, not
    results, and the captions say so plainly.

Colour-to-meaning mapping held constant across all eleven figures:
    BLUE   fast loop / primary series / "Tools" capability / applications
    ORANGE recurrent loop / refused or rejected outcome / "Vision" capability
    GREEN  continual loop / registered-verified / promoted or answered /
           "Audio" capability
    GREY   storage / neutral system state / cold (uncached) state /
           "Thinking" capability
"""

import os
import textwrap

import numpy as np
import matplotlib as mpl

mpl.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from matplotlib.patches import FancyBboxPatch, FancyArrowPatch, Rectangle

# ---------------------------------------------------------------------------
# Binding palette (writing_instructions.md Part 3.3)
# ---------------------------------------------------------------------------
BLUE = "#2563EB"
ORANGE = "#E8710A"
GREEN = "#059669"
GREY = "#6B7280"
TEXT = "#111827"
GRID = "#E5E7EB"
WHITE = "#FFFFFF"

# ---------------------------------------------------------------------------
# Binding matplotlib settings block (writing_instructions.md Part 3.6)
# ---------------------------------------------------------------------------
mpl.rcParams.update({
    "font.family": "sans-serif",
    "font.sans-serif": ["Arial", "Helvetica", "DejaVu Sans"],
    "font.size": 9,          # matches the 9-9.5 pt band of a 9.5 pt body
    "axes.titlesize": 9.5,
    "axes.labelsize": 9,
    "xtick.labelsize": 9,
    "ytick.labelsize": 9,
    "legend.fontsize": 9,
    "savefig.dpi": 300,
    "figure.facecolor": "white",
})
# Supporting settings kept out of the shared block above because they are
# colour/geometry, not typography, but still apply to every figure.
mpl.rcParams["axes.edgecolor"] = TEXT
mpl.rcParams["text.color"] = TEXT
mpl.rcParams["axes.labelcolor"] = TEXT
mpl.rcParams["xtick.color"] = TEXT
mpl.rcParams["ytick.color"] = TEXT
mpl.rcParams["axes.unicode_minus"] = False

SINGLE_COL = 3.5   # IEEE single column, inches
DOUBLE_COL = 7.16  # IEEE double column, inches

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(HERE, "out")
os.makedirs(OUT_DIR, exist_ok=True)

# Agent names are rendered in English only in the images. DejaVu Sans (the
# fallback in the binding font stack) has no Bengali glyphs, so Bangla script
# would render as missing-glyph boxes. Bangla names stay in the surrounding
# prose (README.md, kaggle_writeup.md) where a Bengali-capable font is used.


# ---------------------------------------------------------------------------
# Small shared helpers
# ---------------------------------------------------------------------------
def save(fig, name):
    path = os.path.join(OUT_DIR, name + ".png")
    fig.savefig(path, dpi=300, facecolor="white", edgecolor="none")
    plt.close(fig)
    # Flatten to plain RGB: matplotlib's PNG writer always includes an alpha
    # channel (fully opaque here), but the style spec calls for "no
    # transparency", so drop the channel entirely rather than rely on alpha
    # being 255 everywhere.
    from PIL import Image
    im = Image.open(path).convert("RGB")
    im.save(path)
    size_kb = os.path.getsize(path) / 1024
    print(f"  wrote {name}.png  ({size_kb:.0f} KB)")
    return path


def clean_axes(ax, grid_axis="y"):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)
    for s in ("left", "bottom"):
        ax.spines[s].set_linewidth(0.7)
        ax.spines[s].set_color(TEXT)
    ax.tick_params(width=0.7, colors=TEXT, length=3)
    if grid_axis:
        ax.grid(axis=grid_axis, color=GRID, linewidth=0.7, zorder=0)
    ax.set_axisbelow(True)


def schem_ax(fig, rect=(0.015, 0.02, 0.97, 0.90)):
    """A full-figure axis in normalised 0-1 x 0-1 data coordinates, used for
    every hand-built schematic (no seaborn, no external drawing tool)."""
    ax = fig.add_axes(rect)
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    return ax


def axes_aspect(fig, ax):
    """height_in / width_in of the axes' physical box, so a square drawn in
    data units (0-1 x 0-1) actually renders square regardless of figure
    aspect ratio."""
    bbox = ax.get_position()
    w_in = bbox.width * fig.get_figwidth()
    h_in = bbox.height * fig.get_figheight()
    return h_in / w_in


def box(ax, cx, cy, w, h, label, fc, tc=WHITE, fs=9, weight="normal",
        ec=None, ls="solid", lw=1.1, zorder=3):
    ec = ec or fc
    p = FancyBboxPatch((cx - w / 2, cy - h / 2), w, h,
                        boxstyle="round,pad=0.0,rounding_size=0.012",
                        linewidth=lw, edgecolor=ec, facecolor=fc,
                        linestyle=ls, zorder=zorder)
    ax.add_patch(p)
    ax.text(cx, cy, label, ha="center", va="center", fontsize=fs,
            color=tc, weight=weight, zorder=zorder + 1, linespacing=1.3)
    return p


def arrow(ax, p1, p2, color=TEXT, lw=1.1, mutation=8, rad=0.0, zorder=2):
    a = FancyArrowPatch(p1, p2, arrowstyle="-|>", mutation_scale=mutation,
                         linewidth=lw, color=color, zorder=zorder,
                         connectionstyle=f"arc3,rad={rad}",
                         shrinkA=0, shrinkB=0)
    ax.add_patch(a)
    return a


def swatch(ax, x, y, color, label, fs=9):
    ax.add_patch(Rectangle((x, y - 0.011), 0.022, 0.022, facecolor=color,
                            edgecolor="none", zorder=3))
    ax.text(x + 0.03, y, label, ha="left", va="center", fontsize=fs, color=TEXT)


# ---------------------------------------------------------------------------
# Figure 1 - problem scale (double column, MEASURED)
# ---------------------------------------------------------------------------
def fig01_problem_scale():
    fig = plt.figure(figsize=(DOUBLE_COL, 4.5))
    fig.suptitle("Scale of the problem Digonto addresses (Bangladesh, verified statistics)",
                 fontsize=9.5, weight="semibold", color=TEXT, y=0.99)
    gs = fig.add_gridspec(2, 2, left=0.06, right=0.97, top=0.86, bottom=0.09,
                           wspace=0.30, hspace=0.60)

    # Panel A: students abroad
    axA = fig.add_subplot(gs[0, 0])
    axA.axis("off")
    axA.add_patch(Rectangle((0.0, 0.88), 1.0, 0.05, facecolor=BLUE, edgecolor="none"))
    axA.text(0.5, 0.53, "52,799", ha="center", va="center", fontsize=21,
              weight="bold", color=BLUE)
    axA.text(0.5, 0.18, "Bangladeshi students abroad, 2023\nacross 55 countries",
              ha="center", va="center", fontsize=9, color=TEXT)

    # Panel B: FY25 outflow
    axB = fig.add_subplot(gs[0, 1])
    axB.axis("off")
    axB.add_patch(Rectangle((0.0, 0.88), 1.0, 0.05, facecolor=GREY, edgecolor="none"))
    axB.text(0.5, 0.53, "$667.77M", ha="center", va="center", fontsize=21,
              weight="bold", color=GREY)
    axB.text(0.5, 0.18, "Overseas education outflow, FY25\n109,290 banking transactions",
              ha="center", va="center", fontsize=9, color=TEXT)

    # Panel C: consultancy oversight gap
    axC = fig.add_subplot(gs[1, 0])
    cats = ["Operating (all)", "Registered with\nsector association"]
    vals = [2000, 400]
    colors = [GREY, GREEN]
    y = np.arange(2)
    axC.barh(y, vals, color=colors, height=0.5, zorder=3)
    for yi, v in zip(y, vals):
        axC.text(v + 45, yi, f"~{v:,}", va="center", ha="left", fontsize=9, color=TEXT)
        # category name labelled directly inside the bar (avoids clipping
        # long y-tick labels off the left edge of the panel)
    axC.text(40, 0, cats[0], va="center", ha="left", fontsize=9, color="white")
    axC.text(40, 1, cats[1], va="center", ha="left", fontsize=9, color="white",
              linespacing=1.3)
    axC.set_yticks([])
    axC.invert_yaxis()
    axC.set_xlim(0, 2500)
    axC.set_xticks([])
    for s in ("top", "right", "bottom", "left"):
        axC.spines[s].set_visible(False)
    axC.tick_params(left=False)
    axC.set_title("Consultancy firms, Bangladesh", fontsize=9.5, color=TEXT, pad=6)

    # Panel D: Schengen refusal rate, 2023 vs 2024
    axD = fig.add_subplot(gs[1, 1])
    years = ["2023", "2024"]
    rate_vals = [42.8, 54.90]
    rate_labels = ["42.8%", "54.90%"]
    xpos = np.arange(2)
    axD.bar(xpos, rate_vals, color=ORANGE, width=0.5, zorder=3)
    for xi, v, rl in zip(xpos, rate_vals, rate_labels):
        axD.text(xi, v + 2.0, rl, ha="center", va="bottom", fontsize=9,
                  weight="bold", color=TEXT)
    axD.set_xticks(xpos)
    axD.set_xticklabels(years, fontsize=9)
    axD.set_ylim(0, 68)
    axD.set_yticks([])
    for s in ("top", "right", "left"):
        axD.spines[s].set_visible(False)
    axD.tick_params(left=False)
    axD.set_title("Schengen visa refusal rate, Bangladesh", fontsize=9.5, color=TEXT, pad=6)

    title = "Bangladesh outbound study market: scale of the problem"
    caption = (
        "Four verified statistics on the market Digonto addresses. Top left: "
        "52,799 Bangladeshi students studied abroad in 2023, across 55 "
        "countries. Top right: families paid 667.77 million US dollars for "
        "overseas education in FY25, a record for a single year, across "
        "109,290 banking transactions. Bottom left: an estimated 2,000 "
        "consultancy firms operate in Bangladesh, of which only about 400 are "
        "registered with the sector association; the rest hold no specialised "
        "supervision. Bottom right: the Schengen visa refusal rate for "
        "Bangladeshi applicants rose from 42.8 percent in 2023 to 54.90 "
        "percent in 2024. MEASURED: every number is transcribed unchanged from "
        "README.md, which cites the original sources (UNESCO, Bangladesh Bank, "
        "the consultancy sector association, and Schengen visa statistics); "
        "none is derived or estimated for this figure."
    )
    return dict(name="fig01_problem_scale", title=title, caption=caption,
                width=DOUBLE_COL, measured=True, path=save(fig, "fig01_problem_scale"))


# ---------------------------------------------------------------------------
# Figure 2 - Schengen applications vs refusals, 2023/2024 (single col, MEASURED)
# ---------------------------------------------------------------------------
def fig02_refusal_trend():
    fig = plt.figure(figsize=(SINGLE_COL, 3.35))
    ax = fig.add_axes([0.17, 0.15, 0.80, 0.66])

    years = ["2023", "2024"]
    apps = [41317, 39345]
    refused = [17015, 20957]
    x = np.arange(2)
    w = 0.34
    ax.bar(x - w / 2, apps, w, color=BLUE, label="Applications", zorder=3)
    ax.bar(x + w / 2, refused, w, color=ORANGE, label="Refused", zorder=3)

    for xi, v in zip(x - w / 2, apps):
        ax.text(xi, v + 1000, f"{v:,}", ha="center", va="bottom", fontsize=9, color=TEXT)
    for xi, v in zip(x + w / 2, refused):
        ax.text(xi, v + 1000, f"{v:,}", ha="center", va="bottom", fontsize=9, color=TEXT)

    rate_labels = ["refusal rate\n42.8%", "refusal rate\n54.90%"]
    for xi, rl in zip(x, rate_labels):
        ax.text(xi, 46500, rl, ha="center", va="bottom", fontsize=9, weight="bold", color=TEXT)

    ax.set_xticks(x)
    ax.set_xticklabels(years)
    ax.set_ylim(0, 56000)
    ax.set_ylabel("Number of applications")
    ax.set_title("Schengen visa applications and refusals, Bangladesh", pad=8)
    clean_axes(ax, grid_axis="y")
    ax.legend(frameon=False, loc="upper left")

    title = "Schengen applications and refusals, Bangladesh, 2023-2024"
    caption = (
        "Bangladeshi Schengen visa applications (blue) and refusals (orange), "
        "2023 and 2024, with the refusal rate labelled directly above each "
        "year. 2023: 41,317 applications, 17,015 refused. 2024: 39,345 "
        "applications, 20,957 refused. MEASURED, from README.md's cited "
        "Schengen visa statistics. Note: the refusal rate is quoted exactly "
        "as officially reported (42.8 percent, 54.90 percent); dividing the "
        "refused count shown here by the application count shown here gives "
        "a slightly lower figure (about 41 percent and 53 percent), most "
        "likely because the official rate uses a different denominator or "
        "reporting period than the two headline counts. Both figures are "
        "reproduced unchanged from the source rather than reconciled by us. "
        "Takeaway: the refusal rate rose by more than 12 percentage points "
        "in a single year."
    )
    return dict(name="fig02_refusal_trend", title=title, caption=caption,
                width=SINGLE_COL, measured=True, path=save(fig, "fig02_refusal_trend"))


# ---------------------------------------------------------------------------
# Figure 3 - RC-RAG three-loop architecture (double col, ILLUSTRATIVE)
# ---------------------------------------------------------------------------
def fig03_rcrag_loops():
    fig = plt.figure(figsize=(DOUBLE_COL, 4.7))
    fig.suptitle("RC-RAG: three loops of different speed around one Gemma 4 E2B model",
                 fontsize=9.5, weight="semibold", color=TEXT, y=0.99)
    ax = schem_ax(fig, rect=(0.015, 0.02, 0.97, 0.88))

    # ---- Recurrent loop (top, orange) ----
    ax.text(0.005, 0.965, "RECURRENT LOOP · hours", fontsize=9.5, weight="semibold",
            color=ORANGE, va="center")
    ry = 0.855
    rboxes = ["Official\nportals", "Crawl +\nhash check", "Diff changed\npassages", "Re-embed\ndiffs only"]
    rx = [0.10, 0.30, 0.50, 0.70]
    for cx, lbl in zip(rx, rboxes):
        box(ax, cx, ry, 0.155, 0.155, lbl, ORANGE, fs=9)
    for i in range(len(rx) - 1):
        arrow(ax, (rx[i] + 0.078, ry), (rx[i + 1] - 0.078, ry))

    # ---- Shared storage (grey) ----
    kb_cx, kb_cy = 0.50, 0.615
    box(ax, kb_cx, kb_cy, 0.24, 0.10, "Versioned knowledge store", GREY, fs=9)
    arrow(ax, (rx[-1], ry - 0.078), (kb_cx + 0.03, kb_cy + 0.05), rad=0.15)

    # ---- Fast loop (middle, blue) ----
    ax.text(0.005, 0.50, "FAST LOOP · milliseconds", fontsize=9.5, weight="semibold",
            color=BLUE, va="center")
    fy = 0.40
    fboxes = ["Student\nquestion", "Semantic\ncache hit?", "Hybrid retrieval\ndense + BM25",
              "Gemma 4 E2B\ngenerate, schema", "Cited answer\nor refusal"]
    fx = [0.09, 0.28, 0.47, 0.665, 0.87]
    fcolors = [BLUE, GREY, BLUE, BLUE, BLUE]
    for cx, lbl, c in zip(fx, fboxes, fcolors):
        ls = "dashed" if c == GREY else "solid"
        box(ax, cx, fy, 0.15, 0.155, lbl, c, fs=9, ls=ls)
    for i in range(len(fx) - 1):
        if i == 1:
            continue  # cache decision drawn separately below
        arrow(ax, (fx[i] + 0.075, fy), (fx[i + 1] - 0.075, fy))
    arrow(ax, (fx[0] + 0.075, fy), (fx[1] - 0.075, fy))
    arrow(ax, (fx[1] + 0.075, fy + 0.02), (fx[2] - 0.075, fy + 0.02))
    ax.text((fx[1] + fx[2]) / 2, fy + 0.06, "miss", fontsize=9, color=TEXT, ha="center")
    arrow(ax, (fx[1], fy - 0.078), (fx[4], fy - 0.078), rad=-0.25)
    ax.text((fx[1] + fx[4]) / 2, fy - 0.155, "hit", fontsize=9, color=TEXT, ha="center")
    arrow(ax, (kb_cx - 0.03, kb_cy - 0.05), (fx[2], fy + 0.078), rad=0.15)

    # ---- Continual loop (bottom, green) ----
    ax.text(0.005, 0.145, "CONTINUAL LOOP · weeks", fontsize=9.5, weight="semibold",
            color=GREEN, va="center")
    cy = 0.045
    cboxes = ["Replay buffer\nrefusals + corr.", "Rehearsal mix\ntrain adapter",
              "Gate 1\nfrozen benchmark", "Gate 2\nhuman reviewer", "Promote / roll back\nhot swap"]
    cx_ = [0.09, 0.28, 0.47, 0.665, 0.87]
    for cx, lbl in zip(cx_, cboxes):
        box(ax, cx, cy, 0.155, 0.155, lbl, GREEN, fs=9)
    for i in range(len(cx_) - 1):
        arrow(ax, (cx_[i] + 0.078, cy), (cx_[i + 1] - 0.078, cy))

    arrow(ax, (fx[4], fy - 0.078), (cx_[0], cy + 0.078), rad=0.2)
    ax.text((fx[4] + cx_[0]) / 2 + 0.02, (fy + cy) / 2, "refusals +\ncorrections",
            fontsize=9, color=TEXT, ha="left", va="center")
    arrow(ax, (cx_[-1], cy + 0.078), (fx[3], fy - 0.078), rad=-0.28)
    ax.text((cx_[-1] + fx[3]) / 2 - 0.03, (fy + cy) / 2 - 0.06, "hot swap",
            fontsize=9, color=TEXT, ha="right", va="center")

    title = "RC-RAG three-loop architecture"
    caption = (
        "Schematic of Recurrent Continual RAG (RC-RAG): three loops of "
        "different speed around one served Gemma 4 E2B model. Fast loop "
        "(blue, per query): a semantic cache check, then hybrid dense and "
        "BM25 retrieval, schema-constrained generation, and a cited answer or "
        "an explicit refusal. Recurrent loop (orange, scheduled crawling): "
        "portals are hash-checked, changed pages are diffed at passage level, "
        "and only the diffs are re-embedded into a new store version. "
        "Continual loop (green, every 2 to 4 weeks): refusals and corrections "
        "train a QLoRA adapter that must pass a frozen benchmark and a human "
        "reviewer, in series, before it replaces the running model. The "
        "versioned knowledge store (grey) is the shared state the fast loop "
        "reads and the recurrent loop writes. ILLUSTRATIVE: this is an "
        "architecture schematic, not a data plot; box shapes and positions "
        "carry no quantitative meaning."
    )
    return dict(name="fig03_rcrag_loops", title=title, caption=caption,
                width=DOUBLE_COL, measured=False, path=save(fig, "fig03_rcrag_loops"))


# ---------------------------------------------------------------------------
# Figure 4 - one event, four consumers (single col, ILLUSTRATIVE)
# ---------------------------------------------------------------------------
def fig04_event_fanout():
    fig = plt.figure(figsize=(SINGLE_COL, 3.35))
    fig.suptitle("One event, four consumers", fontsize=9.5, weight="semibold",
                 color=TEXT, y=0.98)
    ax = schem_ax(fig, rect=(0.015, 0.02, 0.97, 0.86))

    ev_cx, ev_cy = 0.5, 0.82
    box(ax, ev_cx, ev_cy, 0.42, 0.16, "event:\nportal.changed", ORANGE, fs=9, weight="semibold")

    consumers = [
        "Knowledge store\nupdate",
        "Semantic cache\ninvalidation",
        "Timeline re-planning\nfor affected students",
        "Bangla alert\nquoted + cited",
    ]
    cxs = [0.135, 0.385, 0.635, 0.885]
    cy = 0.24
    for cx, lbl in zip(cxs, consumers):
        box(ax, cx, cy, 0.225, 0.28, lbl, GREY, fs=9)
        arrow(ax, (ev_cx, ev_cy - 0.08), (cx, cy + 0.14), rad=0.0)

    title = "portal.changed event fan-out to four consumers"
    caption = (
        "The single event portal.changed reaches four independent consumers: "
        "the knowledge store update, semantic cache invalidation, timeline "
        "re-planning for every affected student, and a Bangla alert quoting "
        "and citing the changed passage. This one-to-many fan-out is the "
        "specific reason the backend is event-driven on Redis Streams rather "
        "than request-driven. ILLUSTRATIVE: an architecture schematic, not a "
        "data plot."
    )
    return dict(name="fig04_event_fanout", title=title, caption=caption,
                width=SINGLE_COL, measured=False, path=save(fig, "fig04_event_fanout"))


# ---------------------------------------------------------------------------
# Figure 5 - two promotion gates in series (double col, ILLUSTRATIVE)
# ---------------------------------------------------------------------------
def fig05_promotion_gates():
    fig = plt.figure(figsize=(DOUBLE_COL, 2.9))
    fig.suptitle("Two promotion gates in series before an adapter reaches students",
                 fontsize=9.5, weight="semibold", color=TEXT, y=0.97)
    ax = schem_ax(fig, rect=(0.015, 0.03, 0.97, 0.82))

    y0 = 0.52
    box(ax, 0.09, y0, 0.15, 0.22, "Trained\nadapter", BLUE, fs=9)
    box(ax, 0.335, y0, 0.19, 0.22, "Gate 1\nfrozen benchmark", GREY, fs=9, ls="dashed")
    box(ax, 0.60, y0, 0.19, 0.22, "Gate 2\nhuman reviewer", GREY, fs=9, ls="dashed")
    box(ax, 0.87, 0.76, 0.20, 0.20, "Promote\nhot swap", GREEN, fs=9)
    box(ax, 0.87, 0.24, 0.20, 0.20, "Roll back", ORANGE, fs=9)

    arrow(ax, (0.165, y0), (0.24, y0))
    arrow(ax, (0.43, y0), (0.505, y0))
    ax.text((0.43 + 0.505) / 2, y0 + 0.05, "passes", fontsize=9, color=TEXT, ha="center")
    arrow(ax, (0.695, y0), (0.77, 0.72), rad=-0.12)
    ax.text(0.735, y0 + 0.12, "approved", fontsize=9, color=TEXT, ha="left")
    arrow(ax, (0.335, y0 - 0.11), (0.80, 0.27), rad=-0.22)
    ax.text(0.52, 0.30, "fails", fontsize=9, color=TEXT, ha="center")
    arrow(ax, (0.695, y0 - 0.06), (0.78, 0.28), rad=0.18)
    ax.text(0.72, 0.40, "rejected", fontsize=9, color=TEXT, ha="left")

    title = "Adapter promotion, two gates in series"
    caption = (
        "A trained QLoRA adapter is promoted only after two gates in series. "
        "Gate 1 is a frozen 200-question Bangla benchmark: the adapter must "
        "pass with no metric regressing by more than one point. Gate 2 is a "
        "human reviewer. Failing either gate rolls the adapter back; only an "
        "adapter that passes both is hot-swapped into the running model. "
        "ILLUSTRATIVE: a protocol schematic, not a data plot; no benchmark "
        "scores are shown because none have been measured yet."
    )
    return dict(name="fig05_promotion_gates", title=title, caption=caption,
                width=DOUBLE_COL, measured=False, path=save(fig, "fig05_promotion_gates"))


# ---------------------------------------------------------------------------
# Figure 6 - measured latency, development machine (single col, MEASURED)
# ---------------------------------------------------------------------------
def fig06_latency_measured():
    # Wider than a single column and taller than the default: the earlier
    # version clipped its own title and collided the callout with a bar label.
    fig = plt.figure(figsize=(DOUBLE_COL * 0.62, 3.6))
    ax = fig.add_axes([0.17, 0.24, 0.79, 0.52])

    labels = ["Cold\nload", "Warm\ntool call", "Warm\nrefusal", "Warm grounded\nanswer"]
    values = [24318, 1163, 1908, 5128]
    colors = [GREY, BLUE, BLUE, BLUE]
    x = np.arange(len(values))
    ax.bar(x, values, color=colors, width=0.58, zorder=3)
    ax.set_yscale("log")
    # Headroom above the tallest bar so the value label never meets the title.
    ax.set_ylim(600, 60000)

    for xi, v in zip(x, values):
        ax.text(xi, v * 1.16, f"{v:,} ms", ha="center", va="bottom",
                fontsize=9, color=TEXT)

    ax.set_xticks(x)
    ax.set_xticklabels(labels, fontsize=9)
    ax.set_ylabel("Latency, milliseconds (log scale)", fontsize=9)
    ax.set_title("Measured response latency, development machine",
                 fontsize=9.5, pad=14)
    clean_axes(ax, grid_axis="y")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{int(v):,}"))
    ax.set_yticks([1000, 3000, 10000, 30000])

    # The callout sits between the two bars it compares, below the value
    # labels rather than through them.
    ax.annotate(
        "", xy=(0.82, 2600), xytext=(0.18, 17000),
        arrowprops=dict(arrowstyle="->", color=TEXT, lw=1.0,
                        connectionstyle="arc3,rad=-0.25"),
    )
    ax.text(0.5, 6200, "20x faster\nwhen resident", fontsize=9, color=TEXT,
            ha="center", va="center", linespacing=1.35)

    title = "Measured response latency, development machine"
    caption = (
        "Wall-clock latency on the development machine, log scale. A cold "
        "model load costs 24,318 ms. With the model resident, a tool call "
        "takes 1,163 ms, a refusal 1,908 ms, and a full grounded answer with "
        "retrieval 5,128 ms. Single runs on one development machine, not "
        "repeated trials and not the production virtual machine, so these are "
        "an order of magnitude indication rather than a benchmark. MEASURED "
        "(development machine only). Takeaway: keeping the model resident "
        "turns a 24.3 second cold start into a 1.2 second warm call."
    )
    return dict(name="fig06_latency_measured", title=title, caption=caption,
                width=SINGLE_COL, measured=True, path=save(fig, "fig06_latency_measured"))



# ---------------------------------------------------------------------------
# Figure 7 - agent x Gemma-capability matrix (double col, ILLUSTRATIVE)
# ---------------------------------------------------------------------------
def fig07_agent_map():
    fig = plt.figure(figsize=(DOUBLE_COL, 3.9))
    fig.suptitle("Which Gemma 4 E2B capability each agent uses",
                 fontsize=9.5, weight="semibold", color=TEXT, y=0.985)
    ax = schem_ax(fig, rect=(0.015, 0.03, 0.97, 0.86))
    ratio = axes_aspect(fig, ax)

    agents = ["Porter", "Prohori", "Khoji", "Shonchari", "Bicharok", "Lekhok", "Dalil"]
    cols = ["Tools", "Vision", "Audio", "Thinking"]
    col_colors = [BLUE, ORANGE, GREEN, GREY]
    matrix = [
        [1, 0, 0, 0],  # Porter: tool calling only, thinking off (change triage)
        [1, 1, 0, 0],  # Prohori: extract_fields is a native vision pass
        [1, 0, 0, 1],  # Khoji: eligibility scoring runs with thinking on
        [1, 0, 1, 1],  # Shonchari: voice mode (audio) + answer scoring thinking on
        [1, 1, 0, 0],  # Bicharok: reads the refusal letter with vision
        [1, 0, 0, 0],  # Lekhok: tool calling only
        [1, 1, 0, 0],  # Dalil: extract_fields vision pass over the contract
    ]

    top, bottom = 0.88, 0.04
    n_rows = len(agents) + 1
    row_h = (top - bottom) / n_rows
    col_centers = [0.475, 0.620, 0.765, 0.910]
    sq_h = row_h * 0.60
    sq_w = sq_h * ratio

    header_y = top - row_h * 0.5
    ax.text(0.02, header_y, "Agent", fontsize=9.5, weight="semibold", va="center")
    for cx, name in zip(col_centers, cols):
        ax.text(cx, header_y, name, fontsize=9.5, weight="semibold", ha="center", va="center")
    ax.plot([0.0, 1.0], [top - row_h * 0.92, top - row_h * 0.92], color=GRID, lw=1.0)

    for i, (name, row) in enumerate(zip(agents, matrix)):
        ry = top - row_h * (i + 1.5)
        ax.text(0.02, ry, name, fontsize=9, color=TEXT, va="center", weight="semibold")
        for cx, cc, used in zip(col_centers, col_colors, row):
            if used:
                box(ax, cx, ry, sq_w, sq_h, "Yes", cc, tc=WHITE, fs=9, weight="bold")
            else:
                p = FancyBboxPatch((cx - sq_w / 2, ry - sq_h / 2), sq_w, sq_h,
                                    boxstyle="round,pad=0.0,rounding_size=0.01",
                                    linewidth=0.8, edgecolor=GRID, facecolor="white", zorder=3)
                ax.add_patch(p)
        if i < len(agents) - 1:
            sep_y = top - row_h * (i + 2)
            ax.plot([0.0, 1.0], [sep_y, sep_y], color=GRID, lw=0.6)

    title = "Agent to Gemma-capability map"
    caption = (
        "Which native Gemma 4 E2B capability each of the seven agents uses: "
        "tools (function calling), vision, audio, and thinking mode. Filled, "
        "coloured cell with 'Yes' means the capability is used; empty white "
        "cell means it is not. All seven agents use tool calling. Vision is "
        "used by Prohori, Bicharok, and Dalil, exactly where agents.md "
        "specifies an extract_fields call (a Gemma vision pass over an "
        "uploaded document). Audio is used by Shonchari's voice mode. "
        "Thinking mode is shown on only where agents.md states it explicitly, "
        "Khoji's eligibility scoring and Shonchari's answer scoring; it is "
        "off by the same source's stated default everywhere else (Porter's "
        "change triage is explicitly off). ILLUSTRATIVE: a design map read "
        "from the agent specification in agents.md, not a runtime "
        "measurement of calls actually made."
    )
    return dict(name="fig07_agent_map", title=title, caption=caption,
                width=DOUBLE_COL, measured=False, path=save(fig, "fig07_agent_map"))


# ---------------------------------------------------------------------------
# Figure 8 - separation of duties by timescale (double col, ILLUSTRATIVE)
# ---------------------------------------------------------------------------
def fig08_timescale_separation():
    fig = plt.figure(figsize=(DOUBLE_COL, 3.75))
    fig.suptitle("Separation of duties by timescale across the three RC-RAG loops",
                 fontsize=9.5, weight="semibold", color=TEXT, y=0.98)
    ax = schem_ax(fig, rect=(0.015, 0.03, 0.97, 0.86))

    rows = [
        (BLUE, "FAST\nLOOP", "Milliseconds,\nper query",
         "Nothing structural changes. A cache entry may be written for the "
         "current knowledge-store version.",
         "An unsupported or hallucinated answer reaching a student: the "
         "output schema forces an explicit refusal when no retrieved passage "
         "supports the claim."),
        (ORANGE, "RECURRENT\nLOOP", "Hours,\nscheduled crawl",
         "The versioned knowledge store: pages are hash-checked, changed "
         "pages diffed at passage level, only the diffs re-embedded, and a "
         "new store version published.",
         "A student acting on a stale deadline, fee, or document requirement "
         "after a portal changed without their knowledge."),
        (GREEN, "CONTINUAL\nLOOP", "2 to 4 weeks,\nadapter cycle",
         "Model weights: a rank-16 QLoRA adapter trained on refusals and "
         "corrections, rehearsed 1 to 1 against a fixed set to resist "
         "forgetting.",
         "The model's skill stagnating, and an unvetted regression reaching "
         "students; promotion needs a frozen benchmark and a human reviewer, "
         "in series."),
    ]

    ax.text(0.135, 0.895, "Loop / timescale", fontsize=9.5, weight="semibold", ha="left")
    ax.text(0.415, 0.895, "What changes in that loop", fontsize=9.5, weight="semibold", ha="left")
    ax.text(0.715, 0.895, "Failure it prevents", fontsize=9.5, weight="semibold", ha="left")
    ax.plot([0.0, 1.0], [0.845, 0.845], color=GRID, lw=1.0)

    row_tops = [0.825, 0.565, 0.305]
    row_h = 0.245
    for (color, tag, timescale, changes, prevents), rt in zip(rows, row_tops):
        cy = rt - row_h / 2
        box(ax, 0.075, cy, 0.115, 0.17, tag, color, fs=9, weight="semibold")
        ts_lines = timescale.split("\n")
        ax.text(0.135, cy + 0.045, ts_lines[0], fontsize=9, color=TEXT, va="center", ha="left")
        ax.text(0.135, cy - 0.045, ts_lines[1], fontsize=9, color=GREY, va="center", ha="left")
        ax.text(0.415, cy, textwrap.fill(changes, width=30), fontsize=9, color=TEXT,
                va="center", ha="left", linespacing=1.45)
        ax.text(0.715, cy, textwrap.fill(prevents, width=27), fontsize=9, color=TEXT,
                va="center", ha="left", linespacing=1.45)
        if rt != row_tops[-1]:
            sep = rt - row_h
            ax.plot([0.0, 1.0], [sep, sep], color=GRID, lw=0.7)

    title = "Separation of duties by timescale"
    caption = (
        "What changes in each of the three RC-RAG loops, and the failure each "
        "one specifically prevents. Fast loop (blue, per query): nothing is "
        "stored; the schema forces a refusal rather than an unsupported "
        "answer. Recurrent loop (orange, hours): the versioned knowledge "
        "store is updated so students never act on a stale requirement. "
        "Continual loop (green, 2 to 4 weeks): the model's own weights "
        "improve through a gated adapter, so language and reasoning quality "
        "does not stagnate, without an ungated regression reaching students. "
        "ILLUSTRATIVE: a conceptual summary of the design, not a "
        "measurement."
    )
    return dict(name="fig08_timescale_separation", title=title, caption=caption,
                width=DOUBLE_COL, measured=False, path=save(fig, "fig08_timescale_separation"))


# ---------------------------------------------------------------------------
# Figure 9 - question to cited answer data flow (single col, ILLUSTRATIVE)
# ---------------------------------------------------------------------------
def fig09_data_flow():
    fig = plt.figure(figsize=(SINGLE_COL, 4.75))
    fig.suptitle("From question to cited answer", fontsize=9.5, weight="semibold",
                 color=TEXT, y=0.985)
    ax = schem_ax(fig, rect=(0.02, 0.02, 0.96, 0.90))

    main_x = 0.36
    main_w = 0.58
    side_x = 0.835
    side_w = 0.29
    h = 0.10

    steps = [
        (0.93, "Question\nBangla / Banglish / English", BLUE, "solid"),
        (0.795, "Normalise", BLUE, "solid"),
        (0.645, "Semantic\ncache hit?", GREY, "dashed"),
        (0.485, "Hybrid retrieval\ndense + BM25", BLUE, "solid"),
        (0.335, "Generate with schema\nGemma 4 E2B", BLUE, "solid"),
        (0.185, "Supporting\npassage found?", GREY, "dashed"),
        (0.04, "Answer + citation", GREEN, "solid"),
    ]
    for y, label, color, ls in steps:
        tc = TEXT if color == GREY else WHITE
        ec = GREY if color == GREY else color
        box(ax, main_x, y, main_w, h, label, color, fs=9, ls=ls, tc=tc, ec=ec)

    main_arrow_pairs = [(0, 1), (1, 2), (3, 4), (4, 5), (5, 6)]
    for i, j in main_arrow_pairs:
        arrow(ax, (main_x, steps[i][0] - h / 2), (main_x, steps[j][0] + h / 2))
    ax.text(main_x + 0.03, (steps[2][0] + steps[3][0]) / 2, "miss", fontsize=9,
            color=TEXT, ha="left")
    arrow(ax, (main_x, steps[2][0] - h / 2), (main_x, steps[3][0] + h / 2))

    box(ax, side_x, steps[2][0], side_w, h, "Cached cited\nanswer", GREEN, fs=9)
    arrow(ax, (main_x + main_w / 2, steps[2][0]), (side_x - side_w / 2, steps[2][0]))
    ax.text((main_x + main_w / 2 + side_x - side_w / 2) / 2, steps[2][0] + 0.035,
            "hit", fontsize=9, color=TEXT, ha="center")

    box(ax, side_x, steps[5][0], side_w, h, "Explicit refusal\nreason stated", ORANGE, fs=9)
    arrow(ax, (main_x + main_w / 2, steps[5][0]), (side_x - side_w / 2, steps[5][0]))
    ax.text((main_x + main_w / 2 + side_x - side_w / 2) / 2, steps[5][0] + 0.035,
            "no", fontsize=9, color=TEXT, ha="center")
    ax.text(main_x + 0.03, (steps[5][0] + steps[6][0]) / 2, "yes", fontsize=9,
            color=TEXT, ha="left")

    title = "Data flow: question to cited answer"
    caption = (
        "The fast-loop pipeline from a student's question to a cited answer: "
        "normalise, check the semantic cache, hybrid retrieval (dense plus "
        "BM25) on a cache miss, generate with a schema-constrained call to "
        "Gemma 4 E2B, and either an answer with a citation or an explicit "
        "refusal when no retrieved passage supports a claim. A cache hit "
        "short-circuits straight to a previously cached, still-current cited "
        "answer. ILLUSTRATIVE: a pipeline schematic, not a data plot."
    )
    return dict(name="fig09_data_flow", title=title, caption=caption,
                width=SINGLE_COL, measured=False, path=save(fig, "fig09_data_flow"))


# ---------------------------------------------------------------------------
# Figure 10 - three human-in-the-loop decision points (single col, ILLUSTRATIVE)
# ---------------------------------------------------------------------------
def fig10_human_in_loop():
    fig = plt.figure(figsize=(SINGLE_COL, 4.5))
    fig.suptitle("Three points where a human decides, not the model",
                 fontsize=9.5, weight="semibold", color=TEXT, y=0.985)
    ax = schem_ax(fig, rect=(0.02, 0.02, 0.96, 0.90))

    rows = [
        ("1. Alert release", "Change classified\nbelow 0.7 confidence", "Human review\nqueue",
         [("Alert\nsent", GREEN), ("Suppressed", ORANGE)]),
        ("2. Answer correction", "Reviewer flags\nan answer", "Human records\nthe correction",
         [("Enters replay buffer\nhighest-value item", GREEN)]),
        ("3. Adapter promotion", "Adapter passes\nGate 1 benchmark", "Human reviewer\nGate 2",
         [("Promote\nhot swap", GREEN), ("Roll\nback", ORANGE)]),
    ]
    row_tops = [0.885, 0.585, 0.285]
    row_h = 0.27
    for (title_txt, trig, human, outcomes), rt in zip(rows, row_tops):
        cy = rt - row_h * 0.46
        ax.text(0.0, rt, title_txt, fontsize=9.5, weight="semibold", color=TEXT,
                ha="left", va="top")
        box(ax, 0.155, cy, 0.27, 0.15, trig, GREY, fs=9)
        arrow(ax, (0.29, cy), (0.395, cy))
        box(ax, 0.535, cy, 0.25, 0.15, human, BLUE, fs=9)
        if len(outcomes) == 1:
            arrow(ax, (0.66, cy), (0.775, cy))
            box(ax, 0.905, cy, 0.19, 0.15, outcomes[0][0], outcomes[0][1], fs=9)
        else:
            arrow(ax, (0.66, cy), (0.775, cy + 0.075), rad=-0.15)
            arrow(ax, (0.66, cy), (0.775, cy - 0.075), rad=0.15)
            box(ax, 0.905, cy + 0.075, 0.19, 0.11, outcomes[0][0], outcomes[0][1], fs=9)
            box(ax, 0.905, cy - 0.075, 0.19, 0.11, outcomes[1][0], outcomes[1][1], fs=9)
        if rt != row_tops[-1]:
            sep = rt - row_h + 0.02
            ax.plot([0.0, 1.0], [sep, sep], color=GRID, lw=0.6)

    title = "Three human-in-the-loop decision points"
    caption = (
        "The three points in Digonto where a human decides rather than the "
        "model. Alert release: a portal change classified below 0.7 "
        "confidence reaches a human review queue before any student is "
        "alerted, so a false 'your deadline moved' notice never reaches five "
        "hundred students unsupervised. Answer correction: a corrected "
        "answer is recorded by a human, not inferred from an implicit signal "
        "such as a thumbs-down, because that correction is the highest-value "
        "item in the training buffer. Adapter promotion: gate 2 is a human "
        "reviewer, and no adapter reaches students on the automatic "
        "benchmark alone. ILLUSTRATIVE: a governance schematic, not a data "
        "plot."
    )
    return dict(name="fig10_human_in_loop", title=title, caption=caption,
                width=SINGLE_COL, measured=False, path=save(fig, "fig10_human_in_loop"))


# ---------------------------------------------------------------------------
# Figure 11 - cost model, fixed VM vs per-token API (single col, ILLUSTRATIVE)
# ---------------------------------------------------------------------------
def fig11_cost_model():
    fig = plt.figure(figsize=(SINGLE_COL, 3.5))
    ax = fig.add_axes([0.17, 0.19, 0.68, 0.62])

    vm_cost = 80.0          # illustrative flat monthly VM cost, USD
    per_student = 0.03      # illustrative per-student-per-month API cost, USD
    x = np.linspace(0, 4300, 200)
    fixed = np.full_like(x, vm_cost)
    api = per_student * x
    ax.plot(x, fixed, color=BLUE, lw=1.8, zorder=3)
    ax.plot(x, api, color=ORANGE, lw=1.8, zorder=3)

    cross_x = vm_cost / per_student
    ax.plot([cross_x], [vm_cost], marker="o", color=TEXT, markersize=4, zorder=4)
    ax.axvline(cross_x, color=GRID, lw=1.0, linestyle="dashed", zorder=1)
    ax.text(cross_x, vm_cost + 8, f"crossover\n~{cross_x:,.0f} students",
            fontsize=9, color=TEXT, ha="center", va="bottom")

    ax.text(4260, vm_cost + 5, "Fixed VM cost\n(illustrative)", fontsize=9,
            color=BLUE, ha="right", va="bottom")
    ax.text(4260, per_student * 4300 + 6, "Per-token API cost\n(illustrative)",
            fontsize=9, color=ORANGE, ha="right", va="bottom")

    ax.set_xlim(0, 4300)
    ax.set_ylim(0, 165)
    ax.set_xlabel("Active students per month (illustrative)")
    ax.set_ylabel("Monthly cost, USD (illustrative)")
    ax.set_title("Why a flat server cost stays sustainable as usage grows", pad=8)
    clean_axes(ax, grid_axis="y")

    title = "Illustrative cost model: fixed VM versus per-token API"
    caption = (
        "Illustrative cost comparison, not measured billing data. The blue "
        "line assumes a flat, hypothetical 80 US dollar per month cost for "
        "one self-hosted virtual machine, independent of how many students "
        "use it. The orange line assumes a hypothetical per-token hosted-API "
        "alternative, at roughly 0.03 US dollars per active student per "
        "month (illustrative: about 3,000 tokens and 20 questions per "
        "student monthly at an illustrative 0.50 US dollars per million "
        "tokens). Under these assumptions the two cost curves cross at "
        "roughly 2,700 students; past that point self-hosting a fixed VM is "
        "cheaper than paying per token, and the gap widens as usage grows. "
        "ILLUSTRATIVE: all costs, token counts, and usage rates are assumed "
        "for illustration, not sourced from a metered bill; real API "
        "pricing, real VM pricing, and real usage patterns will differ."
    )
    return dict(name="fig11_cost_model", title=title, caption=caption,
                width=SINGLE_COL, measured=False, path=save(fig, "fig11_cost_model"))


# ---------------------------------------------------------------------------
# Orchestration
# ---------------------------------------------------------------------------
FIGURE_FUNCS = [
    fig01_problem_scale,
    fig02_refusal_trend,
    fig03_rcrag_loops,
    fig04_event_fanout,
    fig05_promotion_gates,
    fig06_latency_measured,
    fig07_agent_map,
    fig08_timescale_separation,
    fig09_data_flow,
    fig10_human_in_loop,
    fig11_cost_model,
]


def write_readme(results):
    lines = [
        "# Digonto figure assets",
        "",
        "Generated entirely by `make_figures.py`. Regenerate every PNG with:",
        "",
        "```",
        "python3 make_figures.py",
        "```",
        "",
        "Pure matplotlib, no seaborn, no external images, no network access, "
        "deterministic output. All 11 figures are written to `out/` at 300 dpi "
        "on a white background.",
        "",
        "## Style",
        "",
        "Binding palette and typography from `writing_instructions.md` Part 3: "
        "Blue #2563EB, Orange #E8710A, Green #059669, Neutral grey #6B7280, "
        "text #111827, gridlines #E5E7EB; Arial/Helvetica/DejaVu Sans, 9 to "
        "9.5 pt; flat 2D, no gradients or drop shadows; designed at true IEEE "
        "print width (3.5 in single column, 7.16 in double column). The same "
        "colour keeps the same meaning in every figure it appears in: blue is "
        "the fast loop / primary series / the Tools capability, orange is the "
        "recurrent loop / a refused or rejected outcome / the Vision "
        "capability, green is the continual loop / a verified or promoted "
        "outcome / the Audio capability, grey is storage / a neutral or cold "
        "system state / the Thinking capability.",
        "",
        "Agent names appear in English only inside the images: the binding "
        "font stack (Arial, Helvetica, DejaVu Sans) has no Bengali glyphs, so "
        "Bangla script would render as missing-glyph boxes. Bangla names stay "
        "in the surrounding prose.",
        "",
        "## Figures",
        "",
        "| # | File | Width | Class | Title |",
        "|---|------|-------|-------|-------|",
    ]
    for i, r in enumerate(results, start=1):
        cls = "MEASURED" if r["measured"] else "ILLUSTRATIVE"
        w = "double column, 7.16 in" if abs(r["width"] - DOUBLE_COL) < 1e-6 else "single column, 3.5 in"
        lines.append(f"| {i:02d} | `out/{r['name']}.png` | {w} | {cls} | {r['title']} |")

    lines.append("")
    lines.append("## Captions")
    lines.append("")
    for i, r in enumerate(results, start=1):
        cls = "MEASURED" if r["measured"] else "ILLUSTRATIVE"
        w = "double column, 7.16 in" if abs(r["width"] - DOUBLE_COL) < 1e-6 else "single column, 3.5 in"
        lines.append(f"### {i:02d}. `{r['name']}.png` — {cls}, {w}")
        lines.append("")
        lines.append(r["caption"])
        lines.append("")

    readme_path = os.path.join(HERE, "README.md")
    with open(readme_path, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"  wrote README.md ({len(results)} figures documented)")


def main():
    print(f"Digonto figure generator - writing to {OUT_DIR}")
    results = []
    for fn in FIGURE_FUNCS:
        r = fn()
        results.append(r)
    write_readme(results)
    print(f"Done: {len(results)} figures + README.md")


if __name__ == "__main__":
    main()
