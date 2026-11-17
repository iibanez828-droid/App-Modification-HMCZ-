"""Gantt en PDF (A4 horizontal, membrete LANDCROS) para la vista pública: el
mismo Gantt de la pantalla (por camión o por actividad, con o sin el plan
original, con el Ready to Work de cada camión y la bandera Engine Service), con la fecha-hora del último
registro de avance de cada Gantt."""

from __future__ import annotations

from datetime import date, timedelta

import pandas as pd

from core import config
from core.executive_report import (BAR_BASE, BLACK, ENGINE_PAD_DAYS, ENGINE_RGB, GREY, LINE, MARGIN, OP_RGB, ORANGE,
                                   RTW_RGB, STATUS_RGB, _fd,
                                   _Report, _txt, t)
from core.project import Project, split_periods

STAMP = (165, 165, 165)  # gris claro del sello "último avance"
GROUPS = (("fleet", "Gantt truck modification"), ("operating", "Gantt operating machine"))
TRUCK_LEGEND = ("completed", "in_progress", "overdue", "upcoming", "future")
ACTIVITY_LEGEND = ("completed", "in_progress", "overdue", "not_started")


def _rows(p: Project, trucks: list[str], by_activity: bool) -> list[dict]:
    """Filas del Gantt: etiqueta, fechas del pronóstico y del plan original, estado, avance y Ready to Work.
    Por actividad, el RTW de cada camión es su última fila; por camión, va en la misma fila."""
    acts = p.activities[p.activities.truck.isin(trucks)]
    tr = p.trucks[p.trucks.truck.isin(trucks)].sort_values("truck")
    if by_activity:
        out = []
        for tk in tr.itertuples():
            for r in acts[acts.truck == tk.truck].sort_values("order").itertuples():
                act = config.activity(r.act_key)
                name = (act.name or t(f"act_{r.act_key}")) + (" (ext.)" if r.external else "")
                out.append({"truck": r.truck, "label": name, "start": r.fc_start, "end": r.fc_end,
                            "base_start": r.base_start, "base_end": r.base_end, "status": r.status,
                            "progress": r.progress, "rtw_start": None, "rtw_end": None, "engine": False,
                            "operation": []})
            if tk.operation:  # fila propia para el tramo en operación, sin tapar las actividades
                ops = split_periods(tk.start, tk.end, tk.operation)[1] if tk.start and tk.end else tk.operation
                out += [{"truck": tk.truck, "label": t("op_period"), "start": a, "end": b, "base_start": None,
                         "base_end": None, "status": "operation", "progress": 0.0, "rtw_start": None,
                         "rtw_end": None, "engine": False, "operation": [(a, b)]} for a, b in ops]
            out.append({"truck": tk.truck, "label": t("rtw"), "start": None, "end": None, "base_start": None,
                        "base_end": None, "status": "rtw", "progress": 0.0,
                        "rtw_start": tk.rtw_start, "rtw_end": tk.rtw_end, "engine": tk.engine_service,
                        "operation": []})
        return out
    base_start = acts.groupby("truck").base_start.agg(lambda s: min((d for d in s if d), default=None))
    return [{"truck": r.truck, "label": r.truck, "start": r.start, "end": r.end, "base_start": base_start.get(r.truck),
             "base_end": r.base_end, "status": r.status, "progress": r.progress,
             "rtw_start": r.rtw_start, "rtw_end": r.rtw_end, "engine": r.engine_service,
             "operation": r.operation}
            for r in tr.itertuples()]


def _chart(pdf: _Report, p: Project, rows: list[dict], by_activity: bool, show_baseline: bool) -> None:
    cols = ("start", "end", "rtw_end") + (("base_start", "base_end") if show_baseline else ())
    dates = ([r[c] for r in rows for c in cols if r[c]] + [p.today]
             + [r["rtw_end"] + timedelta(days=ENGINE_PAD_DAYS) for r in rows if r["engine"] and r["rtw_end"]])
    lo, hi = min(dates) - timedelta(days=2), max(dates) + timedelta(days=3)
    span = max((hi - lo).days, 1)
    truck_w, label_w = (16, 58) if by_activity else (0, 18)
    row_h = 5 if by_activity else 7
    x0 = MARGIN + truck_w + label_w
    w = pdf.content_w - truck_w - label_w
    bottom = pdf.h - 27  # deja lugar para la leyenda y el sello al pie

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
        by, bh = y + row_h * (0.38 if show_baseline else 0.2), row_h * (0.5 if show_baseline else 0.6)
        size = 5.5 if by_activity else 6.5
        if r["start"] and r["end"]:
            pdf.forecast_bar(xpos, r["start"], r["end"], r["operation"], by, bh, STATUS_RGB.get(r["status"], GREY),
                             f"{r['progress'] * 100:.0f}%", size, 8)
        if r["rtw_start"] and r["rtw_end"]:
            pdf.rtw_bar(xpos(r["rtw_start"]), by, xpos(r["rtw_end"] + timedelta(days=1)) - xpos(r["rtw_start"]), bh,
                        size)
            if r["engine"]:
                pdf.engine_flag(xpos(r["rtw_end"] + timedelta(days=1)) + 0.4, y + row_h * 0.1, row_h * 0.8, size)
        y += row_h
    today_line(top, y)
    pdf.set_y(y + 2)


def _legend_and_stamp(pdf: _Report, p: Project, trucks: list[str], by_activity: bool, show_baseline: bool) -> None:
    """Leyenda a la izquierda y, en gris claro abajo a la derecha, la fecha-hora del último registro de avance."""
    y = pdf.get_y()
    lines = pdf.legend(([("Original plan", BAR_BASE)] if show_baseline else [])
               + [(t("st_" + s), STATUS_RGB[s]) for s in (ACTIVITY_LEGEND if by_activity else TRUCK_LEGEND)]
               + [(t("rtw"), RTW_RGB)]
               + ([(t("op_period"), OP_RGB)] if p.trucks[p.trucks.truck.isin(trucks)].operation.map(bool).any() else [])
               + ([(t("engine_short"), ENGINE_RGB)] if p.trucks[p.trucks.truck.isin(trucks)].engine_service.any() else []))

    ts = p.last_progress(trucks)
    tz = p.settings.get("timezone", "UTC")
    when = f"{pd.Timestamp(ts).tz_convert(tz):%d-%b-%Y %H:%M} ({tz})" if ts else "no records yet"
    pdf.set_xy(MARGIN, y + 4.5 * lines)  # en su propia línea, debajo de la leyenda
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(*STAMP)
    pdf.cell(pdf.content_w, 4.5, _txt(f"Last progress update: {when}"), align="R")
    pdf.set_y(y + 6.5 + 4.5 * lines)


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
    pdf.multi_cell(pdf.content_w, 4, _txt(f"Generated {_fd(p.today)} ({p.settings.get('timezone', 'UTC')}) from the "
                                          "HCMZ tracking app. Grey bar = original plan - coloured bar = forecast "
                                          "(colour = status, label = progress) - light green = Ready to Work (RTW): "
                                          f"right after each truck's last activity, {config.RTW_DAYS} working days "
                                          "(Mon-Fri); a weekend finish extends it to Tuesday. Purple = truck temporarily returned "
                                          "to operation (modification paused). Red flag = engine replacement "
                                          "required (Engine Service)."),
                   new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
