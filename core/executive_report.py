"""Reporte ejecutivo en PDF con membrete LANDCROS: resumen del proyecto por
camión (fechas, atrasos, avance) y resumen general de las actividades de toda
la flota. No incluye el detalle de cada actividad por camión."""

from __future__ import annotations

import io
from datetime import date, timedelta

from fpdf import FPDF

from core import config
from core.i18n import translator
from core.project import VISIBLE_STATUSES, Project, split_periods

t = translator("en")

BLACK = (26, 26, 26)
ORANGE = (255, 107, 0)
GREY = (136, 136, 136)
LIGHT = (247, 247, 247)
LINE = (221, 221, 221)
WHITE = (255, 255, 255)
BAR_BASE = (214, 214, 214)


def _rgb(hex_color: str) -> tuple[int, int, int]:
    return tuple(int(hex_color[i:i + 2], 16) for i in (1, 3, 5))


STATUS_RGB = {k: _rgb(v) for k, v in config.STATUS_COLORS.items()}
STATUS_RGB["not_started"] = STATUS_RGB["upcoming"]
RTW_RGB = _rgb(config.RTW_COLOR)
ENGINE_RGB = _rgb(config.ENGINE_FLAG_COLOR)
OP_RGB = _rgb(config.OPERATION_COLOR)
ENGINE_PAD_DAYS = 12  # días extra a la derecha de la escala para el texto de la bandera

PAGE_W, MARGIN = 210, 12
CONTENT_W = PAGE_W - 2 * MARGIN


def _fd(d: date | None) -> str:
    return d.strftime("%d-%b-%Y") if isinstance(d, date) else "-"


def _txt(text: object) -> str:
    """Las fuentes estándar del PDF solo admiten latin-1."""
    return str(text).replace("→", "->").replace("·", "-").encode("latin-1", "replace").decode("latin-1")


class _Report(FPDF):
    """Hoja con membrete LANDCROS. Vertical para el reporte ejecutivo; horizontal ("L") para el Gantt."""

    def __init__(self, today: date, title: str = "EXECUTIVE PROGRESS REPORT", orientation: str = "P") -> None:
        super().__init__(orientation=orientation, unit="mm", format="A4")
        self.today = today
        self.heading = title
        self.content_w = self.w - 2 * MARGIN
        self.set_margins(MARGIN, 36, MARGIN)
        self.set_auto_page_break(True, margin=16)
        self.set_title(f"{config.PROJECT_NAME} - {title.capitalize()} {today.isoformat()}")
        self.set_author("LANDCROS")

    def header(self) -> None:
        self.set_fill_color(*BLACK)
        self.rect(0, 0, self.w, 26, "F")
        self.set_fill_color(*ORANGE)
        self.rect(0, 26, self.w, 1.6, "F")
        if config.LOGO_PATH.exists():
            self.image(str(config.LOGO_PATH), x=MARGIN, y=7, h=12)
        self.set_xy(80, 6.5)
        self.set_text_color(*WHITE)
        self.set_font("Helvetica", "B", 15)
        self.cell(self.w - 80 - MARGIN, 7, self.heading, align="R")
        self.set_xy(80, 14)
        self.set_font("Helvetica", "", 8.5)
        self.set_text_color(170, 170, 170)
        self.cell(self.w - 80 - MARGIN, 5, _txt(f"{config.PROJECT_NAME.upper()} - {config.FLEET} FLEET - "
                                                 f"{_fd(self.today).upper()}"), align="R")
        # Crédito del equipo de desarrollo con la bandera de Canadá, alineado a la derecha
        self.set_font("Helvetica", "", 7)
        text = _txt(config.DEV_CREDIT)
        x_text = self.w - MARGIN - self.c_margin - self.get_string_width(text)  # mismo borde que la línea de arriba
        self.image(io.BytesIO(config.CANADA_FLAG_SVG.encode()), x=x_text - 7, y=19.6, w=6, h=3)
        self.set_xy(80, 19)
        self.cell(self.w - 80 - MARGIN, 4.2, text, align="R")
        self.set_y(36)

    def footer(self) -> None:
        self.set_y(-11)
        self.set_draw_color(*LINE)
        self.line(MARGIN, self.get_y() - 1, self.w - MARGIN, self.get_y() - 1)
        self.set_font("Helvetica", "", 7.5)
        self.set_text_color(*GREY)
        self.cell(self.content_w / 2, 5, _txt(f"LANDCROS - {config.PROJECT_NAME}"))
        self.cell(self.content_w / 2, 5, f"Page {self.page_no()}/{{nb}}", align="R")

    # ── Bloques ─────────────────────────────────────────────────────────
    def section(self, title: str, need: float = 30) -> None:
        """need: alto mínimo (mm) del contenido que sigue, para no dejar el título solo al pie de página."""
        if self.get_y() + need > self.h - 17:
            self.add_page()
        self.ln(3)
        self.set_font("Helvetica", "B", 10.5)
        self.set_text_color(*BLACK)
        self.cell(self.content_w, 6, title.upper(), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*ORANGE)
        self.set_line_width(0.6)
        self.line(MARGIN, self.get_y(), self.w - MARGIN, self.get_y())
        self.set_line_width(0.2)
        self.ln(3)

    def kpis(self, items: list[tuple[str, str, str, tuple]]) -> None:
        gap = 2.5
        w = (CONTENT_W - gap * (len(items) - 1)) / len(items)
        y = self.get_y()
        for n, (label, value, sub, color) in enumerate(items):
            x = MARGIN + n * (w + gap)
            self.set_fill_color(*LIGHT)
            self.rect(x, y, w, 20, "F")
            self.set_fill_color(*color)
            self.rect(x, y, 1.2, 20, "F")
            self.set_xy(x + 3, y + 2)
            self.set_font("Helvetica", "B", 6.5)
            self.set_text_color(*GREY)
            self.cell(w - 4, 3.5, label.upper())
            self.set_xy(x + 3, y + 6.5)
            self.set_font("Helvetica", "B", 15)
            self.set_text_color(*BLACK)
            self.cell(w - 4, 7, _txt(value))
            self.set_xy(x + 3, y + 14.5)
            self.set_font("Helvetica", "", 6.5)
            self.set_text_color(*GREY)
            self.cell(w - 4, 3.5, _txt(sub))
        self.set_y(y + 23)

    def table_head(self, cols: list[tuple[str, float, str]]) -> None:
        self.set_fill_color(*BLACK)
        self.set_text_color(*WHITE)
        self.set_font("Helvetica", "B", 7.5)
        for title, w, align in cols:
            self.cell(w, 6.5, title, fill=True, align=align)
        self.ln()

    def pill(self, x: float, y: float, w: float, status: str) -> None:
        self.set_fill_color(*STATUS_RGB.get(status, GREY))
        self.rect(x + 1, y + 1.4, w - 2, 4.2, "F")
        self.set_xy(x + 1, y + 1.4)
        self.set_font("Helvetica", "B", 6.5)
        self.set_text_color(*WHITE)
        self.cell(w - 2, 4.2, t("st_" + status).upper(), align="C")

    def progress_bar(self, x: float, y: float, w: float, value: float) -> None:
        bar_w = w - 13
        self.set_fill_color(230, 230, 230)
        self.rect(x + 1, y + 2.3, bar_w, 2.4, "F")
        if value > 0:
            self.set_fill_color(*(STATUS_RGB["completed"] if value >= 1 else ORANGE))
            self.rect(x + 1, y + 2.3, bar_w * min(value, 1), 2.4, "F")
        self.set_xy(x + bar_w + 1, y)
        self.set_font("Helvetica", "B", 7.5)
        self.set_text_color(*BLACK)
        self.cell(12, 7, f"{value * 100:.0f}%", align="R")

    def rtw_bar(self, x: float, y: float, w: float, h: float, size: float = 6) -> None:
        """Barra verde de Ready to Work (RTW); lleva el texto "RTW" si cabe."""
        self.set_fill_color(*RTW_RGB)
        self.rect(x, y, w, h, "F")
        if w > 6:
            self.set_xy(x, y)
            self.set_font("Helvetica", "B", size)
            self.set_text_color(*BLACK)
            self.cell(w, h, "RTW", align="C")

    def forecast_bar(self, xpos, start: date, end: date, periods: list, y: float, h: float, rgb: tuple,
                     label: str, size: float, min_label_w: float) -> None:
        """Barra del pronóstico partida por los tramos en que el camión volvió a operación (en morado,
        con "Returned to operation" si cabe). El % va en el tramo de trabajo más largo."""
        segs, ops = split_periods(start, end, periods)
        longest = max(segs, key=lambda se: (se[1] - se[0]).days, default=None)
        self.set_font("Helvetica", "B", size)
        for (a, b), fill, text in ([(se, rgb, label if se == longest else "") for se in segs]
                                   + [(se, OP_RGB, "Returned to operation") for se in ops]):
            x, w = xpos(a), xpos(b + timedelta(days=1)) - xpos(a)
            self.set_fill_color(*fill)
            self.rect(x, y, w, h, "F")
            if text and w > min_label_w and self.get_string_width(text) < w - 1:
                self.set_xy(x, y)
                self.set_text_color(*WHITE)
                self.cell(w, h, text, align="C")

    def engine_flag(self, x: float, y: float, h: float, size: float = 6) -> None:
        """Bandera roja de reemplazo de motor (Engine Service) en x, en una fila de alto h que empieza en y."""
        self.set_draw_color(*BLACK)
        self.set_line_width(0.3)
        self.line(x, y, x, y + h)
        self.set_fill_color(*ENGINE_RGB)
        self.polygon([(x, y), (x + h * 0.9, y + h * 0.3), (x, y + h * 0.6)], style="F")
        self.set_line_width(0.2)
        self.set_xy(x + h * 0.9 + 0.5, y)
        self.set_font("Helvetica", "B", size)
        self.set_text_color(*ENGINE_RGB)
        self.cell(self.get_string_width("Engine Service") + 1, h * 0.6, "Engine Service")

    def legend(self, items: list[tuple[str, tuple]]) -> int:
        """Leyenda del Gantt en una línea, en la posición actual: muestras de color y la línea de hoy.
        Cada elemento ocupa el ancho de su texto; si no cabe en la línea, pasa a la siguiente.
        Devuelve el número de líneas usadas."""
        y, x, lines = self.get_y(), MARGIN, 1
        right = self.w - MARGIN
        self.set_font("Helvetica", "", 6.5)
        self.set_text_color(*GREY)
        for label, rgb in [(_txt(lbl), rgb) for lbl, rgb in items] + [("Today", None)]:
            if x + 4 + self.get_string_width(label) > right:
                x, y, lines = MARGIN, y + 4.5, lines + 1
            if rgb is None:  # línea de hoy
                self.set_fill_color(*ORANGE)
                self.rect(x, y + 2, 3, 0.5, "F")
                self.set_xy(x + 4, y)
                self.cell(20, 4.5, label)
                break
            self.set_fill_color(*rgb)
            self.rect(x, y + 1.2, 3, 2, "F")
            self.set_xy(x + 4, y)
            self.cell(self.get_string_width(label) + 1, 4.5, label)
            x += self.get_string_width(label) + 10
        return lines


# ─── Contenido ────────────────────────────────────────────────────────────
def _summary_text(p: Project) -> list[str]:
    tr = p.trucks
    counts = tr.status.value_counts()
    n = len(tr)
    active = counts.get("in_progress", 0) + counts.get("overdue", 0)
    lines = [f"Overall fleet progress is {tr.progress.mean() * 100:.0f}%: {counts.get('completed', 0)} of {n} trucks "
             f"completed, {active} in execution ({counts.get('overdue', 0)} overdue) and "
             f"{counts.get('upcoming', 0)} starting within {p.settings.get('lookahead_days', 14)} days."]
    ends = [d for d in tr.end if d]
    bends = [d for d in tr.base_end if d]
    if ends and bends:
        diff = (max(ends) - max(bends)).days
        trend = "on the original date" if diff == 0 else (f"{diff} calendar days later than planned" if diff > 0
                                                         else f"{-diff} calendar days earlier than planned")
        lines.append(f"Forecast fleet completion: {_fd(max(ends))} (original plan {_fd(max(bends))}), {trend}.")
    late = tr[(tr.delay_wd > 0) & (tr.progress < 1)].sort_values("delay_wd", ascending=False)
    if len(late):
        worst = ", ".join(f"{r.truck} (+{r.delay_wd} wd)" for r in late.head(4).itertuples())
        lines.append(f"{len(late)} truck(s) behind the original plan. Largest delays: {worst}.")
    else:
        lines.append("No truck is behind its original plan.")
    over = tr[tr.over_limit & tr.status.isin(VISIBLE_STATUSES)]  # mismo criterio que las alertas de la app
    if len(over):
        lines.append(f"{len(over)} active or upcoming truck(s) exceed the limit of "
                     f"{p.settings.get('max_working_days', 5)} own working days: {', '.join(over.truck)}.")
    if len(p.delays):
        top = p.delays.groupby("category")["impact_days"].sum().sort_values(ascending=False)
        lines.append(f"{len(p.delays)} delay note(s) reported by supervisors; main cause: "
                     f"{t('dc_' + top.index[0])} ({top.iloc[0]:g} days of impact).")
    return lines


def _truck_table(pdf: _Report, p: Project) -> None:
    cols = [("Truck", 16, "L"), ("Status", 24, "C"), ("Progress", 34, "L"), ("Fcst start", 22, "C"),
            ("Fcst end", 22, "C"), ("Actual end", 22, "C"), ("Delay (wd)", 18, "C"), ("Own days", 14, "C"),
            ("MH", 14, "R")]
    pdf.table_head(cols)
    limit = int(p.settings.get("max_working_days", 5))
    for n, r in enumerate(p.trucks.sort_values("truck").itertuples()):
        y = pdf.get_y()
        if n % 2:
            pdf.set_fill_color(*LIGHT)
            pdf.rect(MARGIN, y, CONTENT_W, 7, "F")
        x = MARGIN
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(*BLACK)
        pdf.set_xy(x, y)
        pdf.cell(cols[0][1], 7, r.truck)
        x += cols[0][1]
        pdf.pill(x, y, cols[1][1], r.status)
        x += cols[1][1]
        pdf.progress_bar(x, y, cols[2][1], r.progress)
        x += cols[2][1]
        pdf.set_font("Helvetica", "", 7.5)
        delay = f"{r.delay_wd:+d}" if r.progress < 1 else "-"
        values = [_fd(r.start), _fd(r.end), _fd(r.base_end), delay, f"{r.work_days}/{limit}", f"{r.actual_mh:.1f}"]
        for (title, w, align), v in zip(cols[3:], values):
            pdf.set_xy(x, y)
            red = ((title == "Delay (wd)" and r.delay_wd > 0 and r.progress < 1)
                   or (title == "Own days" and r.over_limit and r.status in VISIBLE_STATUSES))
            pdf.set_text_color(*(STATUS_RGB["overdue"] if red else BLACK))
            pdf.set_font("Helvetica", "B" if red else "", 7.5)
            pdf.cell(w, 7, v, align=align)
            x += w
        pdf.set_y(y + 7)
    pdf.set_font("Helvetica", "", 6.5)
    pdf.set_text_color(*GREY)
    pdf.ln(1)
    pdf.multi_cell(CONTENT_W, 3.5, "Delay = working days between the actual end and the forecast end. "
                   f"Own days = working days with in-house work scheduled (limit {limit}; highlighted only for active or "
                   "upcoming trucks). MH = actual man-hours recorded.")


def _timeline(pdf: _Report, p: Project, trucks: list[str]) -> None:
    tr = p.trucks[p.trucks.truck.isin(trucks)].sort_values("truck")
    acts = p.activities[p.activities.truck.isin(trucks)]
    base_start = acts.groupby("truck").base_start.agg(lambda s: min((d for d in s if d), default=None))
    dates = ([d for col in ("start", "end", "base_end", "rtw_end") for d in tr[col] if d]
             + [d for d in base_start if d] + [p.today]
             + [r.rtw_end + timedelta(days=ENGINE_PAD_DAYS) for r in tr.itertuples() if r.engine_service and r.rtw_end])
    lo, hi = min(dates) - timedelta(days=2), max(dates) + timedelta(days=3)
    span = max((hi - lo).days, 1)
    label_w, row_h = 16, 6.2
    x0, w = MARGIN + label_w, CONTENT_W - label_w
    top = pdf.get_y() + 5

    def xpos(d: date) -> float:
        return x0 + w * (d - lo).days / span

    # Escala de meses/semanas
    pdf.set_font("Helvetica", "", 6.5)
    pdf.set_draw_color(*LINE)
    d = lo + timedelta(days=(7 - lo.weekday()) % 7)
    while d <= hi:
        pdf.line(xpos(d), top, xpos(d), top + row_h * len(tr))
        pdf.set_text_color(*GREY)
        pdf.set_xy(xpos(d) - 6, top - 4.5)
        pdf.cell(12, 4, d.strftime("%d-%b"), align="C")
        d += timedelta(days=7)
    for n, r in enumerate(tr.itertuples()):
        y = top + n * row_h
        pdf.set_xy(MARGIN, y + 0.9)
        pdf.set_font("Helvetica", "B", 7.5)
        pdf.set_text_color(*BLACK)
        pdf.cell(label_w, row_h, r.truck)
        bs = base_start.get(r.truck)
        if bs and r.base_end:
            pdf.set_fill_color(*BAR_BASE)
            pdf.rect(xpos(bs), y + 0.6, xpos(r.base_end + timedelta(days=1)) - xpos(bs), 1.4, "F")
        if r.start and r.end:
            pdf.forecast_bar(xpos, r.start, r.end, r.operation, y + 2.4, 3.2, STATUS_RGB.get(r.status, GREY),
                             f"{r.progress * 100:.0f}%", 6, 9)
        if r.rtw_start and r.rtw_end:
            pdf.rtw_bar(xpos(r.rtw_start), y + 2.4, xpos(r.rtw_end + timedelta(days=1)) - xpos(r.rtw_start), 3.2)
            if r.engine_service:
                pdf.engine_flag(xpos(r.rtw_end + timedelta(days=1)) + 0.4, y + 1.6, 4.2, 5.5)
    xt = xpos(p.today)
    pdf.set_draw_color(*ORANGE)
    pdf.set_line_width(0.5)
    pdf.set_dash_pattern(dash=1.2, gap=0.8)
    pdf.line(xt, top - 1, xt, top + row_h * len(tr))
    pdf.set_dash_pattern()
    pdf.set_line_width(0.2)
    y = top + row_h * len(tr) + 2
    pdf.set_xy(MARGIN, y)
    lines = pdf.legend([("Original plan", BAR_BASE)]
               + [(t("st_" + s), STATUS_RGB[s]) for s in ("completed", "in_progress", "overdue", "upcoming", "future")]
               + [(t("rtw"), RTW_RGB)]
               + ([(t("op_period"), OP_RGB)] if tr.operation.map(bool).any() else [])
               + ([(t("engine_short"), ENGINE_RGB)] if tr.engine_service.any() else []))
    pdf.set_y(y + 7 + 4.5 * (lines - 1))


def _plan_activities(p: Project) -> list[config.Activity]:
    present = set(p.activities.act_key)
    return [a for a in config.all_activities() if a.key in present]


def _activity_summary(pdf: _Report, p: Project) -> None:
    cols = [("Activity", 52, "L"), ("Completed", 18, "C"), ("In progress", 18, "C"), ("Not started", 18, "C"),
            ("Overdue", 16, "C"), ("Avg progress", 38, "L"), ("Behind plan", 26, "C")]
    pdf.table_head(cols)
    a = p.activities
    n_trucks = len(p.trucks)
    for n, act in enumerate(_plan_activities(p)):
        g = a[a.act_key == act.key]
        st_ = g.status.value_counts()
        y = pdf.get_y()
        if n % 2:
            pdf.set_fill_color(*LIGHT)
            pdf.rect(MARGIN, y, CONTENT_W, 7, "F")
        name = act.gantt_name + (" (ext.)" if act.external else "")
        values = [name, f"{st_.get('completed', 0)}/{n_trucks}", str(st_.get("in_progress", 0)),
                  str(st_.get("not_started", 0) + st_.get("no_dates", 0)), str(st_.get("overdue", 0))]
        x = MARGIN
        for (title, w, align), v in zip(cols[:5], values):
            pdf.set_xy(x, y)
            red = title == "Overdue" and v != "0"
            pdf.set_font("Helvetica", "B" if title == "Activity" or red else "", 7.5)
            pdf.set_text_color(*(STATUS_RGB["overdue"] if red else BLACK))
            pdf.cell(w, 7, _txt(v), align=align)
            x += w
        pdf.progress_bar(x, y, cols[5][1], float(g.progress.mean()) if len(g) else 0.0)
        x += cols[5][1]
        behind = int(((g.delay_wd > 0) & (g.progress < 1)).sum())
        pdf.set_xy(x, y)
        pdf.set_font("Helvetica", "B" if behind else "", 7.5)
        pdf.set_text_color(*(STATUS_RGB["overdue"] if behind else BLACK))
        pdf.cell(cols[6][1], 7, f"{behind} truck(s)" if behind else "-", align="C")
        pdf.set_y(y + 7)
    pdf.set_font("Helvetica", "", 6.5)
    pdf.set_text_color(*GREY)
    pdf.ln(1)
    pdf.multi_cell(CONTENT_W, 3.5, f"Counts are numbers of trucks (fleet of {n_trucks}). Behind plan = forecast end later "
                   "than the actual end. (ext.) = performed by an external contractor.")


def _delays(pdf: _Report, p: Project) -> None:
    d = p.delays
    if d.empty:
        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(*GREY)
        pdf.cell(CONTENT_W, 6, "No delay notes have been reported.", new_x="LMARGIN", new_y="NEXT")
        return
    by = d.groupby("category").agg(notes=("impact_days", "size"), days=("impact_days", "sum"),
                                   trucks=("truck", "nunique")).sort_values("days", ascending=False)
    cols = [("Cause", 70, "L"), ("Notes", 30, "C"), ("Trucks affected", 40, "C"), ("Impact (days)", 46, "C")]
    pdf.table_head(cols)
    for n, (cat, r) in enumerate(by.iterrows()):
        y = pdf.get_y()
        if n % 2:
            pdf.set_fill_color(*LIGHT)
            pdf.rect(MARGIN, y, CONTENT_W, 6.5, "F")
        pdf.set_text_color(*BLACK)
        x = MARGIN
        for (title, w, align), v in zip(cols, [t("dc_" + cat), r.notes, r.trucks, f"{r.days:g}"]):
            pdf.set_xy(x, y)
            pdf.set_font("Helvetica", "B" if title == "Cause" else "", 7.5)
            pdf.cell(w, 6.5, _txt(v), align=align)
            x += w
        pdf.set_y(y + 6.5)


def build_executive_pdf(p: Project) -> bytes:
    tr = p.trucks
    counts = tr.status.value_counts()
    n = len(tr)
    late = tr[(tr.delay_wd > 0) & (tr.progress < 1)]
    pdf = _Report(p.today)
    pdf.alias_nb_pages()
    pdf.add_page()

    pdf.kpis([
        ("Fleet progress", f"{tr.progress.mean() * 100:.0f}%", f"Average of {n} trucks", ORANGE),
        ("Completed", f"{counts.get('completed', 0)} / {n}", "Trucks", STATUS_RGB["completed"]),
        ("In execution", str(counts.get("in_progress", 0) + counts.get("overdue", 0)), "In progress + overdue", ORANGE),
        ("Upcoming", str(counts.get("upcoming", 0)), f"Within {p.settings.get('lookahead_days', 14)} days",
         STATUS_RGB["upcoming"]),
        ("Behind plan", str(len(late)), "Trucks delayed", STATUS_RGB["overdue"]),
        ("Actual MH", f"{tr.actual_mh.sum():,.0f}", "Recorded man-hours", BLACK),
    ])

    pdf.section("Executive summary")
    pdf.set_font("Helvetica", "", 8.5)
    pdf.set_text_color(*BLACK)
    for line in _summary_text(p):
        pdf.set_x(MARGIN)
        pdf.set_fill_color(*ORANGE)
        pdf.rect(MARGIN + 1, pdf.get_y() + 1.6, 1.4, 1.4, "F")
        pdf.set_x(MARGIN + 5)
        pdf.multi_cell(CONTENT_W - 5, 4.6, _txt(line), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(0.6)

    pdf.section("Status by truck")
    _truck_table(pdf, p)

    # La flota original y las máquinas en operación (agregadas en la app) van en cronogramas separados
    fleet, operating = p.group_trucks("fleet"), p.group_trucks("operating")
    if fleet:
        pdf.section("Gantt truck modification (original plan vs. forecast)", need=6.2 * len(fleet) + 25)
        _timeline(pdf, p, fleet)
    if operating:
        pdf.section("Gantt operating machine (original plan vs. forecast)", need=6.2 * len(operating) + 25)
        _timeline(pdf, p, operating)

    pdf.section("Activity summary - all trucks", need=7 * len(_plan_activities(p)) + 20)
    _activity_summary(pdf, p)

    pdf.section("Delays reported by supervisors")
    _delays(pdf, p)

    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(*GREY)
    pdf.cell(CONTENT_W, 4, _txt(f"Generated {_fd(p.today)} ({p.settings.get('timezone', 'UTC')}) from the HCMZ tracking app."),
             new_x="LMARGIN", new_y="NEXT")
    return bytes(pdf.output())
