"""Piezas de interfaz compartidas por las vistas de supervisor y administrador."""

from __future__ import annotations

import html
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

import pandas as pd
import streamlit as st

from core import config
from core.auth import USERS_PATH, User, check_password, dump_users, hash_password, stamp
from core.project import Project
from storage.base import StorageError, Store

T = Callable[..., str]


@dataclass
class Ctx:
    store: Store
    project: Project
    user: User
    users: dict[str, User]
    lang: str
    t: T


# ─── Formatos ─────────────────────────────────────────────────────────────
def fmt_date(d: date | None) -> str:
    return d.strftime("%d-%b-%Y") if isinstance(d, date) else "—"


def fmt_pct(p: float) -> str:
    return f"{p * 100:.0f}%"


def fmt_ts(ts: str, tz: str) -> str:
    """Fecha-hora UTC guardada → hora local del proyecto."""
    try:
        return pd.Timestamp(ts).tz_convert(tz).strftime("%d-%b-%Y %H:%M")
    except Exception:
        return ts[:16].replace("T", " ")


def act_name(t: T, key: str) -> str:
    return config.activity(key).name or t(f"act_{key}")


def esc(text: object) -> str:
    return html.escape(str(text))


# ─── Bloques visuales ─────────────────────────────────────────────────────
def section(title: str) -> None:
    st.markdown(f'<div class="section-title">{esc(title)}</div>', unsafe_allow_html=True)


def note(text: str) -> None:
    st.markdown(f'<div class="lc-note">{text}</div>', unsafe_allow_html=True)


def pill_html(t: T, status: str) -> str:
    color = config.STATUS_COLORS.get(status, "#888")
    return f'<span class="pill" style="background:{color}">{esc(t("st_" + status))}</span>'


def kpi_cards(items: list[tuple[str, str, str, str]]) -> None:
    """items: (etiqueta, valor, subtítulo, color: ''|'red'|'green'|'blue')."""
    cards = "".join(
        f'<div class="kpi-card {c}"><div class="kpi-label">{esc(l)}</div>'
        f'<div class="kpi-value">{esc(v)}</div><div class="kpi-sub">{esc(s)}</div></div>'
        for l, v, s, c in items
    )
    st.markdown(f'<div class="kpi-grid">{cards}</div>', unsafe_allow_html=True)


def truck_badge(ctx: Ctx, truck: str) -> None:
    t, p = ctx.t, ctx.project
    tr = p.truck_row(truck)
    window = f"{fmt_date(tr.start)} → {fmt_date(tr.end)}"
    limit = int(p.settings.get("max_working_days", 5))
    parts = [
        f'<div class="truck-badge-dt">{esc(truck.replace("RD", "RD "))}</div>',
        f'<div><div class="truck-badge-label">{esc(t("status"))}</div><div>{pill_html(t, tr.status)}</div></div>',
        f'<div><div class="truck-badge-label">{esc(t("progress"))}</div><div class="truck-badge-val">{fmt_pct(tr.progress)}</div></div>',
        f'<div><div class="truck-badge-label">{esc(t("forecast"))}</div><div class="truck-badge-val">{esc(window)}</div></div>',
        f'<div><div class="truck-badge-label">{esc(t("own_work_days"))}</div>'
        f'<div class="truck-badge-val">{tr.work_days} / {limit}{" ⚠" if tr.over_limit else ""}</div></div>',
        f'<div><div class="truck-badge-label">{esc(t("delay_wd"))}</div><div class="truck-badge-val">{tr.delay_wd:+d}</div></div>',
    ]
    sep = '<div class="truck-badge-sep"></div>'
    st.markdown(f'<div class="truck-badge">{sep.join(parts)}</div>', unsafe_allow_html=True)


def truck_label(ctx: Ctx, truck: str) -> str:
    tr = ctx.project.truck_row(truck)
    return f"{truck} · {ctx.t('st_' + tr.status)} · {fmt_pct(tr.progress)}"


# ─── Guardado con manejo de errores ───────────────────────────────────────
def safe_write(ctx: Ctx, fn: Callable[[], object], success: str) -> bool:
    try:
        with st.spinner(ctx.t("saving")):
            fn()
    except StorageError as exc:
        st.error(f"{ctx.t('save_failed')} {exc}", icon=":material/error:")
        return False
    st.session_state["flash"] = success
    return True


def show_flash() -> None:
    msg = st.session_state.pop("flash", None)
    if msg:
        st.toast(msg, icon=":material/check_circle:")


# ─── Cambio de contraseña propia ──────────────────────────────────────────
def password_form(ctx: Ctx, key: str) -> None:
    """Cada usuario solo puede cambiar su propia contraseña."""
    t, user = ctx.t, ctx.user
    with st.form(key, clear_on_submit=True):
        old = st.text_input(t("current_password"), type="password")
        new = st.text_input(t("new_password"), type="password", help=t("password_help"))
        new2 = st.text_input(t("confirm_password"), type="password")
        if st.form_submit_button(t("save"), icon=":material/key:"):
            if not check_password(old, user.hash):
                st.error(t("err_current_password"))
            elif len(new) < 8:
                st.error(t("err_password_short"))
            elif new != new2:
                st.error(t("err_password_match"))
            else:
                updated = dict(ctx.users)
                updated[user.username] = stamp(User(**{**vars(user), "hash": hash_password(new)}))
                try:
                    ctx.store.write(USERS_PATH, dump_users(updated), f"[app] cambio de contraseña · {user.username}")
                    st.success(t("password_changed"))
                except StorageError as exc:
                    st.error(f"{t('save_failed')} {exc}")
