"""Estilo visual: identidad LANDCROS, igual que el dashboard de referencia
(negro #1A1A1A, naranja #FF6B00, tipografía Barlow)."""

from __future__ import annotations

import base64
from functools import lru_cache
from pathlib import Path

import streamlit as st

from core import config

_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Barlow+Condensed:wght@400;600;700;800&family=Barlow:wght@300;400;500;600&display=swap');
html,body,[class*="css"]{font-family:'Barlow',sans-serif;}
.block-container{padding-top:1rem!important;padding-left:2rem!important;padding-right:2rem!important;max-width:1400px;}
#MainMenu,footer{visibility:hidden;}
/* Barra superior de Streamlit (GitHub, Share, menú, Deploy): oculta. stToolbar
   NO se oculta: contiene el botón que vuelve a abrir la barra lateral. */
[data-testid="stToolbarActions"],[data-testid="stMainMenu"],[data-testid="stAppDeployButton"],
.stAppDeployButton,[data-testid="stDecoration"],[data-testid="stStatusWidget"]{display:none!important;}
header[data-testid="stHeader"],[data-testid="stToolbar"]{background:transparent!important;box-shadow:none!important;}

/* Botones para esconder / mostrar la barra lateral: siempre visibles */
[data-testid="stExpandSidebarButton"]{display:flex!important;visibility:visible!important;opacity:1!important;
  background:#1A1A1A!important;border:2px solid #FF6B00!important;border-radius:4px!important;}
[data-testid="stExpandSidebarButton"] span{color:#FF6B00!important;}
[data-testid="stSidebarCollapseButton"],[data-testid="stSidebarCollapseButton"] button{display:flex!important;
  visibility:visible!important;opacity:1!important;}
[data-testid="stSidebarCollapseButton"] button{border-color:#FF6B00!important;}
[data-testid="stSidebarCollapseButton"] span{color:#FF6B00!important;}

/* Barra lateral oscura */
[data-testid="stSidebar"]{background:#1A1A1A!important;border-right:3px solid #FF6B00;}
[data-testid="stSidebar"] p,[data-testid="stSidebar"] span,[data-testid="stSidebar"] label,
[data-testid="stSidebar"] div[data-testid="stMarkdownContainer"],[data-testid="stSidebar"] small{color:#FFFFFF!important;}
[data-testid="stSidebar"] label p{font-family:'Barlow Condensed',sans-serif;font-weight:600;font-size:.8rem;letter-spacing:.09em;text-transform:uppercase;color:#AAAAAA!important;}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p{color:#AAAAAA!important;}
[data-testid="stSidebar"] button{background:#262626!important;border:1px solid #444!important;}
[data-testid="stSidebar"] button p{color:#FFFFFF!important;}
[data-testid="stSidebar"] button:hover{border-color:#FF6B00!important;}
[data-testid="stSidebar"] button[aria-checked="true"],[data-testid="stSidebar"] button[aria-pressed="true"],
[data-testid="stSidebar"] button[kind*="Active"]{background:#FF6B00!important;border-color:#FF6B00!important;}
[data-testid="stSidebar"] input{color:#1A1A1A!important;background:#F7F7F7!important;}
[data-testid="stSidebar"] [data-testid="stExpander"] details{border-color:#444!important;}
[data-testid="stSidebar"] hr{border-top:1px solid #333;}
.sidebar-logo{display:flex;justify-content:center;padding:14px 10px 12px;border-bottom:1px solid #333;margin-bottom:12px;}
.sidebar-logo img{max-width:150px;}
.side-user{font-family:'Barlow Condensed',sans-serif;font-size:1.15rem;font-weight:700;color:#fff;}
.side-role{display:inline-block;font-family:'Barlow Condensed',sans-serif;font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;
  background:#FF6B00;color:#fff!important;padding:1px 8px;border-radius:2px;margin-top:2px;}

/* Pestañas */
[data-testid="stTabs"] [role="tablist"]{border-bottom:2px solid #FF6B00;gap:4px;flex-wrap:wrap;}
[data-testid="stTabs"] button[role="tab"]{font-family:'Barlow Condensed',sans-serif;font-weight:700;letter-spacing:.08em;text-transform:uppercase;color:#888;padding:8px 14px;}
[data-testid="stTabs"] button[role="tab"] p,[data-baseweb="tab"] p{font-family:'Barlow Condensed',sans-serif;font-weight:700;font-size:.95rem;letter-spacing:.06em;text-transform:uppercase;}
[data-testid="stTabs"] button[role="tab"][aria-selected="true"]{color:#FF6B00!important;}

/* Encabezado */
.lc-header{display:flex;align-items:center;justify-content:space-between;background:#1A1A1A;padding:16px 28px;border-bottom:4px solid #FF6B00;margin-bottom:20px;border-radius:0 0 4px 4px;gap:16px;}
.lc-header-title{font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:1.8rem;letter-spacing:.04em;color:#fff;line-height:1.1;}
.lc-header-subtitle{font-weight:300;font-size:.82rem;color:#AAAAAA;margin-top:3px;letter-spacing:.07em;text-transform:uppercase;}
.lc-header img{height:62px;}

/* Tarjetas KPI */
.kpi-grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:18px;}
.kpi-card{background:#F7F7F7;border-left:4px solid #FF6B00;padding:14px 16px 10px;border-radius:2px;}
.kpi-card.red{border-left-color:#C62828;} .kpi-card.green{border-left-color:#2E7D32;} .kpi-card.blue{border-left-color:#1565C0;}
.kpi-label{font-family:'Barlow Condensed',sans-serif;font-weight:600;font-size:.72rem;letter-spacing:.13em;text-transform:uppercase;color:#888;margin-bottom:4px;}
.kpi-value{font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:1.9rem;color:#1A1A1A;line-height:1;}
.kpi-sub{font-size:.75rem;color:#888;margin-top:4px;}

.section-title{font-family:'Barlow Condensed',sans-serif;font-weight:700;font-size:1.02rem;letter-spacing:.11em;text-transform:uppercase;color:#1A1A1A;
  border-bottom:2px solid #FF6B00;padding-bottom:5px;margin:8px 0 12px;}
.lc-note{font-size:.84rem;color:#555;background:#FFF4EC;border-left:3px solid #FF6B00;padding:8px 12px;margin-bottom:12px;border-radius:0 2px 2px 0;}

/* Insignia del camión */
.truck-badge{display:flex;flex-wrap:wrap;align-items:center;gap:22px;background:#1A1A1A;padding:12px 22px;border-radius:3px;margin-bottom:16px;}
.truck-badge-dt{font-family:'Barlow Condensed',sans-serif;font-weight:800;font-size:2.1rem;color:#FF6B00;letter-spacing:.05em;}
.truck-badge-label{font-family:'Barlow Condensed',sans-serif;font-weight:600;font-size:.7rem;letter-spacing:.12em;text-transform:uppercase;color:#888;}
.truck-badge-val{font-family:'Barlow Condensed',sans-serif;font-weight:700;font-size:1.12rem;color:#fff;}
.truck-badge-sep{width:1px;height:34px;background:#444;}

/* Estado */
.pill{display:inline-block;padding:2px 9px;border-radius:2px;color:#fff!important;font-family:'Barlow Condensed',sans-serif;
  font-weight:700;font-size:.76rem;letter-spacing:.08em;text-transform:uppercase;white-space:nowrap;}

/* Alertas */
.alert{border-left:4px solid #C62828;background:#FDECEA;padding:10px 14px;margin-bottom:8px;border-radius:0 2px 2px 0;font-size:.9rem;}
.alert.orange{border-left-color:#FF6B00;background:#FFF4EC;}
.alert.blue{border-left-color:#1565C0;background:#E8F0FB;}
.alert b{font-family:'Barlow Condensed',sans-serif;letter-spacing:.04em;}

.lc-footer{margin-top:28px;padding:12px 0;border-top:1px solid #EFEFEF;display:flex;justify-content:space-between;}
.lc-footer span{font-family:'Barlow Condensed',sans-serif;font-size:.78rem;color:#BBBBBB;letter-spacing:.07em;text-transform:uppercase;}

/* Inicio de sesión */
.login-box{max-width:420px;margin:0 auto;}
</style>
"""


def inject_css() -> None:
    st.markdown(_CSS, unsafe_allow_html=True)


@lru_cache(maxsize=4)
def image_b64(path: Path) -> str:
    try:
        return base64.b64encode(Path(path).read_bytes()).decode()
    except OSError:
        return ""


def sidebar_logo() -> None:
    b64 = image_b64(config.LOGO_PATH)
    html = f'<img src="data:image/webp;base64,{b64}" alt="LANDCROS"/>' if b64 else "<b>LANDCROS</b>"
    st.markdown(f'<div class="sidebar-logo">{html}</div>', unsafe_allow_html=True)


def header(title: str, subtitle: str) -> None:
    b64 = image_b64(config.TRUCK_IMAGE_PATH)
    img = f'<img src="data:image/webp;base64,{b64}" alt="EH5000"/>' if b64 else ""
    st.markdown(
        f'<div class="lc-header"><div><div class="lc-header-title">{title}</div>'
        f'<div class="lc-header-subtitle">{subtitle}</div></div>{img}</div>',
        unsafe_allow_html=True,
    )


def footer(left: str, right: str) -> None:
    st.markdown(f'<div class="lc-footer"><span>{left}</span><span>{right}</span></div>', unsafe_allow_html=True)
