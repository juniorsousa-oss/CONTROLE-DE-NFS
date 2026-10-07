"""Shell visual SETTA canônico.

Extraído do Conversor MRP e compartilhável entre aplicativos Streamlit.
Este módulo deve controlar somente a moldura, header, sidebar e responsividade.
"""

DEFAULT_SETTA_UI_CONFIG = {
    "header": {
        "enabled": True,
        "min_height": 150,
        "background": "#FFFFFF",
        "border_color": "#E5E8EE",
        "border_radius": 18,
        "padding_y": 18,
        "padding_x": 24,
        "logo_max_width": 220,
        "logo_max_height": 90,
        "margin_bottom": 24,
    },
    "top_actions": {
        "show_more": False,
    },
    "theme": {
        "lock_light": True,
        "app_background": "#F4F7FB",
        "surface_background": "#FFFFFF",
        "text_color": "#111827",
    },
}


def _merge_config(base, override):
    result = {}
    override = override if isinstance(override, dict) else {}
    for key, value in base.items():
        custom = override.get(key)
        if isinstance(value, dict):
            result[key] = _merge_config(
                value,
                custom if isinstance(custom, dict) else {},
            )
        else:
            result[key] = value if custom is None else custom
    for key, value in override.items():
        if key not in result:
            result[key] = value
    return result


def build_ui_config(override=None):
    return _merge_config(DEFAULT_SETTA_UI_CONFIG, override or {})


def _int_cfg(value, default, minimum, maximum):
    try:
        return max(minimum, min(maximum, int(value)))
    except Exception:
        return default


def _css_color(value, default):
    text = str(value or "").strip()
    if len(text) in {4, 7, 9} and text.startswith("#"):
        return text
    return default


def render_shell(st, ui_config, sidebar_open):
    header = (ui_config or {}).get("header") or {}
    theme = (ui_config or {}).get("theme") or {}

    _header_height = _int_cfg(header.get("min_height"), 150, 90, 320)
    _header_radius = _int_cfg(header.get("border_radius"), 18, 0, 40)
    _header_padding_y = _int_cfg(header.get("padding_y"), 18, 0, 80)
    _header_padding_x = _int_cfg(header.get("padding_x"), 24, 0, 120)
    _logo_max_width = _int_cfg(header.get("logo_max_width"), 220, 80, 600)
    _logo_max_height = _int_cfg(header.get("logo_max_height"), 90, 40, 240)
    _header_margin_bottom = _int_cfg(header.get("margin_bottom"), 24, 0, 100)
    _header_background = _css_color(header.get("background"), "#FFFFFF")
    _header_border = _css_color(header.get("border_color"), "#E5E8EE")
    _app_background = _css_color(theme.get("app_background"), "#F4F7FB")
    _surface_background = _css_color(theme.get("surface_background"), "#FFFFFF")
    _text_color = _css_color(theme.get("text_color"), "#111827")

    if not sidebar_open:
        st.markdown(
            """
            <style>
            section[data-testid="stSidebar"]{display:none!important;}
            [data-testid="stSidebarCollapseButton"],
            [data-testid="stSidebarCollapsedControl"],
            button[data-testid="stSidebarCollapseButton"]{display:none!important;}
            </style>
            """,
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            """
            <style>
            [data-testid="stSidebarCollapseButton"],
            [data-testid="stSidebarCollapsedControl"],
            button[data-testid="stSidebarCollapseButton"]{display:none!important;}
            </style>
            """,
            unsafe_allow_html=True,
        )

    st.markdown(
        f"""<style>
/* SETTA UI — Layout padrão Streamlit */
html,body,#root{{
  min-height:100%!important;
  height:auto!important;
  max-height:none!important;
  overflow-y:auto!important;
  overflow-x:hidden!important;
}}
html,body{{background:#F4F7FB!important}}
body{{
  box-sizing:border-box!important;
  padding:0!important;
  margin:0!important;
  overflow-y:auto!important;
}}
.stApp,[data-testid="stApp"]{{
  position:relative!important;
  inset:auto!important;
  width:100%!important;
  height:auto!important;
  min-height:100vh!important;
  max-height:none!important;
  max-width:none!important;
  margin:0!important;
  border:0!important;
  border-radius:0!important;
  overflow:visible!important;
  background:#F8FAFD!important;
  box-shadow:none!important;
}}
[data-testid="stAppViewContainer"]{{
  position:relative!important;
  inset:auto!important;
  width:100%!important;
  height:auto!important;
  min-height:100vh!important;
  max-height:none!important;
  border-radius:0!important;
  overflow:visible!important;
  background:{_app_background}!important;
  color:{_text_color}!important;
}}
[data-testid="stMain"],.stMain,section.main{{
  position:relative!important;
  width:100%!important;
  max-width:none!important;
  height:auto!important;
  min-height:100vh!important;
  max-height:none!important;
  margin:0!important;
  overflow-x:hidden!important;
  overflow-y:visible!important;
}}
[data-testid="stMainBlockContainer"],[data-testid="stAppViewBlockContainer"]{{
  width:100%!important;
  max-width:none!important;
  height:auto!important;
  min-height:100vh!important;
  max-height:none!important;
  margin:0!important;
  overflow:visible!important;
  padding-top:3.2rem!important;
  padding-left:2.7rem!important;
  padding-right:2.7rem!important;
  padding-bottom:3rem!important;
  box-sizing:border-box!important;
}}
[data-testid="stHeader"],[data-testid="stToolbar"],[data-testid="stDecoration"],header[data-testid="stHeader"]{{
  display:none!important;
  visibility:hidden!important;
  height:0!important;
  min-height:0!important;
  max-height:0!important;
  margin:0!important;
  padding:0!important;
}}
#MainMenu{{display:none!important}}
.block-container{{
  max-width:none!important;
  width:100%!important;
  margin:0!important;
  padding-top:3.2rem!important;
  padding-left:2.7rem!important;
  padding-right:2.7rem!important;
  padding-bottom:3rem!important;
  box-sizing:border-box!important;
}}
.st-key-setta_top_controls{{
  position:absolute!important;
  top:18px!important;
  left:44px!important;
  z-index:120!important;
  width:82px!important;
  margin:0!important;
  padding:0!important;
}}
.st-key-setta_top_controls [data-testid="stVerticalBlock"]{{gap:0!important}}
.st-key-setta_drawer_toggle{{width:82px!important;margin:0!important;padding:0!important}}
.st-key-setta_drawer_toggle button{{
  width:82px!important;
  min-height:42px!important;
  height:42px!important;
  border-radius:10px!important;
  padding:0!important;
  background:rgba(255,255,255,.96)!important;
  box-shadow:0 2px 8px rgba(15,23,42,.06)!important;
}}
section[data-testid="stSidebar"]{{
  background:{_surface_background}!important;
  border-right:1px solid #e8ebf0!important;
  border-radius:0!important;
  width:260px!important;
  min-width:260px!important;
  max-width:260px!important;
  flex:0 0 260px!important;
  flex-basis:260px!important;
  overflow:hidden!important;
}}
section[data-testid="stSidebar"]>div{{
  width:260px!important;
  min-width:260px!important;
  max-width:260px!important;
  box-sizing:border-box!important;
}}
section[data-testid="stSidebar"] .block-container{{
  width:260px!important;
  min-width:260px!important;
  max-width:260px!important;
  box-sizing:border-box!important;
  padding-top:26px!important;
  padding-left:16px!important;
  padding-right:16px!important;
}}
section[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{{gap:0!important;row-gap:0!important}}
.sidebar-brand{{
  width:100%!important;
  background:#f8fafc!important;
  border:1px solid #e5e8ee!important;
  border-radius:12px!important;
  padding:14px 16px!important;
  margin:0 0 20px 0!important;
}}
.sidebar-brand-title{{
  margin:0!important;padding:0!important;font-size:15px!important;font-weight:800!important;
  line-height:18px!important;color:#111827!important;letter-spacing:-.01em!important;
}}
.sidebar-brand-sub{{
  margin:3px 0 0 0!important;padding:0!important;font-size:12px!important;font-weight:400!important;
  line-height:16px!important;color:#6b7280!important;
}}
.sidebar-section-label{{
  display:block!important;margin:0 0 8px 0!important;padding:0!important;color:#374151!important;
  font-size:12px!important;line-height:15px!important;font-weight:800!important;
  text-transform:uppercase!important;letter-spacing:.055em!important;
}}
section[data-testid="stSidebar"] div[data-testid="stElementContainer"]:has(.sidebar-section-label){{margin:0!important;padding:0!important}}
section[data-testid="stSidebar"] [class*="st-key-setta_nav_"]{{margin:0 0 2px 0!important;padding:0!important}}
section[data-testid="stSidebar"] .st-key-setta_nav_0{{margin-top:8px!important}}
section[data-testid="stSidebar"] [class*="st-key-setta_nav_"] button{{
  position:relative!important;width:100%!important;min-height:42px!important;height:42px!important;max-height:42px!important;
  margin:0!important;padding:0 12px 0 24px!important;border-radius:10px!important;
  justify-content:flex-start!important;text-align:left!important;box-shadow:none!important;
}}
section[data-testid="stSidebar"] [class*="st-key-setta_nav_"] button > div{{width:100%!important;justify-content:flex-start!important;text-align:left!important}}
section[data-testid="stSidebar"] [class*="st-key-setta_nav_"] button p{{
  width:100%!important;margin:0!important;padding:0!important;text-align:left!important;font-size:13px!important;line-height:16px!important;
}}
section[data-testid="stSidebar"] [class*="st-key-setta_nav_"] button[data-testid="stBaseButton-secondary"]{{
  background:transparent!important;border:1px solid transparent!important;color:#374151!important;font-weight:500!important;
}}
section[data-testid="stSidebar"] [class*="st-key-setta_nav_"] button[data-testid="stBaseButton-secondary"]:hover{{
  background:#f8fafc!important;border-color:#e5e7eb!important;color:#111827!important;
}}
section[data-testid="stSidebar"] [class*="st-key-setta_nav_"] button[data-testid="stBaseButton-primary"]{{
  background:#111827!important;border:1px solid #111827!important;color:#fff!important;font-weight:700!important;
  box-shadow:0 5px 14px rgba(17,24,39,.14)!important;
}}
section[data-testid="stSidebar"] [class*="st-key-setta_nav_"] button[data-testid="stBaseButton-primary"]::before{{
  content:""!important;position:absolute!important;left:7px!important;top:50%!important;width:4px!important;height:20px!important;
  border-radius:999px!important;background:#ef4444!important;transform:translateY(-50%)!important;
}}
.sidebar-divider{{display:block!important;width:100%!important;height:1px!important;min-height:1px!important;background:#d1d5db!important;margin:18px 0 20px 0!important;padding:0!important}}
.sidebar-status-card{{width:100%!important;background:#f8fafc!important;border:1px solid #e5e8ee!important;border-radius:10px!important;padding:12px 14px!important;margin:0!important;color:#6b7280!important}}
.sidebar-status-name{{margin:0!important;padding:0!important;font-size:11px!important;line-height:14px!important;font-weight:800!important;color:#64748b!important;text-transform:uppercase!important;letter-spacing:.025em!important}}
.sidebar-status-value{{margin:4px 0 0 0!important;padding:0!important;font-size:13px!important;line-height:16px!important;font-weight:900!important;text-transform:uppercase!important}}
.sidebar-status-value.status-ok{{color:#16a34a!important}}
.sidebar-status-value.status-warning{{color:#f59e0b!important}}
.sidebar-status-value.status-error{{color:#ef4444!important}}
.sidebar-status-meta{{margin:6px 0 0 0!important;padding:0!important;color:#6b7280!important;font-size:11px!important;line-height:15px!important;text-transform:uppercase!important}}
[data-testid="stAppViewContainer"] > .main,[data-testid="stAppViewContainer"] .main,[data-testid="stMain"],.stMain{{width:100%!important;max-width:100%!important;margin-left:0!important;margin-right:0!important}}
[data-testid="stAppViewContainer"] .main .block-container,[data-testid="stMain"] .block-container,.stMain .block-container{{width:100%!important;max-width:100%!important;margin-left:0!important;margin-right:0!important}}

.setta-logo-card{{
  width:100%!important;
  min-height:{_header_height}px!important;
  display:flex!important;
  align-items:center!important;
  justify-content:center!important;
  background:{_header_background}!important;
  border:1px solid {_header_border}!important;
  border-radius:{_header_radius}px!important;
  box-shadow:0 4px 14px rgba(24,39,75,.08)!important;
  box-sizing:border-box!important;
  margin:0 0 {_header_margin_bottom}px 0!important;
  padding:{_header_padding_y}px {_header_padding_x}px!important;
}}
.setta-logo-card img{{display:block!important;width:auto!important;height:auto!important;max-width:{_logo_max_width}px!important;max-height:{_logo_max_height}px!important;object-fit:contain!important}}
.app-title{{margin:0!important;padding:0!important;font-size:2.55rem!important;line-height:1.08!important;font-weight:800!important;letter-spacing:-.04em!important;color:#050505!important;text-transform:uppercase!important}}
.app-sub{{margin-top:.72rem!important;margin-bottom:1.65rem!important;color:#4f5661!important;font-size:.94rem!important;line-height:1.35!important;text-transform:uppercase!important}}

/* Componentes internos explícitos — sem monkey patch global */
.kpi-card{{
  position:relative!important;min-height:116px!important;padding:16px 18px 15px 18px!important;
  border:1px solid #e2e8f0!important;border-radius:14px!important;background:#fff!important;
  box-shadow:0 4px 16px rgba(15,23,42,.055)!important;overflow:hidden!important;
  transition:transform .12s ease,box-shadow .12s ease!important;
}}
.kpi-card:hover{{transform:translateY(-1px)!important;box-shadow:0 8px 22px rgba(15,23,42,.085)!important}}
.kpi-card::before{{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;background:var(--accent)}}
.kpi-header{{display:flex;align-items:center;gap:8px;margin-bottom:11px}}
.kpi-dot{{width:9px;height:9px;border-radius:999px;background:var(--accent);box-shadow:0 0 0 4px var(--accent-soft);flex:0 0 auto}}
.kpi-label{{color:#475569;font-size:.83rem;font-weight:700;line-height:1.15}}
.kpi-value{{color:#0f172a;font-size:2rem;font-weight:800;line-height:1;letter-spacing:-.035em}}
.kpi-delta{{margin-top:8px;color:#64748b;font-size:.76rem}}
div[class*="st-key-dash_kpi_"]{{margin-top:-116px!important;height:116px!important;position:relative!important;z-index:20!important}}
div[class*="st-key-dash_kpi_"] button{{
  width:100%!important;height:116px!important;min-height:116px!important;opacity:0!important;cursor:pointer!important;
  border:0!important;background:transparent!important;box-shadow:none!important;padding:0!important;
}}

/* Conteúdo interno do Gestão de Entregas — preservado */
.critical{{border:1px solid #ef4444!important;border-left:6px solid #ef4444!important;border-radius:8px!important;padding:12px 14px!important;background:rgba(239,68,68,.06)!important;margin:8px 0 14px!important}}
.project-card{{border:1px solid #d1d5db!important;border-radius:10px!important;padding:14px 16px!important;margin-top:12px!important;background:rgba(249,250,251,.72)!important}}
.project-title{{font-size:1.08rem!important;font-weight:750!important;margin-bottom:.25rem!important}}
.project-meta{{color:#6b7280!important;font-size:.88rem!important;margin-bottom:.6rem!important}}
.section-band{{margin:0 0 .95rem!important;padding:.82rem 1rem!important;background:#fff!important;border:1px solid #e5e8ee!important;border-left:5px solid #111827!important;border-radius:12px!important;box-shadow:0 3px 12px rgba(15,23,42,.035)!important}}
.section-band-kicker{{font-size:.66rem!important;font-weight:900!important;letter-spacing:.085em!important;text-transform:uppercase!important;color:#ef4444!important;margin-bottom:.18rem!important}}
.section-band-title{{font-size:1.08rem!important;font-weight:900!important;color:#111827!important;letter-spacing:-.015em!important;line-height:1.2!important;text-transform:uppercase!important}}
.section-band-note{{margin-top:.22rem!important;color:#667085!important;font-size:.75rem!important;line-height:1.35!important}}
.topic-divider{{height:1px!important;background:#cbd5e1!important;margin:1.55rem 0 1.05rem!important;width:100%!important}}
[data-testid="stMetric"]{{background:#fff!important;border:1px solid #e2e8f0!important;border-radius:14px!important;box-shadow:0 4px 16px rgba(15,23,42,.055)!important;padding:1rem 1rem .9rem!important;min-height:112px!important;position:relative!important;overflow:hidden!important}}
[data-testid="stMetric"]::before{{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;background:#111827}}
[data-testid="stMetricLabel"] p{{text-transform:uppercase!important;font-size:.72rem!important;font-weight:900!important;letter-spacing:.025em!important;color:#475569!important}}
[data-testid="stMetricValue"]{{font-weight:800!important;color:#0f172a!important}}
[data-testid="stDataFrame"],[data-testid="stDataEditor"]{{border:1px solid #dfe3e8!important;border-radius:14px!important;overflow:hidden!important;box-shadow:0 4px 16px rgba(15,23,42,.045)!important;background:#fff!important}}
[data-testid="stVerticalBlockBorderWrapper"]{{border-color:#e5e8ee!important;border-radius:14px!important;background:#fff!important;box-shadow:0 3px 12px rgba(15,23,42,.035)!important}}
[data-testid="stTabs"] button{{font-weight:800!important;text-transform:uppercase!important;letter-spacing:.015em!important}}
div[data-testid="stMarkdownContainer"] h1,div[data-testid="stMarkdownContainer"] h2,div[data-testid="stMarkdownContainer"] h3,div[data-testid="stMarkdownContainer"] h4{{text-transform:uppercase}}
[data-testid="stAlert"]{{border-radius:12px!important;box-shadow:0 3px 12px rgba(15,23,42,.035)!important}}
button[kind="primary"],button[data-testid="stBaseButton-primary"]{{background:#111827!important;border-color:#111827!important;color:#fff!important}}

@media(max-width:900px){{
  html,body,#root{{height:auto!important;min-height:100%!important;max-height:none!important;overflow-y:auto!important}}
  body{{padding:0!important;background:#F5F8FC!important;overflow-y:auto!important}}
  .stApp,[data-testid="stApp"]{{width:100%!important;height:auto!important;min-height:100vh!important;max-height:none!important;max-width:none!important;border:0!important;border-radius:0!important;box-shadow:none!important;overflow:visible!important}}
  [data-testid="stAppViewContainer"],[data-testid="stMain"],.stMain{{height:auto!important;min-height:100vh!important;max-height:none!important;overflow:visible!important;border-radius:0!important}}
  .block-container{{padding-top:2rem!important;padding-left:1rem!important;padding-right:1rem!important;padding-bottom:2rem!important}}
  .setta-logo-card{{min-height:105px!important;margin-bottom:1.8rem!important;padding:.9rem 1rem!important}}
  .setta-logo-card img{{max-width:170px!important;max-height:72px!important}}
  .app-title{{font-size:2rem!important;line-height:1.12!important}}
  .app-sub{{font-size:.86rem!important;margin-bottom:1.35rem!important}}
}}
</style>""",
        unsafe_allow_html=True,
    )


    # Estado aberto precisa vencer tanto o aria-expanded do Streamlit quanto
    # qualquer style tag residual da execução anterior em que o drawer estava fechado.
    if sidebar_open:
        st.markdown(
            """
            <style>
            section[data-testid="stSidebar"],
            section[data-testid="stSidebar"][aria-expanded="false"]{
              display:flex!important;
              visibility:visible!important;
              opacity:1!important;
              width:260px!important;
              min-width:260px!important;
              max-width:260px!important;
              flex:0 0 260px!important;
              flex-basis:260px!important;
              transform:none!important;
              overflow:hidden!important;
            }
            section[data-testid="stSidebar"]>div,
            section[data-testid="stSidebar"][aria-expanded="false"]>div{
              display:block!important;
              visibility:visible!important;
              opacity:1!important;
              width:260px!important;
              min-width:260px!important;
              max-width:260px!important;
              transform:none!important;
            }
            section[data-testid="stSidebar"] [data-testid="stSidebarContent"],
            section[data-testid="stSidebar"] [data-testid="stVerticalBlock"],
            section[data-testid="stSidebar"] div[data-testid="stElementContainer"]{
              visibility:visible!important;
              opacity:1!important;
            }
            </style>
            """,
            unsafe_allow_html=True,
        )
