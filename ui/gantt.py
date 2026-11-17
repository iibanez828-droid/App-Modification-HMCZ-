"""Gantt interactivo (Plotly): plan original (barra gris delgada) y pronóstico
(barra de color según el estado), con la línea de hoy. Dos vistas: por
actividad de cada camión y por camión (ventana completa). Cada camión cierra
con Ready to Work (RTW, barra verde); los que requieren reemplazo de motor
llevan una bandera roja (Engine Service) al final de su RTW, y el tramo en que
un camión volvió temporalmente a operación se pinta de morado. La flota original y las máquinas en
operación (camiones agregados en la app) van en Gantt separados."""

from __future__ import annotations

from datetime import timedelta

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core import config
from core.project import Project, operation_periods, split_periods
from ui.common import T, act_name, esc, fmt_date, fmt_pct, fmt_ts, note, section

DAY_MS = 86_400_000
ACT_COLORS = {
    "completed": "#2E7D32", "in_progress": config.ORANGE, "overdue": "#C62828",
    "not_started": "#1565C0", "no_dates": "#6D4C41",
}


def gantt_panels(p: Project, t: T, trucks: list[str], mode: str, show_baseline: bool, key: str,
                 stamp: bool = False) -> None:
    """Gantt de la flota y, aparte, el Gantt Operating Machine (camiones agregados en la app).
    stamp: muestra abajo a la derecha de cada Gantt la fecha-hora del último registro de avance."""
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
        if stamp:
            _progress_stamp(p, t, selected)
    st.caption(t("gantt_help", days=config.RTW_DAYS) + " · " + t("op_legend") + " · 🚩 " + t("engine_flag"))


def _progress_stamp(p: Project, t: T, trucks: list[str]) -> None:
    ts = p.last_progress(trucks)
    tz = p.settings.get("timezone", "UTC")
    when = f"{fmt_ts(ts, tz)} ({tz})" if ts else "—"
    st.markdown(f'<div style="text-align:right;color:#A5A5A5;font-size:0.8rem;margin-top:-0.6rem">'
                f'{esc(t("last_progress", ts=when))}</div>', unsafe_allow_html=True)


def _rtw_trace(t: T, tr: pd.DataFrame, labels: list[str], show_baseline: bool) -> go.Bar | None:
    """Barra verde de Ready to Work (RTW) de cada camión (fila `labels`), después de su última actividad."""
    df = tr.assign(row=labels)
    df = df[df.rtw_start.notna() & df.rtw_end.notna()]
    if df.empty:
        return None
    x0 = pd.to_datetime(df.rtw_start)
    return go.Bar(
        y=df.row, x=(pd.to_datetime(df.rtw_end) + timedelta(days=1) - x0).dt.days * DAY_MS, base=x0,
        orientation="h", name=t("rtw"),
        marker=dict(color=config.RTW_COLOR, line=dict(color="#1A1A1A", width=0.5)),
        width=0.5, offset=-0.1 if show_baseline else -0.25,
        text=["RTW"] * len(df), textposition="inside", insidetextanchor="middle",
        textfont=dict(color="#1A1A1A", size=11),
        customdata=[[fmt_date(r.rtw_start), fmt_date(r.rtw_end)] for r in df.itertuples()],
        hovertemplate=("<b>%{y}</b><br>" + t("rtw") + ": %{customdata[0]} → %{customdata[1]}<br>"
                       + t("rtw_note", days=config.RTW_DAYS) + "<extra></extra>"),
    )


def _split_bars(df: pd.DataFrame, start_col: str, end_col: str, ycol: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Barras del pronóstico partidas por los tramos en que el camión volvió a operación.
    Devuelve los tramos de trabajo (el % va en el más largo) y los tramos en operación."""
    cols = [c for c in df.columns if c not in ("x0", "dur", "label")]
    pieces, gaps = [], []
    for _, r in df.iterrows():
        segs, ops = split_periods(r[start_col], r[end_col], operation_periods(r["truck"]))
        longest = max(segs, key=lambda se: (se[1] - se[0]).days, default=None)
        for a, b in segs:
            pieces.append({**{c: r[c] for c in cols}, "x0": pd.Timestamp(a), "dur": ((b - a).days + 1) * DAY_MS,
                           "label": fmt_pct(r["progress"]) if (a, b) == longest else ""})
        for a, b in ops:
            gaps.append({"y": r[ycol], "x0": pd.Timestamp(a), "dur": ((b - a).days + 1) * DAY_MS, "s": a, "e": b})
    return (pd.DataFrame(pieces, columns=cols + ["x0", "dur", "label"]),
            pd.DataFrame(gaps, columns=["y", "x0", "dur", "s", "e"]))


def _operation_trace(t: T, gaps: pd.DataFrame, show_baseline: bool, size: int) -> go.Bar | None:
    """Tramo morado "Returned to operation" dentro de la barra del pronóstico."""
    if gaps.empty:
        return None
    return go.Bar(
        y=gaps.y, x=gaps.dur, base=gaps.x0, orientation="h", name=t("op_period"),
        marker=dict(color=config.OPERATION_COLOR, line=dict(color="#1A1A1A", width=0.5)),
        width=0.5, offset=-0.1 if show_baseline else -0.25,
        text=[t("op_period")] * len(gaps), textposition="inside", insidetextanchor="middle",
        textfont=dict(color="white", size=size),
        customdata=[[fmt_date(r.s), fmt_date(r.e)] for r in gaps.itertuples()],
        hovertemplate=[("<b>%{y}</b><br>" + t("op_period") + ": %{customdata[0]} → %{customdata[1]}<br>"
                        + t("op_note", date=fmt_date(r.e + timedelta(days=1))) + "<extra></extra>")
                       for r in gaps.itertuples()],
    )


def _engine_flag_traces(t: T, tr: pd.DataFrame, labels: list[str]) -> list[go.Scatter]:
    """Bandera roja "Engine Service" justo después del RTW de los camiones que requieren reemplazo de motor.
    Un punto invisible unos días más allá deja espacio para el texto en la escala automática."""
    df = tr.assign(row=labels)
    df = df[df.engine_service & df.rtw_end.notna()]
    if df.empty:
        return []
    x = pd.to_datetime(df.rtw_end) + timedelta(days=1)
    return [
        go.Scatter(
            y=df.row, x=x, mode="markers+text", name=t("engine_flag"),
            marker=dict(symbol="triangle-right", size=15, color=config.ENGINE_FLAG_COLOR,
                        line=dict(color="#1A1A1A", width=0.5)),
            text=[t("engine_short")] * len(df), textposition="middle right",
            textfont=dict(color=config.ENGINE_FLAG_COLOR, size=11, family="Barlow, sans-serif"),
            cliponaxis=False,
            customdata=[[fmt_date(r.rtw_end)] for r in df.itertuples()],
            hovertemplate=("<b>%{y}</b><br>🚩 " + t("engine_flag") + "<br>" + t("rtw") + " → %{customdata[0]}"
                           "<extra></extra>"),
        ),
        go.Scatter(y=df.row, x=x + timedelta(days=12), mode="markers", marker=dict(opacity=0),
                   showlegend=False, hoverinfo="skip"),
    ]


def gantt_figure(p: Project, t: T, trucks: list[str], show_baseline: bool = True) -> go.Figure:
    acts = p.activities[p.activities.truck.isin(trucks)].sort_values(["truck", "order"]).copy()
    acts["row"] = [f"{r.truck} · {act_name(t, r.act_key)}" for r in acts.itertuples()]
    tr = p.trucks[p.trucks.truck.isin(trucks)].sort_values("truck")
    rtw_rows = [f"{truck} · {t('rtw')}" for truck in tr.truck]
    # Filas de arriba hacia abajo: las actividades de cada camión, su tramo en operación (si lo tiene) y su RTW
    rows: list[str] = []
    gaps = []
    for r, rtw_row in zip(tr.itertuples(), rtw_rows):
        rows += acts[acts.truck == r.truck].row.tolist()
        periods = operation_periods(r.truck)
        if periods:
            op_row = f"{r.truck} · {t('op_period')}"
            rows.append(op_row)
            ops = split_periods(r.start, r.end, periods)[1] if r.start and r.end else periods
            gaps += [{"y": op_row, "x0": pd.Timestamp(a), "dur": ((b - a).days + 1) * DAY_MS, "s": a, "e": b}
                     for a, b in ops]
        rows.append(rtw_row)
    gaps = pd.DataFrame(gaps, columns=["y", "x0", "dur", "s", "e"])
    fig = go.Figure()

    def bars(start_col: str, end_col: str) -> pd.DataFrame:
        df = acts[acts[start_col].notna() & acts[end_col].notna()].copy()
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

    op = _operation_trace(t, gaps, show_baseline, 11)  # fila propia, sin tapar las actividades
    if op is not None:
        fig.add_trace(op)
    rtw = _rtw_trace(t, tr, rtw_rows, show_baseline)
    if rtw is not None:
        fig.add_trace(rtw)
    fig.add_traces(_engine_flag_traces(t, tr, rtw_rows))

    # Separadores entre camiones, debajo de cada fila RTW salvo la última. El eje
    # cuenta las filas desde abajo (categoryarray invertido en _finish).
    for rtw_row in rtw_rows[:-1]:
        fig.add_hline(y=len(rows) - rows.index(rtw_row) - 1.5, line=dict(color="#DDDDDD", width=1))
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
    f, gaps = _split_bars(tr[tr.start.notna() & tr.end.notna()], "start", "end", "truck")
    for status, color in config.STATUS_COLORS.items():
        g = f[f.status == status]
        if g.empty:
            continue
        fig.add_trace(go.Bar(
            y=g.truck, x=g.dur, base=g.x0, orientation="h", name=t("st_" + status),
            marker=dict(color=color, line=dict(color="#1A1A1A", width=0.5)),
            width=0.5, offset=-0.1 if show_baseline else -0.25,
            text=g.label, textposition="inside", insidetextanchor="middle",
            textfont=dict(color="white", size=12),
            customdata=[[fmt_date(r.start), fmt_date(r.end), fmt_pct(r.progress), f"{r.delay_wd:+d}", r.work_days]
                        for r in g.itertuples()],
            hovertemplate=("<b>%{y}</b><br>" + t("forecast") + ": %{customdata[0]} → %{customdata[1]}"
                           "<br>" + t("progress") + ": %{customdata[2]}<br>" + t("delay_wd") + ": %{customdata[3]}"
                           "<br>" + t("own_work_days") + ": %{customdata[4]}<extra></extra>"),
        ))
    op = _operation_trace(t, gaps, show_baseline, 11)
    if op is not None:
        fig.add_trace(op)
    rtw = _rtw_trace(t, tr, rows, show_baseline)  # en la misma fila del camión, después de su pronóstico
    if rtw is not None:
        fig.add_trace(rtw)
    fig.add_traces(_engine_flag_traces(t, tr, rows))
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
