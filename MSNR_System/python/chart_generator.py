"""
MSNR Chart Generator — dark theme candlestick chart
Ve: nen, A/V levels, Entry/SL/TP, trendline, signal annotation
"""
import os
import logging
import matplotlib
matplotlib.use("Agg")          # non-interactive, no display needed
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

log = logging.getLogger("MSNR.Chart")

CHART_PATH = r"C:\MSNR_System\signals\signal_chart.png"

# Dark theme colors
BG_DARK   = "#131722"
BG_PANEL  = "#1e222d"
BULL_CLR  = "#26a69a"
BEAR_CLR  = "#ef5350"
GRID_CLR  = "#2a2e39"
TEXT_CLR  = "#d1d4dc"
ENTRY_CLR = "#f9a825"
SL_CLR    = "#ef5350"
TP_CLR    = "#26a69a"
A_CLR     = "#ef5350"
V_CLR     = "#26a69a"
TL_CLR    = "#ba68c8"


def _draw_candles(ax, df):
    for i, (_, row) in enumerate(df.iterrows()):
        bull = row["close"] >= row["open"]
        c    = BULL_CLR if bull else BEAR_CLR
        body_lo = min(row["open"], row["close"])
        body_hi = max(row["open"], row["close"])
        body_h  = max(body_hi - body_lo, 0.01)
        ax.bar(i, body_h, bottom=body_lo,
               color=c, width=0.7, linewidth=0)
        ax.plot([i, i], [row["low"],  body_lo], color=c, lw=0.8)
        ax.plot([i, i], [row["high"], body_hi], color=c, lw=0.8)


def generate(df, signal, fresh_levels, trendlines=None, n_bars=100):
    """
    df           : full OHLCV DataFrame
    signal       : signal dict (action, entry, sl, tp, rr, ...)
    fresh_levels : list of SnRLevel objects
    trendlines   : list of Trendline objects (optional)
    n_bars       : how many candles to show
    """
    try:
        plot_df = df.tail(n_bars).reset_index(drop=True)
        x_len   = len(plot_df)

        fig, ax = plt.subplots(figsize=(16, 8), facecolor=BG_DARK)
        ax.set_facecolor(BG_PANEL)
        fig.subplots_adjust(right=0.82)   # space for level labels on right

        # ── Candles ───────────────────────────────────────────────
        _draw_candles(ax, plot_df)

        # ── Price range for level filtering ───────────────────────
        y_lo = plot_df["low"].min()
        y_hi = plot_df["high"].max()
        pad  = (y_hi - y_lo) * 0.3
        vis_lo = y_lo - pad
        vis_hi = y_hi + pad

        # ── A / V Levels ──────────────────────────────────────────
        drawn_labels = set()
        for lv in fresh_levels:
            price = lv.price
            if not (vis_lo <= price <= vis_hi):
                continue
            is_a   = lv.level_type in ("A", "GAP_R")
            color  = A_CLR if is_a else V_CLR
            ltype  = "A-Level" if is_a else "V-Level"
            if lv.level_type in ("GAP_R", "GAP_S"):
                ltype = "Gap-SnR"
            label_key = f"{ltype}_{price:.2f}"
            ax.axhline(y=price, color=color, lw=0.9,
                       linestyle="--", alpha=0.75)
            if label_key not in drawn_labels:
                ax.text(x_len + 0.4, price,
                        f"  {ltype} {price:.2f} (H1)",
                        color=color, fontsize=7.5,
                        va="center", clip_on=False)
                drawn_labels.add(label_key)

        # ── Entry / SL / TP ───────────────────────────────────────
        entry  = signal["entry"]
        sl     = signal["sl"]
        tp     = signal["tp"]
        action = signal["action"]
        rr     = signal.get("rr", 0)

        # Shade zones
        ax.fill_between(range(x_len), sl, entry,
                        alpha=0.12, color=SL_CLR, zorder=0)
        ax.fill_between(range(x_len), entry, tp,
                        alpha=0.12, color=TP_CLR, zorder=0)

        # Lines
        ax.axhline(y=entry, color=ENTRY_CLR, lw=1.8, linestyle="-",  zorder=3)
        ax.axhline(y=sl,    color=SL_CLR,    lw=1.5, linestyle="--", zorder=3)
        ax.axhline(y=tp,    color=TP_CLR,    lw=1.5, linestyle="--", zorder=3)

        # Right-side labels
        ax.text(x_len + 0.4, entry,
                f"  ENTRY {entry:.2f}",
                color=ENTRY_CLR, fontsize=8.5,
                fontweight="bold", va="center", clip_on=False)
        ax.text(x_len + 0.4, sl,
                f"  SL {sl:.2f}  (-$18)",
                color=SL_CLR, fontsize=8, va="center", clip_on=False)
        ax.text(x_len + 0.4, tp,
                f"  TP {tp:.2f}  (RR {rr:.1f}:1)",
                color=TP_CLR, fontsize=8, va="center", clip_on=False)

        # Entry arrow
        arr_y  = entry
        arr_dx = 3
        arr_x  = x_len - 1
        ax.annotate(
            "", xy=(arr_x, arr_y),
            xytext=(arr_x - arr_dx, arr_y),
            arrowprops=dict(arrowstyle="->", color=ENTRY_CLR, lw=2)
        )

        # ── Trendlines ────────────────────────────────────────────
        if trendlines:
            for tl in trendlines[:3]:
                try:
                    if not (hasattr(tl, "p1_idx") and hasattr(tl, "p3_idx")):
                        continue
                    # Map bar index to plot position
                    total_bars = len(df)
                    offset = total_bars - n_bars
                    x1 = tl.p1_idx - offset
                    x2 = getattr(tl, "p3_idx", tl.p2_idx) - offset
                    y1 = getattr(tl, "p1_price", 0)
                    y2 = getattr(tl, "p3_price", 0) or getattr(tl, "p2_price", 0)
                    if 0 <= x1 < x_len and 0 <= x2 < x_len:
                        # Extend trendline slightly past P3
                        slope  = (y2 - y1) / (x2 - x1) if x2 != x1 else 0
                        x_end  = min(x2 + 10, x_len - 1)
                        y_end  = y2 + slope * (x_end - x2)
                        ax.plot([x1, x_end], [y1, y_end],
                                color=TL_CLR, lw=1.2,
                                linestyle="-", alpha=0.85)
                        ax.scatter([x2], [y2], color=TL_CLR,
                                   s=30, zorder=5)
                except Exception:
                    pass

        # ── Grid ─────────────────────────────────────────────────
        ax.yaxis.grid(True, color=GRID_CLR, lw=0.5, linestyle="-")
        ax.set_axisbelow(True)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.spines["left"].set_color(GRID_CLR)
        ax.spines["bottom"].set_color(GRID_CLR)
        ax.tick_params(colors=TEXT_CLR, labelsize=8)

        # X-axis: show time labels
        step = max(1, x_len // 10)
        xticks = list(range(0, x_len, step))
        xlabels = [str(plot_df.loc[i, "time"])[:13]
                   if i < len(plot_df) else "" for i in xticks]
        ax.set_xticks(xticks)
        ax.set_xticklabels(xlabels, rotation=30, ha="right", fontsize=7)

        # Y range
        ax.set_ylim(vis_lo, vis_hi)
        ax.set_xlim(-1, x_len + 0.5)

        # ── Title ─────────────────────────────────────────────────
        arr_sym = "▲ LONG" if action == "BUY" else "▼ SHORT"
        ax.set_title(
            f"XAUUSD H1  |  MSNR {arr_sym} @ {entry:.2f}  "
            f"|  SL ${18:.0f}  |  TP ${abs(tp-entry):.1f}  |  RR {rr:.1f}:1",
            color=TEXT_CLR, fontsize=11, fontweight="bold",
            pad=10, loc="left"
        )

        # Legend
        legend_items = [
            mpatches.Patch(color=A_CLR,     label="A-Level (Resistance)"),
            mpatches.Patch(color=V_CLR,     label="V-Level (Support)"),
            mpatches.Patch(color=ENTRY_CLR, label="Entry"),
            mpatches.Patch(color=SL_CLR,    label=f"SL (-$18)"),
            mpatches.Patch(color=TP_CLR,    label=f"TP (RR {rr:.1f}:1)"),
        ]
        if trendlines:
            legend_items.append(
                mpatches.Patch(color=TL_CLR, label="Trendline (P3)")
            )
        ax.legend(handles=legend_items, loc="upper left",
                  facecolor=BG_PANEL, edgecolor=GRID_CLR,
                  labelcolor=TEXT_CLR, fontsize=7.5)

        os.makedirs(os.path.dirname(CHART_PATH), exist_ok=True)
        plt.savefig(CHART_PATH, dpi=110, bbox_inches="tight",
                    facecolor=BG_DARK)
        plt.close(fig)
        log.info(f"Chart saved: {CHART_PATH}")
        return CHART_PATH

    except Exception as e:
        log.error(f"Chart generation failed: {e}")
        return None
