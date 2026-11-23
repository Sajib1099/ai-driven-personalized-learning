"""Styling, colours and chart helpers shared by all pages."""
from __future__ import annotations

import html

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Fixed categorical order -> the same colour always means the same class
CLASS_COLORS = {
    "Distinction": "#2a78d6",
    "Fail": "#eb6834",
    "Pass": "#1baf7a",
    "Withdrawn": "#eda100",
}
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100"]
POSITIVE, NEGATIVE = "#2a78d6", "#e34948"     # diverging pair for SHAP / LIME
INK, INK_2, MUTED = "#0b0b0b", "#52514e", "#898781"
GRID, AXIS, SURFACE = "#e1e0d9", "#c3c2b7", "#fcfcfb"
FONT = 'system-ui, -apple-system, "Segoe UI", Roboto, sans-serif'

CSS = f"""
<style>
html, body, [class*="css"] {{ font-family: {FONT}; }}
.block-container {{ padding-top: 2rem; max-width: 1200px; }}
.hero {{ padding: 1.6rem 1.8rem; border-radius: 16px;
        background: linear-gradient(135deg, #0d366b 0%, #1c5cab 55%, #2a78d6 100%);
        color: #fff; margin-bottom: 1.2rem; }}
.hero h1 {{ color: #fff; font-size: 1.9rem; margin: 0 0 .4rem 0; line-height: 1.25; }}
.hero p {{ color: #dbe8fb; margin: 0; font-size: 1.02rem; }}
.hero .tag {{ display:inline-block; background: rgba(255,255,255,.16); border-radius: 999px;
             padding: .15rem .7rem; font-size: .78rem; margin-bottom: .7rem; color:#fff; }}
.card {{ background: #ffffff; border: 1px solid rgba(11,11,11,.10); border-radius: 14px;
        padding: 1.1rem 1.2rem; height: 100%; }}
.kpi-label {{ color: {INK_2}; font-size: .82rem; margin-bottom: .25rem; }}
.kpi-value {{ color: {INK}; font-size: 1.75rem; font-weight: 650; line-height: 1.1; }}
.kpi-note {{ color: {MUTED}; font-size: .78rem; margin-top: .3rem; }}
.step-num {{ display:inline-flex; width:28px; height:28px; border-radius:50%;
            background:#cde2fb; color:#0d366b; font-weight:700; align-items:center;
            justify-content:center; margin-bottom:.5rem; font-size:.9rem; }}
.step-title {{ font-weight: 650; color: {INK}; margin-bottom: .2rem; }}
.step-text {{ color: {INK_2}; font-size: .88rem; }}
.pred-card {{ border-radius: 16px; padding: 1.3rem 1.4rem; border: 1px solid rgba(11,11,11,.10);
             background:#fff; }}
.pred-class {{ font-size: 2.1rem; font-weight: 700; line-height: 1.1; }}
.badge {{ display:inline-block; border-radius:999px; padding:.15rem .65rem; font-size:.78rem;
         font-weight:600; margin-right:.35rem; }}
.rec-card {{ background:#fff; border:1px solid rgba(11,11,11,.10); border-radius:14px;
            padding:1rem 1.15rem; margin-bottom:.8rem; }}
.rec-title {{ font-weight:650; font-size:1.02rem; color:{INK}; }}
.rec-evidence {{ color:{INK_2}; font-size:.86rem; margin:.35rem 0 .45rem 0; }}
.login-brand {{ text-align:center; margin: 2.2rem 0 1.4rem 0; }}
.login-logo {{ font-size: 2.6rem; }}
.login-brand h1 {{ font-size: 1.7rem; margin: .3rem 0 .3rem 0; color:{INK}; }}
.login-brand p {{ color:{INK_2}; margin:0; }}
.role-badge {{ display:inline-block; border-radius:999px; padding:.1rem .6rem; font-size:.75rem;
              font-weight:600; background:#cde2fb; color:#0d366b; }}
.note {{ background:#f2f1ed; border-radius:10px; padding:.7rem .9rem; color:{INK_2}; font-size:.86rem; }}
</style>
"""

PRIORITY_STYLE = {
    "High": ("#fbe3e3", "#a32b2b", "▲ High priority"),
    "Medium": ("#fdf0d5", "#7a5200", "● Medium priority"),
    "Low": ("#e3eefc", "#1c5cab", "▽ Low priority"),
}


def inject_css():
    st.markdown(CSS, unsafe_allow_html=True)


def esc(s) -> str:
    return html.escape(str(s))


def hero(title: str, subtitle: str, tag: str = ""):
    tag_html = f'<div class="tag">{esc(tag)}</div>' if tag else ""
    st.markdown(f'<div class="hero">{tag_html}<h1>{esc(title)}</h1><p>{esc(subtitle)}</p></div>',
                unsafe_allow_html=True)


def kpi(col, label: str, value: str, note: str = ""):
    note_html = f'<div class="kpi-note">{esc(note)}</div>' if note else ""
    col.markdown(f'<div class="card"><div class="kpi-label">{esc(label)}</div>'
                 f'<div class="kpi-value">{esc(value)}</div>{note_html}</div>', unsafe_allow_html=True)


def class_badge(cls: str) -> str:
    color = CLASS_COLORS.get(cls, MUTED)
    text = "#0b0b0b" if cls == "Withdrawn" else "#ffffff"
    return f'<span class="badge" style="background:{color};color:{text}">{esc(cls)}</span>'


# ------------------------------------------------------------------ charts
def _base_layout(fig: go.Figure, height: int = 320, **kw) -> go.Figure:
    fig.update_layout(
        height=height, margin=dict(l=10, r=20, t=30, b=10),
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family=FONT, color=INK_2, size=13),
        hoverlabel=dict(bgcolor="#ffffff", font=dict(family=FONT, color=INK)),
        barcornerradius=4, **kw,
    )
    fig.update_xaxes(gridcolor=GRID, zerolinecolor=AXIS, linecolor=AXIS, tickfont=dict(color=MUTED))
    fig.update_yaxes(gridcolor=GRID, zerolinecolor=AXIS, linecolor=AXIS, tickfont=dict(color=INK_2))
    return fig


def probability_chart(probabilities: dict) -> go.Figure:
    classes = list(probabilities)[::-1]
    vals = [probabilities[c] * 100 for c in classes]
    fig = go.Figure(go.Bar(
        x=vals, y=classes, orientation="h",
        marker=dict(color=[CLASS_COLORS[c] for c in classes], line=dict(color=SURFACE, width=2)),
        text=[f"{v:.1f}%" for v in vals], textposition="outside", textfont=dict(color=INK),
        hovertemplate="%{y}: %{x:.1f}%<extra></extra>", cliponaxis=False,
    ))
    _base_layout(fig, height=230, showlegend=False)
    fig.update_xaxes(range=[0, 112], ticksuffix="%", showgrid=True)
    fig.update_yaxes(showgrid=False)
    return fig


def contribution_chart(labels: list[str], values: list[float], hover: list[str],
                       xaxis_title: str, height: int | None = None) -> go.Figure:
    """Horizontal diverging bars (blue = pushes toward the class, red = away)."""
    colors = [POSITIVE if v >= 0 else NEGATIVE for v in values]
    fig = go.Figure(go.Bar(
        x=values, y=labels, orientation="h",
        marker=dict(color=colors, line=dict(color=SURFACE, width=2)),
        customdata=hover, hovertemplate="%{customdata}<br>Contribution: %{x:+.3f}<extra></extra>",
    ))
    _base_layout(fig, height=height or max(260, 34 * len(labels) + 60), showlegend=False)
    fig.update_xaxes(title=dict(text=xaxis_title, font=dict(color=MUTED, size=12)))
    fig.update_yaxes(showgrid=False, automargin=True)
    fig.add_vline(x=0, line_color=AXIS, line_width=1)
    return fig


def stacked_class_bars(df: pd.DataFrame, classes: list[str], height: int = 460) -> go.Figure:
    """df index = feature labels (top first), columns = classes."""
    fig = go.Figure()
    for cls in classes:
        fig.add_trace(go.Bar(
            name=cls, y=df.index[::-1], x=df[cls][::-1], orientation="h",
            marker=dict(color=CLASS_COLORS[cls], line=dict(color=SURFACE, width=2)),
            hovertemplate=f"{cls}<br>%{{y}}: %{{x:.3f}}<extra></extra>",
        ))
    _base_layout(fig, height=height, barmode="stack",
                 legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None, traceorder="normal"))
    fig.update_xaxes(title=dict(text="Mean |SHAP value|", font=dict(color=MUTED, size=12)))
    fig.update_yaxes(showgrid=False, automargin=True)
    return fig


def grouped_bars(df: pd.DataFrame, x: str, group: str, y: str, order: list[str],
                 labels: dict | None = None, height: int = 380) -> go.Figure:
    fig = go.Figure()
    for i, g in enumerate(order):
        sub = df[df[group] == g]
        fig.add_trace(go.Bar(
            name=(labels or {}).get(g, g), x=sub[x], y=sub[y],
            marker=dict(color=SERIES[i], line=dict(color=SURFACE, width=2)),
            text=[f"{v:.1f}" for v in sub[y]], textposition="outside", textfont=dict(color=INK_2, size=11),
            hovertemplate="%{x}<br>" + (labels or {}).get(g, g) + ": %{y:.2f}%<extra></extra>",
            cliponaxis=False,
        ))
    _base_layout(fig, height=height, barmode="group", bargap=0.25, bargroupgap=0.08,
                 legend=dict(orientation="h", yanchor="bottom", y=1.02, x=0, title=None))
    fig.update_yaxes(range=[0, 100], ticksuffix="%", title=dict(text="Test accuracy", font=dict(color=MUTED, size=12)))
    fig.update_xaxes(showgrid=False)
    return fig


def class_distribution_chart(counts: dict) -> go.Figure:
    classes = list(CLASS_COLORS)
    vals = [counts.get(c, 0) for c in classes]
    total = sum(vals)
    fig = go.Figure(go.Bar(
        x=classes, y=vals, marker=dict(color=[CLASS_COLORS[c] for c in classes], line=dict(color=SURFACE, width=2)),
        text=[f"{v:,}<br>({v / total * 100:.1f}%)" for v in vals], textposition="outside",
        textfont=dict(color=INK_2), hovertemplate="%{x}: %{y:,} students<extra></extra>", cliponaxis=False,
    ))
    _base_layout(fig, height=320, showlegend=False)
    fig.update_yaxes(range=[0, max(vals) * 1.25], title=dict(text="Students", font=dict(color=MUTED, size=12)))
    fig.update_xaxes(showgrid=False)
    return fig
