"""Gantt en PDF (A4 horizontal, membrete LANDCROS) para la vista pública: el
mismo Gantt de la pantalla (por camión o por actividad, con o sin el plan
original), con la fecha-hora del último registro de avance de cada Gantt."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from core import config
from core.executive_report import (BAR_BASE, BLACK, GREY, LINE, MARGIN, ORANGE, STATUS_RGB, WHITE, _fd, _Report,
                                   _txt, t)
from core.project import Project

STAMP = (165, 165, 165)  # gris claro del sello "último avance"
GROUPS = (("fleet", "Gantt truck modification"), ("operating", "Gantt operating machine"))
TRUCK_LEGEND = ("completed", "in_progress", "overdue", "upcoming", "future")
ACTIVITY_LEGEND = ("completed", "in_progress", "overdue", "not_started")


def _rows(p: Project, trucks: list[str], by_activity: bool) -> list[dict]:
    """Filas del Gantt: etiqueta, fechas del pronóstico y del plan original, estado y avance."""
    acts = p.activities[p.activities.truck.isin(trucks)]
    if by_activity:
        out = []
        for r in acts.sort_values(["truck", "order"]).itertuples():
            act = config.activity(r.act_key)
            name = (act.name or t(f"act_{r.act_key}")) + (" (ext.)" if r.external else "")
            out.append({"truck": r.truck, "label": name, "start": r.fc_start, "end": r.fc_end,
                        "base_start": r.base_start, "base_end": r.base_end, "status": r.status, "progress": r.progress})
        return out
    base_start = acts.groupby("truck").base_start.agg(lambda s: min((d for d in s if d), default=None))
    return [{"truck": r.truck, "label": r.truck, "start": r.start, "end": r.end, "base_start": base_start.get(r.truck),
             "base_end": r.base_end, "status": r.status, "progress": r.progress}
            for r in p.trucks[p.trucks.truck.isin(trucks)].sort_values("truck").itertuples()]


def _chart(pdf: _Report, p: Project, rows: list[dict], by_activity: bool, show_baseline: bool) -> None:
    dates = [r[c] for r in rows for c in ("start", "end") + (("base_start", "base_end") if show_baseline else ())
             if r[c]] + [p.today]
    lo, hi = min(dates) - timedelta(days=2), max(dates) + timedelta(days=3)
    span = max((hi - lo).days, 1)
    truck_w, label_w = (16, 58) if by_activity else (0, 18)
    row_h = 5 if by_activity else 7
    x0 = MARGIN + truck_w + label_w
    w = pdf.content_w - truck_w - label_w
    bottom = pdf.h - 24  # deja lugar para la leyenda y el sello al pie

    def xpos(d: date) -> float:
        return x0 + w * (d - lo).days / span

    def start_segment(remaining: int) -> float:
        """Escala semanal y líneas de la grilla del tramo de filas que cabe en la página (antes de las barras)."""
        top = pdf.get_y() + 5
        end = top + row_h * min(remaining, int((bottom - top) // row_h))
        pdf.set_font("Helvetica", "", 6.5)
        pdf.set_text_color(*GREY)
        pdf.set_draw_color(*LINE)
        d = lo + timedelta(days=(7 - lo.weekday()) % 7)  # lunes
        while d <= hi:
            pdf.line(xpos(d), top, xpos(d), end)
            if xpos(d) + 6 <= MARGIN + pdf.content_w:
                pdf.set_xy(xpos(d) - 6, top - 4.5)
                pdf.cell(12, 4, d.strftime("%d-%b"), align="C")
            d += timedelta(days=7)
        return top

    def today_line(top: float, end: float) -> None:
        pdf.set_draw_color(*ORANGE)
        pdf.set_line_width(0.5)
        pdf.set_dash_pattern(dash=1.2, gap=0.8)
        pdf.line(xpos(p.today), top - 1, xpos(p.today), end)
        pdf.set_dash_pattern()
        pdf.set_line_width(0.2)

    top = start_segment(len(rows))
    y, prev_truck = top, None
    for n, r in enumerate(rows):
        if y + row_h > bottom:  # salto de página: cierra el tramo y repite la escala
            today_line(top, y)
            pdf.add_page()
            top = start_segment(len(rows) - n)
            y, prev_truck = top, None
        if by_activity and r["truck"] != prev_truck:
            if prev_truck is not None:
                pdf.set_draw_color(*LINE)
                pdf.line(MARGIN, y, MARGIN + pdf.content_w, y)
            pdf.set_xy(MARGIN, y)
            pdf.set_font("Helvetica", "B", 7.5)
            pdf.set_text_color(*BLACK)
            pdf.cell(truck_w, row_h, r["truck"])
        prev_truck = r["truck"]
        pdf.set_xy(MARGIN + truck_w, y)
        pdf.set_font("Helvetica", "" if by_activity else "B", 6.5 if by_activity else 7.5)
        pdf.set_text_color(*BLACK)
        pdf.cell(label_w, row_h, _txt(r["label"]))
        if show_baseline and r["base_start"] and r["base_end"]:
            pdf.set_fill_color(*BAR_BASE)
            pdf.rect(xpos(r["base_start"]), y + row_h * 0.12,
                     xpos(r["base_end"] + timedelta(days=1)) - xpos(r["base_start"]), row_h * 0.2, "F")
        if r["start"] and r["end"]:
            bx, bw = xpos(r["start"]), xpos(r["end"] + timedelta(days=1)) - xpos(r["start"])
            by, bh = y + row_h * (0.38 if show_baseline else 0.2), row_h * (0.5 if show_baseline else 0.6)
            pdf.set_fill_color(*STATUS_RGB.get(r["status"], GREY))
            pdf.rect(bx, by, bw, bh, "F")
            if bw > 8:
                pdf.set_xy(bx, by)
                pdf.set_font("Helvetica", "B", 5.5 if by_activity else 6.5)
                pdf.set_text_color(*WHITE)
                pdf.cell(bw, bh, f"{r['progress'] * 100:.0f}%", align="C")
        y += row_h
    today_line(top, y)
    pdf.set_y(y + 2)


def _legend_and_stamp(pdf: _Report, p: Project, trucks: list[str], by_activity: bool, show_baseline: bool) -> None:
    """Leyenda a la izquierda y, en gris claro abajo a la derecha, la fecha-hora del último registro de avance."""
    y = pdf.get_y()
    legend = ([("Original plan", BAR_BASE)] if show_baseline else []) + \
             [(t("st_" + s), STATUS_RGB[s]) for s in (ACTIVITY_LEGEND if by_activity else TRUCK_LEGEND)]
    pdf.set_font("Helvetica", "", 6.5)
    pdf.set_text_color(*GREY)
    x = MARGIN
    for label, rgb in legend:
        pdf.set_fill_color(*rgb)
        pdf.rect(x, y + 1.2, 3, 2, "F")
        pdf.set_xy(x + 4, y)
        pdf.cell(22, 4.5, _txt(label))
        x += 26
    pdf.set_fill_color(*ORANGE)
    pdf.rect(x, y + 2, 3, 0.5, "F")
    pdf.set_xy(x + 4, y)
    pdf.cell(20, 4.5, "Today")

    ts = p.last_progress(trucks)
    tz = p.settings.get("timezone", "UTC")
    when = f"{pd.Timestamp(ts).tz_convert(tz):%d-%b-%Y %H:%M} ({tz})" if ts else "no records yet"
    pdf.set_xy(MARGIN, y)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(*STAMP)
    pdf.cell(pdf.content_w, 4.5, _txt(f"Last progress update: {when}"), align="R")
    pdf.set_y(y + 8)


def build_gantt_pdf(p: Project, by_activity: bool = False, show_baseline: bool = True) -> bytes:
    pdf = _Report(p.today, "GANTT REPORT", orientation="L")
    pdf.alias_nb_pages()
    pdf.add_page()
    view = "by activity" if by_activity else "by truck"
    for group, title in GROUPS:
        trucks = p.group_trucks(group)
        if not trucks:
            continue
        rows = _rows(p, trucks, by_activity)
        pdf.section(f"{title} ({view})", need=min(len(rows), 6) * 7 + 25)
        _chart(pdf, p, rows, by_activity, show_baseline)
        _legend_and_stamp(pdf, p, trucks, by_activity, show_baseline)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(*GREY)
    pdf.cell(pdf.content_w, 4, _txt(f"Generated {_fd(p.today)} ({p.settings.get('timezone', 'UTC')}) from the HCMZ "
                                    "tracking app. Grey bar = original plan - coloured bar = forecast "
                                    "(colour = status, label = progress)."), new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
