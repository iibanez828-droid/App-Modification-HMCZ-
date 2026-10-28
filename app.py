"""HMCZ Truck Modification — seguimiento de la modificación de 12 camiones EH5000.

Ejecutar con:  streamlit run app.py
"""

from __future__ import annotations

import time

import streamlit as st

from core import config
from core.auth import User, authenticate, load_users, master_account
from core.events import initialize, is_initialized
from core.i18n import translator
from core.project import build_project
from storage import StorageError, local_dir, make_store
from ui import admin, supervisor
from ui.common import Ctx, note, password_form, show_flash
from ui.theme import footer, header, inject_css, sidebar_logo

st.set_page_config(page_title="HMCZ Truck Modification", page_icon=str(config.LOGO_PATH), layout="wide",
                   initial_sidebar_state="expanded")
inject_css()
ss = st.session_state
ss.setdefault("lang", "en")
t = translator(ss.lang)


# ─── Datos ────────────────────────────────────────────────────────────────
def _secrets() -> dict:
    try:
        return {k: dict(v) if hasattr(v, "keys") else v for k, v in st.secrets.items()}
    except Exception:  # sin archivo de secretos → modo local
        return {}


@st.cache_resource(show_spinner=False)
def get_store(_secrets_dict: dict, local_path: str):
    # local_path forma parte de la clave del caché: si cambia la carpeta local, se crea otro almacenamiento
    return make_store(_secrets_dict)


@st.cache_data(show_spinner=False, max_entries=4)
def load_state(_store, version: int, bucket: int):
    """Lee los datos (una descarga) y calcula el estado del proyecto.
    Se renueva al guardar (version) o cada 30 s (bucket) para ver lo que
    guardan los demás usuarios."""
    snapshot = _store.snapshot()
    project = build_project(snapshot) if is_initialized(snapshot) else None
    return snapshot, project


store = get_store(_secrets(), str(local_dir()))
try:
    with st.spinner(t("loading")):
        snapshot, project = load_state(store, store.version, int(time.time() // 30))
except StorageError as exc:
    header(config.PROJECT_NAME, config.FLEET)
    st.error(f"{t('load_failed')} {exc}", icon=":material/cloud_off:")
    if st.button(t("retry"), icon=":material/refresh:"):
        load_state.clear()
        st.rerun()
    st.stop()

if project is not None:  # actividades creadas en la app (el caché puede omitir build_project)
    config.set_custom_activities(project.custom_acts)

users = load_users(snapshot)
master = master_account(_secrets())


def language_picker(where) -> None:
    choice = where.segmented_control(t("language"), list(config.LANGUAGES), default=ss.lang,
                                     format_func=lambda k: config.LANGUAGES[k], key="lang_pick")
    if choice and choice != ss.lang:
        ss.lang = choice
        st.rerun()


# ─── Inicio de sesión ─────────────────────────────────────────────────────
def login_page() -> None:
    header(config.PROJECT_NAME, t("login_subtitle"))
    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        language_picker(st)
        with st.form("login"):
            username = st.text_input(t("username"))
            pw = st.text_input(t("password"), type="password")
            if st.form_submit_button(t("login"), type="primary", width="stretch", icon=":material/login:"):
                user = authenticate(users, username, pw, master)
                if user:
                    ss.user = user
                    ss.pop("login_fail", None)
                    st.rerun()
                ss.login_fail = ss.get("login_fail", 0) + 1
                time.sleep(min(ss.login_fail, 5))  # frena intentos repetidos
                st.error(t("login_failed"))
        st.caption(t("login_help"))


if "user" not in ss:
    login_page()
    st.stop()

# La sesión se valida contra el archivo de usuarios en cada carga: si el dueño
# desactiva a alguien o le cambia el rol, el cambio aplica en el siguiente clic.
user: User = ss.user
if user.is_master:
    if not master or master.username != user.username:
        ss.clear()
        st.rerun()
    user = ss.user = master
elif user.username in users and users[user.username].active and not (master and user.username == master.username):
    user = ss.user = users[user.username]
else:
    ss.clear()
    st.rerun()
ctx = Ctx(store=store, project=project, user=user, users=users, lang=ss.lang, t=t)

# ─── Barra lateral ────────────────────────────────────────────────────────
with st.sidebar:
    sidebar_logo()
    st.markdown(f'<div class="side-user">{user.name}</div><span class="side-role">{t("role_" + user.role)}</span>',
                unsafe_allow_html=True)
    st.write("")
    language_picker(st)
    # Cada rol ve solo su vista; únicamente el maestro puede alternar entre ambas
    view = "admin" if user.is_admin else "supervisor"
    if user.is_master:
        view = st.segmented_control(t("view"), ["admin", "supervisor"], default="admin", key="view_pick",
                                    format_func=lambda v: t("view_" + v)) or "admin"
    st.divider()
    if st.button(t("refresh"), icon=":material/refresh:", width="stretch", help=t("refresh_help")):
        load_state.clear()
        st.rerun()
    # Los administradores cambian su contraseña en la pestaña de configuración;
    # la del maestro está en los secretos
    if user.role == "supervisor":
        with st.expander(t("change_password"), icon=":material/key:"):
            password_form(ctx, "chg_pw")
    if st.button(t("logout"), icon=":material/logout:", width="stretch"):
        lang = ss.lang
        ss.clear()
        ss.lang = lang
        st.rerun()
    st.caption(f"{t('data_source')}: {store.label}")
    if project is not None:
        st.caption(f"{t('today')}: {project.today:%d-%b-%Y} ({project.settings.get('timezone')})")

# ─── Contenido ────────────────────────────────────────────────────────────
show_flash()
subtitle = t("subtitle_admin") if view == "admin" else t("subtitle_supervisor")
header(config.PROJECT_NAME, f"{config.FLEET} · {subtitle}")
if project is None:
    if user.is_admin or user.is_master:
        note(t("init_help"))
        if st.button(t("init_button"), type="primary", icon=":material/rocket_launch:"):
            try:
                with st.spinner(t("saving")):
                    initialize(store, user.username)
            except StorageError as exc:
                st.error(f"{t('save_failed')} {exc}")
            else:
                st.rerun()
    else:
        note(t("not_initialized"))
    st.stop()

if view == "admin":
    admin.render(ctx)
else:
    supervisor.render(ctx)

footer(f"LANDCROS · {config.PROJECT_NAME}", f"{len(project.trucks)} trucks · {config.FLEET}")
