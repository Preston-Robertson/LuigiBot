"""Chart rendering functions — visual theme, styling helpers, and all chart generators."""
import textwrap
from io import BytesIO

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patheffects as pe
from matplotlib.patches import Ellipse, Rectangle


# --- Visual Theme ---

VISUAL_THEME = {
    "bg": "#1E1F22",
    "panel": "#2B2D31",
    "panel_alt": "#242732",
    "grid": "#3A3D45",
    "text": "#F2F3F5",
    "muted": "#B5BAC1",
    "discord": "#5865F2",
    "luigi": "#43B581",
    "cyan": "#4EDFD2",
    "violet": "#6E63D9",
    "warn": "#FAA61A",
    "danger": "#ED4245",
    "neutral": "#7F8C8D",
    "target": "#404A86",
}

VISUAL_FONT_STACK = ["gg sans", "Whitney", "Noto Sans", "DejaVu Sans", "sans-serif"]
matplotlib.rcParams["font.family"] = VISUAL_FONT_STACK


# --- Styling Helpers ---

def style_axis_labels(labels, wrap_width=12, max_chars=24):
    formatted = []
    for label in labels:
        label_text = str(label).strip()
        if len(label_text) > max_chars:
            label_text = label_text[: max_chars - 1].rstrip() + "..."
        formatted.append(textwrap.fill(label_text, width=wrap_width, break_long_words=False))
    return formatted


def apply_chart_theme(ax):
    ax.set_facecolor(VISUAL_THEME["panel"])
    ax.patch.set_edgecolor(VISUAL_THEME["panel_alt"])
    ax.patch.set_linewidth(1.0)
    ax.grid(axis="y", linestyle="-", linewidth=1.0, alpha=0.28, color=VISUAL_THEME["grid"])
    ax.set_axisbelow(True)

    for spine in ["top", "right"]:
        ax.spines[spine].set_visible(False)
    for spine in ["left", "bottom"]:
        ax.spines[spine].set_color(VISUAL_THEME["grid"])

    ax.tick_params(colors=VISUAL_THEME["muted"])


def style_chart_title(ax, chart_title):
    title_obj = ax.set_title(
        chart_title,
        fontsize=15,
        fontweight="bold",
        color=VISUAL_THEME["text"],
        pad=20,
        fontfamily=VISUAL_FONT_STACK,
    )
    title_obj.set_path_effects([
        pe.withStroke(linewidth=3.5, foreground="#171821", alpha=0.95),
    ])


def draw_clean_bars(ax, x_positions, heights, color, width=0.68, label=None, zbase=2):
    """Flat-top bars with neon glow halo, cylindrical cap disc, and subtle gloss strip.
    Must be called after ax.set_ylim() so cap_ry can be computed from the axis range.
    """
    ylim = ax.get_ylim()
    ylim_range = abs(ylim[1] - ylim[0]) or 1.0
    cap_rx = width * 0.48
    cap_ry = max(ylim_range * 0.030, cap_rx * 0.28)
    for i, (xi, h) in enumerate(zip(x_positions, heights)):
        if h <= 0:
            continue
        lbl = label if i == 0 else None
        # Outer neon glow
        ax.add_patch(Rectangle(
            (xi - width / 2 - 0.035, 0), width + 0.07, h,
            facecolor=color, edgecolor="none", alpha=0.11, zorder=zbase - 0.5))
        # Main bar body
        ax.add_patch(Rectangle(
            (xi - width / 2, 0), width, h,
            facecolor=color, edgecolor="none", zorder=zbase, label=lbl))
        # Subtle left gloss strip
        ax.add_patch(Rectangle(
            (xi - width / 2 + width * 0.08, 0), width * 0.13, h * 0.96,
            facecolor="#FFFFFF", edgecolor="none", alpha=0.09, zorder=zbase + 0.2))
        # Cap glow halo
        ax.add_patch(Ellipse(
            (xi, h), width=cap_rx * 2.1, height=cap_ry * 2.1,
            facecolor=color, edgecolor="none", alpha=0.20, zorder=zbase + 0.7))
        # Cap disc
        ax.add_patch(Ellipse(
            (xi, h), width=cap_rx * 2, height=cap_ry * 2,
            facecolor=color, edgecolor="none", alpha=0.95, zorder=zbase + 0.9))
        # Cap shine highlight
        ax.add_patch(Ellipse(
            (xi - cap_rx * 0.18, h + cap_ry * 0.14), width=cap_rx * 0.72, height=cap_ry * 0.55,
            facecolor="#FFFFFF", edgecolor="none", alpha=0.18, zorder=zbase + 1.1))


# --- Chart Generators ---

def render_completed_task_bar_chart(completion_series, chart_title, subtitle=None, highlight_index=None):
    labels = [dt.strftime("%a\n%m/%d") for dt in completion_series.index]
    values = completion_series.values.tolist()

    fig, ax = plt.subplots(figsize=(10, 5.2), dpi=150)
    fig.patch.set_facecolor(VISUAL_THEME["bg"])
    apply_chart_theme(ax)

    ymax = max(max(values), 1) * 1.18
    ax.set_xlim(-0.7, len(values) - 0.3)
    ax.set_ylim(0, ymax)

    for i, v in enumerate(values):
        color = VISUAL_THEME["luigi"] if (highlight_index is not None and i == highlight_index) else VISUAL_THEME["violet"]
        draw_clean_bars(ax, [i], [v], color, width=0.68)

    if highlight_index is not None and 0 <= highlight_index < len(values):
        ax.scatter(
            [highlight_index],
            [values[highlight_index] + ymax * 0.02],
            s=160,
            color=VISUAL_THEME["luigi"],
            alpha=0.22,
            zorder=3,
        )

    style_chart_title(ax, chart_title)
    if subtitle:
        ax.text(
            0.015, 0.99, subtitle, ha="left", va="top", transform=ax.transAxes,
            fontsize=9, color=VISUAL_THEME["muted"], fontfamily=VISUAL_FONT_STACK,
        )

    ax.set_xticks(range(len(labels)))
    ax.set_xticklabels(labels, fontsize=9, color=VISUAL_THEME["text"], fontfamily=VISUAL_FONT_STACK)
    ax.set_ylabel("Tasks Completed", fontsize=10, color=VISUAL_THEME["text"], fontfamily=VISUAL_FONT_STACK)

    for i, v in enumerate(values):
        ax.text(
            i, v + ymax * 0.022, str(int(v)), ha="center", va="bottom",
            fontsize=8, color=VISUAL_THEME["text"], fontfamily=VISUAL_FONT_STACK, fontweight="bold",
        )

    fig.tight_layout(pad=1.25)
    image_buffer = BytesIO()
    fig.savefig(image_buffer, format="png", bbox_inches="tight")
    plt.close(fig)
    image_buffer.seek(0)
    return image_buffer


def render_discipline_daily_goal_status_chart(status_df, chart_title, subtitle=None):
    labels = style_axis_labels(status_df["TASK"].astype(str).tolist(), wrap_width=12, max_chars=24)

    fig, ax = plt.subplots(figsize=(max(11, len(labels) * 0.95), 5.8), dpi=150)
    fig.patch.set_facecolor(VISUAL_THEME["bg"])
    apply_chart_theme(ax)

    ax.set_xlim(-0.7, len(labels) - 0.3)
    ax.set_ylim(0, 1.28)
    ax.axhline(1, color=VISUAL_THEME["cyan"], linewidth=0.8, alpha=0.28, zorder=1)

    for idx, (_, row) in enumerate(status_df.iterrows()):
        status_code = row["STATUS_CODE"]
        if status_code == "met_today":
            draw_clean_bars(ax, [idx], [1], VISUAL_THEME["luigi"], width=0.68)
        elif status_code == "met_before_today":
            draw_clean_bars(ax, [idx], [1], VISUAL_THEME["discord"], width=0.68)
        elif status_code == "done_today_not_met":
            draw_clean_bars(ax, [idx], [0.15], VISUAL_THEME["warn"], width=0.68)
        else:
            ax.add_patch(Rectangle(
                (idx - 0.34, 0), 0.68, 0.03,
                facecolor="none", edgecolor=VISUAL_THEME["neutral"], linewidth=1.5, zorder=2))

    ax.set_xticks(list(range(len(labels))))
    ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=9, color=VISUAL_THEME["text"], fontfamily=VISUAL_FONT_STACK)
    ax.set_yticks([0, 1])
    ax.set_yticklabels(["Need", "Met"], fontsize=9, color=VISUAL_THEME["text"], fontfamily=VISUAL_FONT_STACK)
    ax.set_ylabel("Weekly Goal Status", fontsize=10, color=VISUAL_THEME["text"], fontfamily=VISUAL_FONT_STACK)
    style_chart_title(ax, chart_title)

    if subtitle:
        ax.text(
            0.015, 0.99, subtitle, ha="left", va="top", transform=ax.transAxes,
            fontsize=9, color=VISUAL_THEME["muted"], fontfamily=VISUAL_FONT_STACK,
        )

    legend_handles = [
        plt.Rectangle((0, 0), 1, 1, color=VISUAL_THEME["luigi"], label="Reached Goal Today"),
        plt.Rectangle((0, 0), 1, 1, color=VISUAL_THEME["discord"], label="Goal Already Met"),
        plt.Rectangle((0, 0), 1, 1, color=VISUAL_THEME["warn"], label="Done Today (Not Met Yet)"),
        plt.Rectangle((0, 0), 1, 1, facecolor="none", edgecolor=VISUAL_THEME["neutral"], label="Needs Completion"),
    ]
    ax.legend(
        handles=legend_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        ncol=2,
        fontsize=8,
        facecolor=VISUAL_THEME["panel"],
        edgecolor=VISUAL_THEME["grid"],
        labelcolor=VISUAL_THEME["text"],
        framealpha=0.95,
        borderpad=0.7,
    )

    fig.subplots_adjust(top=0.84, bottom=0.28)
    fig.tight_layout(pad=1.2)
    image_buffer = BytesIO()
    fig.savefig(image_buffer, format="png", bbox_inches="tight")
    plt.close(fig)
    image_buffer.seek(0)
    return image_buffer


def render_discipline_weekly_progress_chart(report_df, chart_title, subtitle=None):
    labels = style_axis_labels(report_df["TASK"].astype(str).tolist(), wrap_width=12, max_chars=24)
    actual = report_df["COMPLETIONS_THIS_WEEK"].astype(int).tolist()
    target = report_df["FREQUENCY_PER_WEEK"].astype(int).tolist()

    fig, ax = plt.subplots(figsize=(max(11, len(labels) * 0.95), 5.8), dpi=150)
    fig.patch.set_facecolor(VISUAL_THEME["bg"])
    apply_chart_theme(ax)

    x_positions = list(range(len(labels)))
    width = 0.42
    max_y = max(target + actual) if (target or actual) else 1
    ymax = max_y * 1.22

    ax.set_xlim(-0.7, len(labels) - 0.3)
    ax.set_ylim(0, ymax)

    for i in range(len(labels)):
        xi_t = i - width / 2 - 0.04
        xi_a = i + width / 2 + 0.04
        ac = VISUAL_THEME["luigi"] if actual[i] >= target[i] else VISUAL_THEME["danger"]
        draw_clean_bars(ax, [xi_t], [target[i]], VISUAL_THEME["target"], width=width)
        draw_clean_bars(ax, [xi_a], [actual[i]], ac, width=width)

    ax.set_xticks(x_positions)
    ax.set_xticklabels(labels, rotation=20, ha="right", fontsize=9, color=VISUAL_THEME["text"], fontfamily=VISUAL_FONT_STACK)
    ax.set_ylabel("Days Completed This Week", fontsize=10, color=VISUAL_THEME["text"], fontfamily=VISUAL_FONT_STACK)
    style_chart_title(ax, chart_title)

    if subtitle:
        ax.text(
            0.015, 0.99, subtitle, ha="left", va="top", transform=ax.transAxes,
            fontsize=9, color=VISUAL_THEME["muted"], fontfamily=VISUAL_FONT_STACK,
        )

    for i in range(len(labels)):
        xi_t = i - width / 2 - 0.04
        xi_a = i + width / 2 + 0.04
        ax.text(xi_t, target[i] + ymax * 0.025, str(target[i]), ha="center", va="bottom",
                fontsize=7.5, color=VISUAL_THEME["text"], fontfamily=VISUAL_FONT_STACK, fontweight="bold")
        ax.text(xi_a, actual[i] + ymax * 0.025, str(actual[i]), ha="center", va="bottom",
                fontsize=7.5, color=VISUAL_THEME["text"], fontfamily=VISUAL_FONT_STACK, fontweight="bold")

    legend_handles = [
        plt.Rectangle((0, 0), 1, 1, color=VISUAL_THEME["target"], label="Target"),
        plt.Rectangle((0, 0), 1, 1, color=VISUAL_THEME["luigi"], label="Actual (On Track)"),
        plt.Rectangle((0, 0), 1, 1, color=VISUAL_THEME["danger"], label="Actual (Behind)"),
    ]
    ax.legend(
        handles=legend_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.14),
        ncol=3,
        fontsize=9,
        facecolor=VISUAL_THEME["panel"],
        edgecolor=VISUAL_THEME["grid"],
        labelcolor=VISUAL_THEME["text"],
        framealpha=0.95,
        borderpad=0.7,
    )

    fig.subplots_adjust(top=0.84, bottom=0.27)
    fig.tight_layout(pad=1.2)
    image_buffer = BytesIO()
    fig.savefig(image_buffer, format="png", bbox_inches="tight")
    plt.close(fig)
    image_buffer.seek(0)
    return image_buffer
