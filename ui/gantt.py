"""Gantt interactivo (Plotly): plan original (barra gris delgada) y pronóstico
(barra de color según el estado), con la línea de hoy. Dos vistas: por
actividad de cada camión y por camión (ventana completa). La flota original y
las máquinas en operación (camiones agregados en la app) van en Gantt separados."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import config
from core.project import Project
from ui.common import T, act_name, fmt_date, fmt_pct, note, section

DAY_MS = 86_400_000
ACT_COLORS = {
    "completed": "#2E7D32", "in_progress": config.ORANGE, "overdue": "#C62828",
    "not_started": "#1565C0", "no_dates": "#6D4C41",
}


def gantt_panels(p: Project, t: T, trucks: list[str], mode: str, show_baseline: bool, key: str) -> None:
    """Gantt de la flota y, aparte, el Gantt Operating Machine (camiones agregados en la app)."""
    build = truck_gantt_figure if mode == "truck" else gantt_figure
    for group in ("fleet", "operating"):
        section(t(f"gantt_{group}_title"))
        members = p.group_trucks(group)
        selected = sorted(tr for tr in trucks if tr in members)
        if not selected:
            note(t("no_operating_trucks") if group == "operating" and not members else t("select_trucks"))
            continue
        st.plotly_chart(build(p, t, selected, show_baseline), width="stretch", key=f"{key}_{group}",
                        config={"displaylogo": False, "modeBarButtonsToRemove": ["select2d", "lasso2d"]})
    st.caption(t("gantt_help"))


def gantt_figure(p: Project, t: T, trucks: list[str], show_baseline: bool = True) -> go.Figure:
    acts = p.activities[p.activities.truck.isin(trucks)].sort_values(["truck", "order"])
    rows = [f"{r.truck} · {act_name(t, r.act_key)}" for r in acts.itertuples()]
    fig = go.Figure()

    def bars(start_col: str, end_col: str) -> pd.DataFrame:
        df = acts.copy()
        df["row"] = rows
        df = df[df[start_col].notna() & df[end_col].notna()]
        df["x0"] = pd.to_datetime(df[start_col])
        df["dur"] = (pd.to_datetime(df[end_col]) + timedelta(days=1) - df["x0"]).dt.days * DAY_MS
        return df

    if show_baseline:
        b = bars("base_start", "base_end")
        fig.add_trace(go.Bar(
            y=b.row, x=b.dur, base=b.x0, orientation="h", name=t("original_plan"),
            marker=dict(color="#BDBDBD"), width=0.28, offset=-0.42,
            customdata=[[fmt_date(r.base_start), fmt_date(r.base_end)] for r in b.itertuples()],
            hovertemplate="<b>%{y}</b><br>" + t("original_plan") + ": %{customdata[0]} → %{customdata[1]}<extra></extra>",
        ))
    f = bars("fc_start", "fc_end")
    for status, color in ACT_COLORS.items():
        g = f[f.status == status]
        if g.empty:
            continue
        fig.add_trace(go.Bar(
            y=g.row, x=g.dur, base=g.x0, orientation="h", name=t("st_" + status),
            marker=dict(color=color, line=dict(color="#1A1A1A", width=0.5)),
            width=0.5, offset=-0.1 if show_baseline else -0.25,
            text=[fmt_pct(v) for v in g.progress], textposition="inside", insidetextanchor="middle",
            textfont=dict(color="white", size=11),
            customdata=[[fmt_date(r.fc_start), fmt_date(r.fc_end), fmt_pct(r.progress), r.delay_wd,
                         t("external") if r.external else ""] for r in g.itertuples()],
            hovertemplate=("<b>%{y}</b> %{customdata[4]}<br>" + t("forecast") + ": %{customdata[0]} → %{customdata[1]}"
                           "<br>" + t("progress") + ": %{customdata[2]}<br>" + t("delay_wd") + ": %{customdata[3]}<extra></extra>"),
        ))

    # Separadores entre camiones
    for n in range(1, len(trucks)):
        count = (acts.truck.isin(trucks[:n])).sum()
        fig.add_hline(y=count - 0.5, line=dict(color="#DDDDDD", width=1))
    _finish(fig, p, t, rows)
    return fig


def truck_gantt_figure(p: Project, t: T, trucks: list[str], show_baseline: bool = True) -> go.Figure:
    """Una barra por camión: ventana completa del plan original y del pronóstico."""
    acts = p.activities[p.activities.truck.isin(trucks)]
    base_start = acts.groupby("truck").base_start.agg(lambda s: min((d for d in s if d), default=None))
    tr = p.trucks[p.trucks.truck.isin(trucks)].sort_values("truck").copy()
    tr["base_start"] = tr.truck.map(base_start)
    rows = tr.truck.tolist()
    fig = go.Figure()

    def bars(start_col: str, end_col: str) -> pd.DataFrame:
        df = tr[tr[start_col].notna() & tr[end_col].notna()].copy()
        df["x0"] = pd.to_datetime(df[start_col])
        df["dur"] = (pd.to_datetime(df[end_col]) + timedelta(days=1) - df["x0"]).dt.days * DAY_MS
        return df

    if show_baseline:
        b = bars("base_start", "base_end")
        fig.add_trace(go.Bar(
            y=b.truck, x=b.dur, base=b.x0, orientation="h", name=t("original_plan"),
            marker=dict(color="#BDBDBD"), width=0.28, offset=-0.42,
            customdata=[[fmt_date(r.base_start), fmt_date(r.base_end)] for r in b.itertuples()],
            hovertemplate="<b>%{y}</b><br>" + t("original_plan") + ": %{customdata[0]} → %{customdata[1]}<extra></extra>",
        ))
    f = bars("start", "end")
    for status, color in config.STATUS_COLORS.items():
        g = f[f.status == status]
        if g.empty:
            continue
        fig.add_trace(go.Bar(
            y=g.truck, x=g.dur, base=g.x0, orientation="h", name=t("st_" + status),
            marker=dict(color=color, line=dict(color="#1A1A1A", width=0.5)),
            width=0.5, offset=-0.1 if show_baseline else -0.25,
            text=[fmt_pct(v) for v in g.progress], textposition="inside", insidetextanchor="middle",
            textfont=dict(color="white", size=12),
            customdata=[[fmt_date(r.start), fmt_date(r.end), fmt_pct(r.progress), f"{r.delay_wd:+d}", r.work_days]
                        for r in g.itertuples()],
            hovertemplate=("<b>%{y}</b><br>" + t("forecast") + ": %{customdata[0]} → %{customdata[1]}"
                           "<br>" + t("progress") + ": %{customdata[2]}<br>" + t("delay_wd") + ": %{customdata[3]}"
                           "<br>" + t("own_work_days") + ": %{customdata[4]}<extra></extra>"),
        ))
    _finish(fig, p, t, rows, row_height=40)
    return fig


def _finish(fig: go.Figure, p: Project, t: T, rows: list[str], row_height: int = 26) -> None:
    fig.add_vline(x=pd.Timestamp(p.today).value / 1e6, line=dict(color=config.ORANGE, width=2, dash="dash"))
    fig.add_annotation(x=pd.Timestamp(p.today), y=1.0, yref="paper", text=t("today"), showarrow=False, xanchor="left",
                       font=dict(color=config.ORANGE, size=11), xshift=4, yshift=-8)
    fig.update_layout(
        barmode="overlay", height=max(320, row_height * len(rows) + 120),
        margin=dict(l=10, r=10, t=50, b=40), plot_bgcolor="white",
        legend=dict(orientation="h", yanchor="top", y=-0.01, x=0),
        font=dict(family="Barlow, sans-serif", size=12, color="#1A1A1A"),
        xaxis=dict(type="date", gridcolor="#EEEEEE", tickformat="%d-%b", dtick=7 * DAY_MS,
                   showgrid=True, side="top"),
        yaxis=dict(categoryorder="array", categoryarray=list(reversed(rows)), autorange=True),
        hoverlabel=dict(bgcolor="white"),
    )
