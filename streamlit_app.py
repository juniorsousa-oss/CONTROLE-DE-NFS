from __future__ import annotations

import base64
import io
import json
import re
import uuid
import zipfile
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from PIL import Image

import db
from nf_processor import (
    build_final_name,
    digits_only,
    process_nf_pdf,
    supplier_dataframe,
    valid_cnpj,
)

ROOT = Path(__file__).parent
SUPPLIERS_FILE = ROOT / "data" / "fornecedores.csv"
LOGO_FILE = ROOT / "config" / "logo_setta.svg"
TZ = ZoneInfo("America/Sao_Paulo")

DEFAULT_FAVICON_B64 = """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"""

st.set_page_config(
    page_title="Controle de NFs | Setta",
    page_icon=Image.open(io.BytesIO(base64.b64decode(DEFAULT_FAVICON_B64))),
    layout="wide",
    initial_sidebar_state="expanded",
)

DEFAULT = {
    "title": "CONTROLE DE NOTAS FISCAIS",
    "subtitle": "Processamento • Pré-notas • Prioridade MRP • Fornecedores • Dashboard",
    "sidebar_title": "CONTROLE DE NFs",
    "sidebar_subtitle": "Automação do fluxo fiscal",
    "intro": "Envie os PDFs, valide as correspondências encontradas e somente depois gere os arquivos com o padrão definitivo.",
    "button_color": "#111111",
    "footer": "SETTA | Controle de Notas Fiscais",
    "naturezas": "MP,MC",
    "favicon_data": "",
    "favicon_mime": "image/png",
}


def now_local() -> datetime:
    return datetime.now(TZ)


def load_default_logo():
    if not LOGO_FILE.exists():
        return "", "image/svg+xml"
    return base64.b64encode(LOGO_FILE.read_bytes()).decode(), "image/svg+xml"


def local_suppliers() -> pd.DataFrame:
    try:
        base = pd.read_csv(SUPPLIERS_FILE, dtype=str).fillna("")
    except Exception:
        base = pd.DataFrame()
    return supplier_dataframe(base)


def init():
    if "cfg" not in st.session_state:
        logo_data, logo_mime = load_default_logo()
        st.session_state.cfg = {**DEFAULT, "logo_data": logo_data, "logo_mime": logo_mime}
    if "suppliers" not in st.session_state:
        st.session_state.suppliers = local_suppliers()
    defaults = {
        "analysis": pd.DataFrame(),
        "pdfs": {},
        "zip_outputs": {},
        "history": [],
        "pre_notes": pd.DataFrame(),
        "priority_nf_numbers": set(),
        "db_synced": False,
        "operator": "",
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)

    if db.configured() and not st.session_state.db_synced:
        try:
            remote_cfg = db.load_config()
            if remote_cfg:
                st.session_state.cfg = {**st.session_state.cfg, **remote_cfg}
            remote_suppliers = db.load_suppliers()
            if remote_suppliers:
                st.session_state.suppliers = supplier_dataframe(pd.DataFrame(remote_suppliers))
            remote_pre_notes = db.load_pre_notes()
            if remote_pre_notes:
                st.session_state.pre_notes = pd.DataFrame(remote_pre_notes)
            st.session_state.db_synced = True
        except Exception as exc:
            st.session_state.db_sync_error = str(exc)


init()
cfg = st.session_state.cfg


def browser_icon():
    """Converte o favicon salvo na configuração em imagem aceita pelo Streamlit."""
    data = str(cfg.get("favicon_data") or "").strip() or DEFAULT_FAVICON_B64
    if not data:
        return "📄"
    try:
        raw = base64.b64decode(data)
        image = Image.open(io.BytesIO(raw))
        image.load()
        return image
    except Exception:
        return "📄"


# Streamlit 1.49+ permite atualizar a configuração da página ao longo do script.
# Assim, o favicon salvo no Supabase passa a valer após salvar/recarregar o app.
st.set_page_config(
    page_title="Controle de NFs | Setta",
    page_icon=browser_icon(),
    layout="wide",
    initial_sidebar_state="expanded",
)

color = str(cfg.get("button_color") or "#111111").upper()
if not re.fullmatch(r"#[0-9A-F]{6}", color):
    color = "#111111"


def logo_html() -> str:
    data = cfg.get("logo_data", "")
    mime = cfg.get("logo_mime", "image/svg+xml")
    return f'<img src="data:{mime};base64,{data}" alt="Logo">' if data else '<b class="fallback">SETTA</b>'


st.markdown(
    """
<style>
:root{--p:__COLOR__}
[data-testid="stAppViewContainer"]{background:#f4f7fb!important}
[data-testid="stHeader"]{background:rgba(255,255,255,.96)!important}
.block-container{max-width:1780px!important;padding-top:3.2rem!important;padding-left:2.7rem!important;padding-right:2.7rem!important;padding-bottom:3rem!important;width:100%!important}
section[data-testid="stSidebar"]{background:#fff!important;border-right:1px solid #e8ebf0!important}
section[data-testid="stSidebar"] .block-container{padding-top:1.6rem!important;padding-left:1rem!important;padding-right:1rem!important}
.brand,.info,.intro,.setta-logo-card,.kpi-card,.panel{background:#fff;border:1px solid #e5e8ee;border-radius:14px}
.brand{padding:.9rem 1rem;margin:0 0 1.05rem;background:#f8fafc}.brand b{font-size:.92rem;color:#111827;font-weight:800}.brand small{color:#6b7280;font-size:.75rem}
.label{margin:.25rem 0 .45rem;color:#374151;font-size:.76rem;font-weight:800;text-transform:uppercase;letter-spacing:.055em}
.logo-preview{width:100%;min-height:82px;display:flex;justify-content:center;align-items:center;margin:.65rem 0 .5rem;padding:.65rem .8rem;background:#fff;border:1px dashed #d1d5db;border-radius:10px;box-sizing:border-box;overflow:hidden}
.logo-preview img{display:block;width:auto;height:auto;max-width:140px;max-height:62px;object-fit:contain}
.info{padding:.75rem .85rem;background:#f8fafc;color:#6b7280;font-size:.76rem;line-height:1.55}
section[data-testid="stSidebar"] div[role="radiogroup"]{display:flex;flex-direction:column;gap:.58rem}
section[data-testid="stSidebar"] div[role="radiogroup"] label{position:relative;width:100%;min-height:48px;display:flex!important;align-items:center!important;padding:.66rem .8rem .66rem 1rem!important;margin:0!important;border:1px solid #e2e8f0!important;border-radius:12px;background:#fff!important;box-shadow:0 2px 8px rgba(15,23,42,.035)!important;cursor:pointer;box-sizing:border-box;transition:.12s ease}
section[data-testid="stSidebar"] div[role="radiogroup"] label>div:first-child{display:none!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label p{margin:0!important;color:#334155!important;font-size:.86rem!important;line-height:1.2!important;font-weight:700!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label:hover{transform:translateY(-1px);border-color:#cbd5e1!important;background:#fbfdff!important;box-shadow:0 5px 14px rgba(15,23,42,.07)!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked){background:#111827!important;border-color:#111827!important;box-shadow:0 5px 14px rgba(17,24,39,.14)!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked)::before{content:"";position:absolute;left:.42rem;top:50%;width:4px;height:20px;border-radius:999px;background:#ef4444;transform:translateY(-50%)}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p{color:#fff!important}
section[data-testid="stSidebar"][aria-expanded="false"]{width:0!important;min-width:0!important;max-width:0!important;flex-basis:0!important}
.setta-logo-card{width:100%;min-height:128px;display:flex;align-items:center;justify-content:center;background:#fff;border:1px solid #e5e8ee;border-radius:16px;box-shadow:0 4px 14px rgba(24,39,75,.08);box-sizing:border-box;margin:0 0 2.55rem;padding:1.1rem 2rem}
.setta-logo-card img{display:block;width:auto;height:auto;max-width:205px;max-height:86px;object-fit:contain}.fallback{font-size:2rem;letter-spacing:.08em}
.app-title{margin:0!important;padding:0!important;font-size:2.55rem!important;line-height:1.08!important;font-weight:800!important;letter-spacing:-.04em!important;color:#050505!important}
.app-brand-line{display:flex;align-items:center;gap:.45rem;margin-top:.06rem}.app-brand-bar{display:inline-block;width:4px;height:.98em;background:#0b0b0b;border-radius:1px;flex:0 0 4px}
.app-sub{margin-top:.72rem!important;margin-bottom:2rem!important;color:#4f5661!important;font-size:.94rem!important;line-height:1.45!important}
.section-title{margin:0 0 1rem!important;color:#0f172a!important;font-size:1.28rem!important;font-weight:800!important;letter-spacing:-.02em}
.intro{padding:.9rem 1rem;color:#555c66;margin-bottom:1rem;box-shadow:0 3px 12px rgba(15,23,42,.035)}
.kpi-card{position:relative;min-height:116px;padding:16px 18px 15px;border:1px solid #e2e8f0;border-radius:14px;background:#fff;box-shadow:0 4px 16px rgba(15,23,42,.055);overflow:hidden;transition:transform .12s ease,box-shadow .12s ease}
.kpi-card::before{content:"";position:absolute;left:0;top:0;bottom:0;width:5px;background:var(--accent)}.kpi-card.selected{outline:2px solid var(--accent);outline-offset:1px}
.kpi-header{display:flex;align-items:center;gap:8px;margin-bottom:11px}.kpi-dot{width:9px;height:9px;border-radius:999px;background:var(--accent);box-shadow:0 0 0 4px var(--accent-soft);flex:0 0 auto}
.kpi-label{color:#475569;font-size:.83rem;font-weight:700;line-height:1.15}.kpi-value{color:#0f172a;font-size:2rem;font-weight:800;line-height:1;letter-spacing:-.035em}.kpi-delta{margin-top:8px;color:#64748b;font-size:.76rem}
[data-testid="stDataFrame"]{border:1px solid #e2e8f0;border-radius:12px;overflow:hidden;box-shadow:0 3px 12px rgba(15,23,42,.04)}
[data-testid="stAlert"]{border-radius:12px!important;box-shadow:0 3px 12px rgba(15,23,42,.035)}
button[kind="primary"],button[data-testid="stBaseButton-primary"]{background:var(--p)!important;border-color:var(--p)!important;color:#fff!important}.footer{text-align:center;color:#9298a1;font-size:.72rem;padding-top:1.2rem}
@media (max-width:900px){.block-container{padding-top:2rem!important;padding-left:1rem!important;padding-right:1rem!important;padding-bottom:2rem!important}.setta-logo-card{min-height:105px;margin-bottom:1.8rem;padding:.9rem 1rem}.setta-logo-card img{max-width:170px;max-height:72px}.app-title{font-size:2rem!important;line-height:1.12!important}.app-sub{font-size:.9rem!important;margin-bottom:1.6rem!important}.section-title{font-size:1.14rem!important}div[data-testid="stHorizontalBlock"]{flex-wrap:wrap!important}div[data-testid="stHorizontalBlock"]>div[data-testid="stColumn"]{min-width:100%!important;width:100%!important;flex:1 1 100%!important}.kpi-card{min-height:112px;margin-bottom:.12rem}}
</style>
""".replace("__COLOR__", color),
    unsafe_allow_html=True,
)


def parse_natures() -> list[str]:
    raw = str(st.session_state.cfg.get("naturezas") or "MP,MC")
    values = [re.sub(r"\s+", " ", x.strip().upper()) for x in re.split(r"[,;|\n]", raw) if x.strip()]
    return list(dict.fromkeys(values)) or ["MP", "MC"]


def recalc(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    names, stats, issues = [], [], []
    for _, row in out.iterrows():
        due = row.get("vencimento")
        if isinstance(due, (pd.Timestamp, datetime)):
            due = due.date()
        elif isinstance(due, str) and due.strip():
            parsed = pd.to_datetime(due, errors="coerce", dayfirst=True)
            due = None if pd.isna(parsed) else parsed.date()
        num = str(row.get("numero_nf") or "").strip()
        supplier = str(row.get("fornecedor_padrao") or "").strip()
        nature = str(row.get("natureza") or "").strip().upper()
        missing = []
        if not due:
            missing.append("vencimento")
        if not digits_only(num):
            missing.append("número NF")
        if not supplier:
            missing.append("fornecedor")
        if not nature:
            missing.append("natureza")
        names.append(build_final_name(due, num, supplier))
        current = str(row.get("status") or "REVISAR")
        stats.append("REVISAR" if any(x in missing for x in ["vencimento", "número NF", "fornecedor"]) else (current if current in {"APROVADO", "REVISAR"} else "REVISAR"))
        issues.append("Campos pendentes: " + ", ".join(missing) if missing else "")
    out["nome_sugerido"] = names
    out["status"] = stats
    out["validacao"] = issues
    return out


def metrics(df: pd.DataFrame):
    values = [
        ("Documentos", len(df), "PDFs analisados"),
        ("Aprovados", int(df.status.eq("APROVADO").sum()), "Correspondências"),
        ("Revisar", int((df.status.eq("REVISAR") | df.validacao.ne("")).sum()), "Conferir"),
        ("Prioridade MRP", int(df.get("prioridade_mrp", pd.Series(False, index=df.index)).fillna(False).astype(bool).sum()), "ZIP separado"),
    ]
    for col, (title, number, desc) in zip(st.columns(4), values):
        col.markdown(f'<div class="metric"><small>{title}</small><strong>{number}</strong><span>{desc}</span></div>', unsafe_allow_html=True)


def excel_bytes(frame: pd.DataFrame, sheet: str = "Dados") -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name=sheet[:31])
    return buffer.getvalue()


def read_uploaded_table(uploaded, sheet_name: str | None = None) -> tuple[pd.DataFrame, list[str]]:
    raw = uploaded.getvalue()
    name = uploaded.name.lower()
    if name.endswith(".csv"):
        for sep in [None, ";", ",", "\t"]:
            try:
                frame = pd.read_csv(io.BytesIO(raw), dtype=str, sep=sep, engine="python" if sep is None else "c").fillna("")
                if frame.shape[1] > 1 or sep == "\t":
                    return frame, []
            except Exception:
                pass
        raise ValueError("Não foi possível interpretar o CSV.")
    book = pd.ExcelFile(io.BytesIO(raw))
    sheets = book.sheet_names
    selected = sheet_name if sheet_name in sheets else sheets[0]
    return pd.read_excel(io.BytesIO(raw), sheet_name=selected, dtype=str).fillna(""), sheets


def guess_column(columns, tokens: list[str]) -> str | None:
    normalized = {c: re.sub(r"\W", "", str(c).upper()) for c in columns}
    for token in tokens:
        nt = re.sub(r"\W", "", token.upper())
        for col, value in normalized.items():
            if nt == value:
                return col
    for token in tokens:
        nt = re.sub(r"\W", "", token.upper())
        for col, value in normalized.items():
            if nt in value:
                return col
    return None


def normalized_nf(value) -> str:
    digits = digits_only(value)
    return digits.lstrip("0") or ("0" if digits else "")


def current_pre_note_map() -> dict[str, dict]:
    frame = st.session_state.pre_notes
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return {}
    result = {}
    for _, row in frame.iterrows():
        key = normalized_nf(row.get("numero_nf"))
        if key:
            result[key] = row.to_dict()
    return result


def apply_cross_checks(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    out = df.copy()
    priorities = set(st.session_state.priority_nf_numbers or set())
    pmap = current_pre_note_map()
    priority_flags, pre_status, pre_dates = [], [], []
    for _, row in out.iterrows():
        num = normalized_nf(row.get("numero_nf"))
        priority_flags.append(num in priorities)
        pre = pmap.get(num, {})
        pre_status.append(str(pre.get("status") or ""))
        pre_dates.append(pre.get("data_pre_nota") or None)
    out["prioridade_mrp"] = priority_flags
    out["pre_nota_status"] = pre_status
    out["pre_nota_em"] = pre_dates
    return out


def make_zip_outputs(df: pd.DataFrame):
    outputs: dict[str, bytes] = {}
    manifest: list[dict] = []
    batch = f"NF-{now_local():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:5].upper()}"
    operator = str(st.session_state.operator or "").strip()
    processed_at = now_local().isoformat(timespec="seconds")
    grouped = df.groupby([df["natureza"].fillna("").astype(str).str.upper().str.strip(), df["prioridade_mrp"].fillna(False).astype(bool)], dropna=False)
    for (nature, priority), group in grouped:
        if not nature:
            raise ValueError("Existe documento sem natureza interna.")
        buffer = io.BytesIO()
        used = set()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for _, row in group.iterrows():
                item = st.session_state.pdfs.get(str(row.file_id))
                final_name = str(row.nome_sugerido or "").strip()
                if not item:
                    raise ValueError(f"PDF original indisponível: {row.arquivo_original}")
                if not final_name or final_name in used:
                    raise ValueError(f"Nome final vazio ou duplicado: {final_name}")
                used.add(final_name)
                archive.writestr(final_name, item["bytes"])
                manifest.append(
                    {
                        "lote_id": batch,
                        "arquivo_original": str(row.arquivo_original),
                        "arquivo_final": final_name,
                        "tipo_documento": "NF-e",
                        "numero_nf": normalized_nf(row.numero_nf),
                        "serie": str(row.serie),
                        "chave_nfe": str(row.chave_nfe),
                        "cnpj_fornecedor": str(row.cnpj_fornecedor),
                        "fornecedor_padrao": str(row.fornecedor_padrao),
                        "vencimento": row.vencimento.isoformat() if isinstance(row.vencimento, date) else None,
                        "natureza": nature,
                        "prioridade_mrp": bool(priority),
                        "pre_nota_status": str(row.get("pre_nota_status") or ""),
                        "pre_nota_em": str(row.get("pre_nota_em") or "") or None,
                        "metodo_fornecedor": str(row.metodo_fornecedor),
                        "confianca": int(row.confianca),
                        "status": "PDF CRIADO",
                        "operador": operator or None,
                        "recebido_em": processed_at,
                        "pdf_criado_em": processed_at,
                        "processado_em": processed_at,
                    }
                )
        suffix = " - PRIORIDADE" if priority else ""
        zip_name = f"{now_local():%d-%m-%Y} - NOTAS FISCAIS - {nature}{suffix}.zip"
        outputs[zip_name] = buffer.getvalue()
    return outputs, manifest


def save_config_or_session(new_cfg: dict) -> tuple[bool, str]:
    st.session_state.cfg = new_cfg
    if not db.configured():
        return False, "Configuração aplicada somente nesta sessão: SUPABASE_ANON_KEY ainda não está configurada neste app."
    db.save_config(new_cfg)
    st.session_state.db_synced = True
    return True, "Configuração salva no Supabase."


with st.sidebar:
    st.markdown(f'<div class="brand"><b>{cfg["sidebar_title"]}</b><br><small>{cfg["sidebar_subtitle"]}</small></div>', unsafe_allow_html=True)
    st.markdown('<div class="label">Navegação</div>', unsafe_allow_html=True)
    page = st.radio(
        "Página",
        ["Dashboard", "Processamento de arquivos", "Configurações"],
        label_visibility="collapsed",
        format_func=str.upper,
    )
    st.divider()
    st.markdown('<div class="label">Operador</div>', unsafe_allow_html=True)
    try:
        _usuarios_ativos = db.list_users(active_only=True) if db.configured() else []
    except Exception:
        _usuarios_ativos = []
    _nomes_usuarios = [str(x.get("nome") or "").strip() for x in _usuarios_ativos if str(x.get("nome") or "").strip()]
    if _nomes_usuarios:
        _placeholder_operador = "Selecione o operador"
        _opcoes_operador = [_placeholder_operador] + _nomes_usuarios
        _operador_atual = str(st.session_state.operator or "").strip()
        _indice_operador = _opcoes_operador.index(_operador_atual) if _operador_atual in _opcoes_operador else 0
        _operador_escolhido = st.selectbox("Operador", _opcoes_operador, index=_indice_operador, label_visibility="collapsed", key="operador_select")
        st.session_state.operator = "" if _operador_escolhido == _placeholder_operador else _operador_escolhido
    else:
        st.session_state.operator = st.text_input("Nome do operador", value=st.session_state.operator, label_visibility="collapsed", placeholder="Cadastre um usuário em Configurações")
    st.divider()
    st.markdown('<div class="label">Identidade visual</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="logo-preview">{logo_html()}</div>', unsafe_allow_html=True)
    st.caption("Logo, títulos e cores ficam em Configurações.")
    st.divider()
    status = db.db_status()
    db_text = "Conectado" if status["configured"] else "Aguardando chave"
    st.markdown('<div class="label">Informações</div>', unsafe_allow_html=True)
    st.markdown(
        f'<div class="info"><b>Data operacional</b><br>{now_local():%d/%m/%Y}<br><br><b>Banco de dados</b><br>{db_text}<br><br><b>Fluxo</b><br>NF-e → conferência → ZIP<br><br><b>Versão</b><br>Protótipo 0.2</div>',
        unsafe_allow_html=True,
    )
    if st.session_state.get("db_sync_error"):
        st.warning("Falha na sincronização inicial do banco. Veja Configurações.")

st.markdown(f'<div class="setta-logo-card">{logo_html()}</div>', unsafe_allow_html=True)
st.markdown(
    f'<div class="app-title">{cfg["title"]}<div class="app-brand-line"><span class="app-brand-bar"></span><span>SETTA</span></div></div>',
    unsafe_allow_html=True,
)
st.markdown(f'<div class="app-sub">{cfg["subtitle"]}</div>', unsafe_allow_html=True)


if page == "Dashboard":
    st.markdown('<div class="section-title">Dashboard operacional</div>', unsafe_allow_html=True)
    if db.configured():
        try:
            records = pd.DataFrame(db.list_process_records())
        except Exception as exc:
            st.error(f"Não foi possível consultar o histórico: {exc}")
            records = pd.DataFrame(st.session_state.history)
    else:
        records = pd.DataFrame(st.session_state.history)

    if records.empty:
        records = pd.DataFrame(columns=[
            "id", "processado_em", "numero_nf", "fornecedor_padrao", "natureza",
            "vencimento", "pre_nota_status", "pre_nota_em", "prioridade_mrp",
            "status", "recebido_em", "pdf_criado_em", "enviado_em", "operador", "arquivo_final"
        ])

    for col in ["recebido_em", "pdf_criado_em", "enviado_em", "processado_em", "pre_nota_em"]:
        if col in records.columns:
            records[col] = pd.to_datetime(records[col], errors="coerce")

    received = int(records.get("recebido_em", pd.Series(pd.NaT, index=records.index)).notna().sum())
    pre_done = int(records.get("pre_nota_status", pd.Series("", index=records.index)).fillna("").astype(str).str.strip().ne("").sum())
    created = int(records.get("pdf_criado_em", pd.Series(pd.NaT, index=records.index)).notna().sum())
    sent = int(records.get("enviado_em", pd.Series(pd.NaT, index=records.index)).notna().sum())

    kpis = [
        ("Notas recebidas", received, "Documentos registrados", "#2563eb", "#dbeafe", True),
        ("Pré-notas realizadas", pre_done, "Vinculadas ao controle", "#d97706", "#ffedd5", False),
        ("PDFs criados", created, "Renomeados e compactados", "#0891b2", "#cffafe", False),
        ("Enviadas", sent, "Fluxo concluído", "#16a34a", "#dcfce7", False),
    ]
    for col, item in zip(st.columns(4), kpis):
        label, value, delta, accent, soft, selected = item
        selected_class = " selected" if selected else ""
        col.markdown(
            f'<div class="kpi-card{selected_class}" style="--accent:{accent};--accent-soft:{soft}">'
            f'<div class="kpi-header"><span class="kpi-dot"></span><span class="kpi-label">{label}</span></div>'
            f'<div class="kpi-value">{value}</div><div class="kpi-delta">{delta}</div></div>',
            unsafe_allow_html=True,
        )

    if not db.configured():
        st.caption("Persistência ainda não conectada neste deployment. Configure a chave do Supabase em Configurações.")

    st.markdown('<div class="section-title" style="margin-top:1.65rem!important;">Consulta de documentos</div>', unsafe_allow_html=True)
    if records.empty:
        st.caption("Os documentos processados passarão a aparecer nesta tabela.")
    else:
        f1, f2, f3, f4 = st.columns(4)
        ref_date = pd.to_datetime(records.get("processado_em"), errors="coerce").dt.date if "processado_em" in records.columns else pd.Series([date.today()] * len(records))
        min_d = min([d for d in ref_date.dropna().tolist()] or [date.today()])
        max_d = max([d for d in ref_date.dropna().tolist()] or [date.today()])
        start_date = f1.date_input("De", value=min_d)
        end_date = f2.date_input("Até", value=max_d)
        natures = sorted(records.get("natureza", pd.Series(dtype=str)).fillna("").astype(str).loc[lambda x: x.ne("")].unique().tolist())
        nature_filter = f3.multiselect("Natureza", natures, default=natures)
        suppliers = sorted(records.get("fornecedor_padrao", pd.Series(dtype=str)).fillna("").astype(str).loc[lambda x: x.ne("")].unique().tolist())
        supplier_filter = f4.multiselect("Fornecedor", suppliers)

        view = records.copy()
        mask_date = (ref_date >= start_date) & (ref_date <= end_date)
        view = view[mask_date]
        if nature_filter and "natureza" in view.columns:
            view = view[view["natureza"].isin(nature_filter)]
        if supplier_filter and "fornecedor_padrao" in view.columns:
            view = view[view["fornecedor_padrao"].isin(supplier_filter)]
        priority_only = st.checkbox("Exibir somente prioridade MRP")
        if priority_only and "prioridade_mrp" in view.columns:
            view = view[view["prioridade_mrp"].fillna(False).astype(bool)]

        display_cols = [x for x in [
            "id", "processado_em", "numero_nf", "fornecedor_padrao", "natureza",
            "vencimento", "pre_nota_status", "pre_nota_em", "prioridade_mrp",
            "status", "pdf_criado_em", "enviado_em", "operador", "arquivo_final"
        ] if x in view.columns]
        table = view[display_cols].copy().reset_index(drop=True)

        if "id" in table.columns:
            table.insert(0, "Selecionar", False)
            edited = st.data_editor(
                table,
                use_container_width=True,
                hide_index=True,
                disabled=[x for x in table.columns if x != "Selecionar"],
                key="dashboard_editor",
            )
            selected_ids = edited.loc[
                edited["Selecionar"].fillna(False).astype(bool), "id"
            ].astype(str).tolist()
            if st.button("Marcar selecionadas como enviadas", type="primary", disabled=not selected_ids):
                try:
                    result = db.mark_sent(selected_ids, st.session_state.operator)
                    st.success(f"{int(result.get('atualizados', 0))} registro(s) marcados como enviados.")
                    st.rerun()
                except Exception as exc:
                    st.error(f"Falha ao atualizar envio: {exc}")
        else:
            st.dataframe(table, use_container_width=True, hide_index=True)

        export_view = view.drop(columns=[x for x in ["id"] if x in view.columns])
        st.download_button(
            "Exportar consulta para Excel",
            excel_bytes(export_view, "Controle NFs"),
            file_name=f"controle_nfs_{now_local():%d%m%Y}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )



elif page == "Processamento de arquivos":
    st.markdown('<div class="section-title">Processamento de arquivos</div>', unsafe_allow_html=True)
    tab_nf, tab_cte = st.tabs(["NFs", "CTEs"])

    with tab_nf:
        st.markdown(f'<div class="intro">{cfg["intro"]}</div>', unsafe_allow_html=True)
        files = st.file_uploader("Selecione ou arraste os PDFs das notas fiscais", type=["pdf"], accept_multiple_files=True)
        a, b = st.columns(2)
        analyze = a.button("Analisar documentos", type="primary", use_container_width=True, disabled=not files)
        if b.button("Limpar lote atual", use_container_width=True):
            st.session_state.analysis = pd.DataFrame()
            st.session_state.pdfs = {}
            st.session_state.zip_outputs = {}
            st.rerun()
        if analyze:
            rows, store = [], {}
            progress = st.progress(0, text="Analisando documentos...")
            for i, file in enumerate(files, 1):
                raw = file.getvalue()
                result = process_nf_pdf(file.name, raw, st.session_state.suppliers, ocr_fallback=True)
                rows.append(result.to_dict())
                store[result.file_id] = {"name": file.name, "bytes": raw}
                progress.progress(i / len(files), text=f"{i}/{len(files)} — {file.name}")
            progress.empty()
            frame = pd.DataFrame(rows)
            if not frame.empty:
                frame["vencimento"] = pd.to_datetime(frame["vencimento"], errors="coerce").dt.date
                frame = apply_cross_checks(frame)
                frame = recalc(frame)
            st.session_state.analysis = frame
            st.session_state.pdfs = store
            st.session_state.zip_outputs = {}
            st.success(f"{len(frame)} documento(s) analisado(s). Confira antes da renomeação final.")

        frame = st.session_state.analysis.copy()
        if frame.empty:
            st.info("Nenhum lote analisado nesta sessão.")
        else:
            frame = apply_cross_checks(frame)
            frame = recalc(frame)
            st.markdown("### Conferência das correspondências")
            metrics(frame)
            st.caption("Vencimento, número da NF, fornecedor, natureza interna e status podem ser corrigidos antes da geração definitiva.")

            nature_options = parse_natures()
            with st.expander("Atribuição rápida de natureza", expanded=False):
                c1, c2 = st.columns([2, 1])
                bulk_nature = c1.selectbox("Natureza", nature_options, key="bulk_nature")
                only_blank = c2.checkbox("Somente vazias", value=True)
                if st.button("Aplicar natureza ao lote"):
                    target = frame["natureza"].fillna("").astype(str).str.strip().eq("") if only_blank else pd.Series(True, index=frame.index)
                    frame.loc[target, "natureza"] = bulk_nature
                    st.session_state.analysis = recalc(frame)
                    st.rerun()

            cols = ["arquivo_original", "vencimento", "numero_nf", "cnpj_fornecedor", "fornecedor_lido", "fornecedor_padrao", "natureza", "pre_nota_status", "prioridade_mrp", "metodo_fornecedor", "confianca", "leitura", "status", "nome_sugerido", "observacao"]
            editor = st.data_editor(
                frame[cols],
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                key="review",
                disabled=["arquivo_original", "cnpj_fornecedor", "fornecedor_lido", "pre_nota_status", "prioridade_mrp", "metodo_fornecedor", "confianca", "leitura", "nome_sugerido", "observacao"],
                column_config={
                    "arquivo_original": "Arquivo original",
                    "vencimento": st.column_config.DateColumn("Vencimento", format="DD/MM/YYYY"),
                    "numero_nf": "NF",
                    "cnpj_fornecedor": "CNPJ emitente",
                    "fornecedor_lido": "Fornecedor lido",
                    "fornecedor_padrao": "Fornecedor padrão",
                    "natureza": "Natureza interna",
                    "pre_nota_status": "Status pré-nota",
                    "prioridade_mrp": st.column_config.CheckboxColumn("Prioridade MRP"),
                    "metodo_fornecedor": "Correspondência",
                    "confianca": st.column_config.ProgressColumn("Confiança", min_value=0, max_value=100, format="%d%%"),
                    "leitura": "Leitura",
                    "status": st.column_config.SelectboxColumn("Status", options=["APROVADO", "REVISAR"], required=True),
                    "nome_sugerido": "Nome final",
                    "observacao": "Observação automática",
                },
            )
            merged = frame.copy()
            for col in ["vencimento", "numero_nf", "fornecedor_padrao", "natureza", "status"]:
                merged[col] = editor[col].values
            merged["natureza"] = merged["natureza"].fillna("").astype(str).str.strip().str.upper()
            merged = recalc(merged)
            st.session_state.analysis = merged
            st.markdown("#### Prévia da renomeação e separação")
            st.dataframe(merged[["arquivo_original", "nome_sugerido", "natureza", "prioridade_mrp", "status", "validacao"]], use_container_width=True, hide_index=True)

            invalid = merged[merged.nome_sugerido.fillna("").eq("") | merged.status.ne("APROVADO") | merged.validacao.fillna("").ne("")]
            duplicate = merged.nome_sugerido.fillna("").duplicated(keep=False) & merged.nome_sugerido.fillna("").ne("")
            if duplicate.any():
                st.error("Há nomes finais duplicados no lote.")
            elif not invalid.empty:
                st.warning(f"{len(invalid)} documento(s) ainda precisam de conferência.")
            else:
                normal = int((~merged["prioridade_mrp"].fillna(False).astype(bool)).sum())
                priority = int(merged["prioridade_mrp"].fillna(False).astype(bool).sum())
                st.success(f"Lote aprovado: {normal} documento(s) no fluxo normal e {priority} em prioridade MRP.")

            if st.button("Renomear, separar e gerar ZIPs", type="primary", use_container_width=True, disabled=(not invalid.empty or duplicate.any())):
                try:
                    outputs, manifest = make_zip_outputs(merged)
                    st.session_state.zip_outputs = outputs
                    st.session_state.history.extend(manifest)
                    if db.configured():
                        try:
                            db.save_process_records(manifest)
                            st.success("ZIPs criados e registros gravados no Supabase. Nenhum PDF foi salvo no banco.")
                        except Exception as exc:
                            st.warning(f"ZIPs criados, mas o histórico não pôde ser gravado no Supabase: {exc}")
                    else:
                        st.success("ZIPs criados. Histórico mantido nesta sessão; nenhum PDF foi salvo em banco.")
                except Exception as exc:
                    st.error(f"Falha ao gerar ZIP: {exc}")

            for zip_name, zip_bytes in st.session_state.zip_outputs.items():
                st.download_button(f"Baixar {zip_name}", zip_bytes, file_name=zip_name, mime="application/zip", type="primary", use_container_width=True, key=f"download_{zip_name}")


    with tab_cte:
        st.markdown("### CT-e")
        st.info("Módulo reservado. O fluxo seguirá a mesma arquitetura validada para NF-e, mas só será ativado após recebermos exemplos reais de CT-e e fecharmos as regras de extração e nomenclatura.")
        st.code("NUMERO CTE - TRANSPORTADORA - NUMERO NF - FORNECEDOR NF.pdf", language=None)



elif page == "Configurações":
    tab_personalizacao, tab_alimentacao, tab_usuarios = st.tabs(["Personalização", "Alimentação", "Usuários"])

    with tab_personalizacao:
        st.markdown("### Personalização do aplicativo")
        cur = st.session_state.cfg.copy()
        with st.form("cfg_form"):
            title = st.text_input("Título principal", cur["title"])
            sub = st.text_input("Subtítulo", cur["subtitle"])
            side = st.text_input("Título do menu lateral", cur["sidebar_title"])
            side_sub = st.text_input("Subtítulo do menu lateral", cur["sidebar_subtitle"])
            intro = st.text_area("Texto da tela principal", cur["intro"])
            footer = st.text_input("Rodapé", cur["footer"])
            natures = st.text_input("Naturezas internas (separadas por vírgula)", str(cur.get("naturezas") or "MP,MC"))
            button_color = st.color_picker("Cor principal dos botões", cur["button_color"])
            save = st.form_submit_button("Salvar textos e cor", type="primary", use_container_width=True)
        if save:
            cur.update(
                title=title or DEFAULT["title"],
                subtitle=sub or DEFAULT["subtitle"],
                sidebar_title=side or DEFAULT["sidebar_title"],
                sidebar_subtitle=side_sub or DEFAULT["sidebar_subtitle"],
                intro=intro or DEFAULT["intro"],
                footer=footer or DEFAULT["footer"],
                naturezas=natures or DEFAULT["naturezas"],
                button_color=button_color.upper(),
            )
            try:
                persisted, message = save_config_or_session(cur)
                (st.success if persisted else st.warning)(message)
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível salvar a configuração: {exc}")

        st.markdown("#### Logo da empresa")
        logo_upload = st.file_uploader("Selecionar nova logo", type=["png", "jpg", "jpeg", "svg"], key="logo")
        if logo_upload:
            raw = logo_upload.getvalue()
            if len(raw) > 1_500_000:
                st.error("Logo acima de 1,5 MB.")
            else:
                mime = logo_upload.type or ("image/svg+xml" if logo_upload.name.lower().endswith(".svg") else "image/png")
                encoded = base64.b64encode(raw).decode()
                st.markdown(f'<div class="logo-preview"><img src="data:{mime};base64,{encoded}"></div>', unsafe_allow_html=True)
                if st.button("Salvar nova logo", type="primary", use_container_width=True):
                    new_cfg = st.session_state.cfg.copy()
                    new_cfg.update(logo_data=encoded, logo_mime=mime)
                    try:
                        persisted, message = save_config_or_session(new_cfg)
                        (st.success if persisted else st.warning)(message)
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Não foi possível salvar a logo: {exc}")

        st.markdown("#### Ícone do navegador")
        st.caption("Personalize a pequena imagem exibida na aba do navegador (favicon). Recomendado: PNG ou ICO quadrado, de preferência 256×256 px.")

        current_favicon = str(st.session_state.cfg.get("favicon_data") or "").strip()
        if current_favicon:
            try:
                current_raw = base64.b64decode(current_favicon)
                current_image = Image.open(io.BytesIO(current_raw))
                st.image(current_image, caption="Favicon atual", width=72)
            except Exception:
                st.caption("O favicon atual não pôde ser pré-visualizado.")

        favicon_upload = st.file_uploader(
            "Selecionar ícone do navegador",
            type=["png", "jpg", "jpeg", "ico"],
            key="favicon_upload",
            help="Use uma imagem quadrada. O sistema ajusta o arquivo para uso como favicon.",
        )
        if favicon_upload:
            favicon_raw = favicon_upload.getvalue()
            if len(favicon_raw) > 750_000:
                st.error("O ícone deve ter no máximo 750 KB.")
            else:
                try:
                    favicon_image = Image.open(io.BytesIO(favicon_raw))
                    favicon_image.load()
                    if favicon_image.mode not in ("RGB", "RGBA"):
                        favicon_image = favicon_image.convert("RGBA")
                    preview = favicon_image.copy()
                    preview.thumbnail((128, 128))
                    st.image(preview, caption="Prévia do novo favicon", width=72)

                    # Normaliza para PNG para evitar incompatibilidades de navegador/Streamlit.
                    favicon_buffer = io.BytesIO()
                    favicon_image.save(favicon_buffer, format="PNG")
                    favicon_encoded = base64.b64encode(favicon_buffer.getvalue()).decode()

                    if st.button("Salvar ícone do navegador", type="primary", use_container_width=True):
                        new_cfg = st.session_state.cfg.copy()
                        new_cfg.update(favicon_data=favicon_encoded, favicon_mime="image/png")
                        try:
                            persisted, message = save_config_or_session(new_cfg)
                            (st.success if persisted else st.warning)(message)
                            st.rerun()
                        except Exception as exc:
                            st.error(f"Não foi possível salvar o ícone do navegador: {exc}")
                except Exception as exc:
                    st.error(f"Arquivo de ícone inválido: {exc}")

        if current_favicon and st.button("Remover ícone personalizado", use_container_width=True):
            new_cfg = st.session_state.cfg.copy()
            new_cfg.update(favicon_data="", favicon_mime="image/png")
            try:
                persisted, message = save_config_or_session(new_cfg)
                (st.success if persisted else st.warning)(message)
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível remover o ícone: {exc}")

        a, b = st.columns(2)
        if a.button("Restaurar padrão visual", use_container_width=True):
            logo_data, logo_mime = load_default_logo()
            restored = {**DEFAULT, "logo_data": logo_data, "logo_mime": logo_mime}
            try:
                persisted, message = save_config_or_session(restored)
                (st.success if persisted else st.warning)(message)
                st.rerun()
            except Exception as exc:
                st.error(f"Não foi possível restaurar o padrão: {exc}")
        b.download_button("Baixar configuração textual", json.dumps({k: v for k, v in st.session_state.cfg.items() if k != "logo_data"}, ensure_ascii=False, indent=2).encode(), file_name="config_controle_nfs.json", mime="application/json", use_container_width=True)

        st.markdown("#### Banco de dados")
        status = db.db_status()
        if status["configured"]:
            st.success("Supabase configurado para este aplicativo.")
            if st.button("Recarregar configurações e fornecedores do banco"):
                st.session_state.db_synced = False
                st.rerun()
        else:
            st.warning("Persistência ainda não está ativa neste deployment. Adicione SUPABASE_ANON_KEY nos Secrets do Streamlit. A URL do projeto já está configurada no código.")
        if st.session_state.get("db_sync_error"):
            st.error(st.session_state.db_sync_error)

    with tab_alimentacao:
        st.markdown("### Alimentação das bases")
        st.caption("Centralize aqui os arquivos que alimentam as validações e cruzamentos do aplicativo.")
        feed_pre, feed_mrp, feed_sup = st.tabs(["Validação Pré-notas", "Prioridade MRP", "Fornecedores"])

        with feed_pre:
            st.markdown("### Validação de pré-notas")
            st.write("Importe o relatório do sistema. A base é confrontada com as notas já processadas para mostrar o que ainda não passou pelo fluxo de documentos.")
            upload = st.file_uploader("Relatório de pré-notas (CSV ou XLSX)", type=["csv", "xlsx"], key="prenota_file")
            if upload:
                try:
                    temp, sheets = read_uploaded_table(upload)
                    if sheets:
                        selected_sheet = st.selectbox("Aba da planilha", sheets, key="prenota_sheet")
                        temp, _ = read_uploaded_table(upload, selected_sheet)
                    columns = list(temp.columns)
                    c1, c2, c3, c4 = st.columns(4)
                    guess_nf = guess_column(columns, ["DOCUMENTO", "NF", "NOTA", "NOTA FISCAL"])
                    guess_status = guess_column(columns, ["STATUS", "CLASSIFICACAO", "SITUACAO"])
                    guess_date = guess_column(columns, ["DIGITACAO", "DATA", "DATA PRE NOTA", "EMISSAO"])
                    nf_col = c1.selectbox("Coluna do número da NF", columns, index=columns.index(guess_nf) if guess_nf in columns else 0)
                    status_col = c2.selectbox("Coluna de status", columns, index=columns.index(guess_status) if guess_status in columns else 0)
                    date_col = c3.selectbox("Coluna da data da pré-nota", columns, index=columns.index(guess_date) if guess_date in columns else 0)
                    optional = ["(não usar)"] + columns
                    nature_guess = guess_column(columns, ["NATUREZA"])
                    nature_col = c4.selectbox("Natureza (opcional)", optional, index=optional.index(nature_guess) if nature_guess in optional else 0)
                    normalized = pd.DataFrame({
                        "numero_nf": temp[nf_col].map(normalized_nf),
                        "status": temp[status_col].fillna("").astype(str).str.strip(),
                        "data_pre_nota": pd.to_datetime(temp[date_col], errors="coerce", dayfirst=True).dt.date,
                        "natureza": temp[nature_col].fillna("").astype(str).str.strip().str.upper() if nature_col != "(não usar)" else "",
                    })
                    normalized = normalized[normalized["numero_nf"].ne("")].copy()
                    normalized = normalized.sort_values("data_pre_nota", na_position="last").drop_duplicates("numero_nf", keep="last")
                    statuses = sorted(normalized["status"].loc[lambda x: x.ne("")].unique().tolist())
                    considered = st.multiselect("Status considerados como pré-nota realizada", statuses, default=statuses)
                    preview = normalized[normalized["status"].isin(considered)] if considered else normalized.iloc[0:0]
                    st.dataframe(preview.head(300), use_container_width=True, hide_index=True)
                    if st.button("Substituir base de pré-notas", type="primary", use_container_width=True, disabled=preview.empty):
                        st.session_state.pre_notes = preview.reset_index(drop=True)
                        if db.configured():
                            rows = []
                            for _, row in preview.iterrows():
                                rows.append({
                                    "numero_nf": row["numero_nf"],
                                    "status": row["status"],
                                    "data_pre_nota": row["data_pre_nota"].isoformat() if isinstance(row["data_pre_nota"], date) else None,
                                    "natureza": row["natureza"],
                                })
                            result = db.replace_pre_notes(rows, upload.name)
                            st.success(f"Base de pré-notas atualizada: {int(result.get('registros', len(rows)))} registro(s).")
                        else:
                            st.success("Base de pré-notas aplicada nesta sessão.")
                        if not st.session_state.analysis.empty:
                            st.session_state.analysis = apply_cross_checks(st.session_state.analysis)
                        st.rerun()
                except Exception as exc:
                    st.error(f"Falha ao interpretar relatório: {exc}")

            pre = st.session_state.pre_notes.copy()
            if not pre.empty:
                if db.configured():
                    try:
                        processed = pd.DataFrame(db.list_process_records())
                    except Exception:
                        processed = pd.DataFrame(st.session_state.history)
                else:
                    processed = pd.DataFrame(st.session_state.history)
                processed_numbers = set(processed.get("numero_nf", pd.Series(dtype=str)).map(normalized_nf).tolist()) if not processed.empty else set()
                pre["validacao_documento"] = pre["numero_nf"].map(lambda n: "PROCESSADA" if normalized_nf(n) in processed_numbers else "PENDENTE DE DOCUMENTO")
                c1, c2, c3 = st.columns(3)
                c1.metric("Pré-notas na base", len(pre))
                c2.metric("Processadas", int(pre["validacao_documento"].eq("PROCESSADA").sum()))
                c3.metric("Pendentes", int(pre["validacao_documento"].eq("PENDENTE DE DOCUMENTO").sum()))
                st.dataframe(pre, use_container_width=True, hide_index=True)
                st.download_button("Exportar validação para Excel", excel_bytes(pre, "Validação Pré-notas"), file_name=f"validacao_pre_notas_{now_local():%d%m%Y}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)


        with feed_mrp:
            st.markdown("### Priorização por impacto no MRP")
            st.write("O cruzamento usa Código do Produto entre o relatório MRP e o relatório de itens das NFs. Depois, o número da NF vincula a prioridade aos PDFs processados.")
            mrp_file = st.file_uploader("Relatório MRP — produtos urgentes", type=["csv", "xlsx"], key="mrp_priority")
            nf_items_file = st.file_uploader("Relatório de NFs — produto + número da NF", type=["csv", "xlsx"], key="nf_items_priority")
            if mrp_file and nf_items_file:
                try:
                    mrp, mrp_sheets = read_uploaded_table(mrp_file)
                    nf_items, nf_sheets = read_uploaded_table(nf_items_file)
                    if mrp_sheets:
                        ms = st.selectbox("Aba MRP", mrp_sheets, key="mrp_priority_sheet")
                        mrp, _ = read_uploaded_table(mrp_file, ms)
                    if nf_sheets:
                        ns = st.selectbox("Aba relatório NFs", nf_sheets, key="nf_priority_sheet")
                        nf_items, _ = read_uploaded_table(nf_items_file, ns)
                    mcols, ncols = list(mrp.columns), list(nf_items.columns)
                    c1, c2, c3 = st.columns(3)
                    mg = guess_column(mcols, ["CODIGO", "COD MATERIAL", "PRODUTO"])
                    ng = guess_column(ncols, ["CODIGO", "COD MATERIAL", "PRODUTO"])
                    nfg = guess_column(ncols, ["DOCUMENTO", "NF", "NOTA"])
                    mrp_product = c1.selectbox("Código do produto no MRP", mcols, index=mcols.index(mg) if mg in mcols else 0)
                    nf_product = c2.selectbox("Código do produto no relatório de NFs", ncols, index=ncols.index(ng) if ng in ncols else 0)
                    nf_number = c3.selectbox("Número da NF no relatório de NFs", ncols, index=ncols.index(nfg) if nfg in ncols else 0)
                    urgent = set(mrp[mrp_product].fillna("").astype(str).str.strip().loc[lambda x: x.ne("")].tolist())
                    base = nf_items[[nf_product, nf_number]].copy()
                    base["produto"] = base[nf_product].fillna("").astype(str).str.strip()
                    base["numero_nf"] = base[nf_number].map(normalized_nf)
                    hits = base[base["produto"].isin(urgent) & base["numero_nf"].ne("")].copy()
                    summary = hits.groupby("numero_nf", as_index=False).agg(itens_urgentes=("produto", "nunique"))
                    st.dataframe(summary, use_container_width=True, hide_index=True)
                    st.caption(f"{len(urgent)} produto(s) urgentes no MRP → {len(summary)} NF(s) com ao menos um item urgente.")
                    if st.button("Aplicar prioridades ao processamento", type="primary", use_container_width=True):
                        st.session_state.priority_nf_numbers = set(summary["numero_nf"].astype(str).tolist())
                        if not st.session_state.analysis.empty:
                            st.session_state.analysis = apply_cross_checks(st.session_state.analysis)
                        st.success("Prioridades aplicadas. As NFs identificadas serão separadas em ZIP de PRIORIDADE dentro da respectiva natureza.")
                        st.rerun()
                except Exception as exc:
                    st.error(f"Falha no cruzamento dos relatórios: {exc}")
            if st.session_state.priority_nf_numbers:
                st.info(f"Há {len(st.session_state.priority_nf_numbers)} NF(s) marcadas como prioridade nesta sessão.")
                if st.button("Limpar prioridades atuais"):
                    st.session_state.priority_nf_numbers = set()
                    if not st.session_state.analysis.empty:
                        st.session_state.analysis = apply_cross_checks(st.session_state.analysis)
                    st.rerun()


        with feed_sup:
            st.markdown("### Base de fornecedores")
            st.write("A base é alimentada exclusivamente por planilha. Uma nova carga validada substitui integralmente a base anterior.")
            current = supplier_dataframe(st.session_state.suppliers)
            c1, c2, c3 = st.columns(3)
            c1.metric("Fornecedores atuais", len(current))
            c2.metric("CNPJs válidos", int(current["cnpj"].map(valid_cnpj).sum()) if not current.empty else 0)
            c3.metric("Origem", "Supabase" if db.configured() and st.session_state.db_synced else "Sessão/local")
            if not current.empty:
                st.dataframe(current.head(200), use_container_width=True, hide_index=True)
                st.download_button("Exportar base atual", excel_bytes(current, "Fornecedores"), file_name=f"fornecedores_nf_{now_local():%d%m%Y}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)

            upload = st.file_uploader("Nova base de fornecedores (CSV ou XLSX)", type=["csv", "xlsx"], key="supplier_import")
            if upload:
                try:
                    raw, sheets = read_uploaded_table(upload)
                    if sheets:
                        selected = st.selectbox("Aba da planilha", sheets, key="supplier_sheet")
                        raw, _ = read_uploaded_table(upload, selected)
                    columns = list(raw.columns)
                    g_cnpj = guess_column(columns, ["CNPJ", "CNPJCPF", "CGC"])
                    g_name = guess_column(columns, ["NOME", "RAZAO SOCIAL", "FORNECEDOR", "NOME FANTASIA"])
                    a, b, c = st.columns(3)
                    cnpj_col = a.selectbox("Coluna CNPJ", columns, index=columns.index(g_cnpj) if g_cnpj in columns else 0)
                    name_col = b.selectbox("Coluna nome padrão", columns, index=columns.index(g_name) if g_name in columns else 0)
                    optional = ["(não usar)"] + columns
                    alias_col = c.selectbox("Aliases (opcional)", optional)
                    incoming = pd.DataFrame({
                        "cnpj": raw[cnpj_col].map(digits_only),
                        "nome_padrao": raw[name_col].fillna("").astype(str).str.strip(),
                        "aliases": raw[alias_col].fillna("").astype(str).str.strip() if alias_col != "(não usar)" else "",
                        "ativo": True,
                    })
                    incoming["cnpj_valido"] = incoming["cnpj"].map(valid_cnpj)
                    incoming["nome_valido"] = incoming["nome_padrao"].ne("")
                    invalid = incoming[~incoming["cnpj_valido"] | ~incoming["nome_valido"]].copy()
                    valid = incoming[incoming["cnpj_valido"] & incoming["nome_valido"]].copy()
                    duplicate_rows = valid[valid["cnpj"].duplicated(keep=False)].copy()
                    conflict_cnpjs = []
                    for cnpj, group in duplicate_rows.groupby("cnpj"):
                        if group["nome_padrao"].str.upper().nunique() > 1:
                            conflict_cnpjs.append(cnpj)
                    clean = valid[~valid["cnpj"].isin(conflict_cnpjs)].drop_duplicates("cnpj", keep="last")
                    s1, s2, s3, s4 = st.columns(4)
                    s1.metric("Linhas", len(incoming))
                    s2.metric("Válidas", len(clean))
                    s3.metric("Duplicidades", int(len(valid) - valid["cnpj"].nunique()))
                    s4.metric("Inválidas/conflito", len(invalid) + len(conflict_cnpjs))
                    if not invalid.empty:
                        st.warning("Existem linhas com CNPJ inválido ou nome vazio. Corrija a planilha antes da substituição.")
                        st.dataframe(invalid.head(200), use_container_width=True, hide_index=True)
                    if conflict_cnpjs:
                        st.error("Existem CNPJs duplicados associados a nomes diferentes. A carga fica bloqueada até a correção.")
                        st.dataframe(duplicate_rows[duplicate_rows["cnpj"].isin(conflict_cnpjs)], use_container_width=True, hide_index=True)
                    st.markdown("#### Prévia da nova base")
                    st.dataframe(clean.head(300), use_container_width=True, hide_index=True)
                    can_replace = invalid.empty and not conflict_cnpjs and not clean.empty
                    if st.button("SUBSTITUIR BASE DE FORNECEDORES", type="primary", use_container_width=True, disabled=not can_replace):
                        final = supplier_dataframe(clean[["cnpj", "nome_padrao", "aliases", "ativo"]])
                        stats = {"total": len(incoming), "validos": len(final), "invalidos": len(invalid) + len(conflict_cnpjs), "duplicados": int(len(valid) - valid["cnpj"].nunique())}
                        if db.configured():
                            result = db.replace_suppliers(final.to_dict("records"), upload.name, stats)
                            st.session_state.suppliers = final
                            st.success(f"Base substituída com sucesso: {int(result.get('fornecedores', len(final)))} fornecedor(es).")
                        else:
                            st.session_state.suppliers = final
                            st.warning("Base substituída somente nesta sessão porque a chave do Supabase não está configurada.")
                        st.rerun()
                except Exception as exc:
                    st.error(f"Falha ao validar a planilha: {exc}")

            if db.configured():
                try:
                    imports = pd.DataFrame(db.list_supplier_imports())
                    if not imports.empty:
                        st.markdown("#### Últimas importações")
                        st.dataframe(imports, use_container_width=True, hide_index=True)
                except Exception:
                    pass



    with tab_usuarios:
        st.markdown("### Usuários")
        st.caption("Cadastre os usuários operacionais que poderão ser selecionados como responsáveis pelos processamentos do aplicativo.")

        with st.expander("+ NOVO USUÁRIO", expanded=False):
            with st.form("form_novo_usuario_nf", clear_on_submit=True):
                u1, u2 = st.columns(2)
                novo_nome = u1.text_input("Nome do usuário")
                novo_email = u2.text_input("E-mail (opcional)")
                criar_usuario = st.form_submit_button("CRIAR USUÁRIO", type="primary", use_container_width=True)

            if criar_usuario:
                if not str(novo_nome or "").strip():
                    st.error("Informe o nome do usuário.")
                elif novo_email and ("@" not in novo_email or "." not in novo_email.split("@")[-1]):
                    st.error("Informe um e-mail válido ou deixe o campo em branco.")
                else:
                    try:
                        db.create_user(novo_nome, novo_email)
                        st.success("Usuário criado com sucesso.")
                        st.rerun()
                    except Exception as exc:
                        mensagem = str(exc)
                        if "duplicate" in mensagem.lower() or "unique" in mensagem.lower():
                            st.error("Já existe um usuário com esse nome.")
                        else:
                            st.error(f"Não foi possível criar o usuário: {exc}")

        try:
            usuarios = db.list_users() if db.configured() else []
        except Exception as exc:
            usuarios = []
            st.error(f"Não foi possível carregar os usuários: {exc}")

        if not usuarios:
            st.info("Nenhum usuário cadastrado.")
        else:
            ativos = sum(1 for u in usuarios if bool(u.get("ativo")))
            c1, c2 = st.columns(2)
            c1.metric("Usuários cadastrados", len(usuarios))
            c2.metric("Usuários ativos", ativos)

            tabela_usuarios = pd.DataFrame(usuarios)
            colunas_usuario = [x for x in ["nome", "email", "ativo", "criado_em", "atualizado_em"] if x in tabela_usuarios.columns]
            st.dataframe(tabela_usuarios[colunas_usuario], use_container_width=True, hide_index=True)

            st.markdown("#### Editar usuário")
            mapa_usuarios = {str(u.get("nome") or u.get("email") or u.get("id")): u for u in usuarios}
            usuario_label = st.selectbox("Selecionar usuário", list(mapa_usuarios.keys()), key="usuario_edicao_select")
            usuario = mapa_usuarios[usuario_label]

            with st.form("form_editar_usuario_nf"):
                e1, e2 = st.columns(2)
                nome_editado = e1.text_input("Nome", value=str(usuario.get("nome") or ""))
                email_editado = e2.text_input("E-mail", value=str(usuario.get("email") or ""))
                ativo_editado = st.toggle("Usuário ativo", value=bool(usuario.get("ativo")), key="usuario_ativo_toggle")
                salvar_usuario = st.form_submit_button("SALVAR ALTERAÇÕES", type="primary", use_container_width=True)

            if salvar_usuario:
                if not nome_editado.strip():
                    st.error("O nome do usuário não pode ficar vazio.")
                else:
                    try:
                        db.update_user(str(usuario.get("id")), nome_editado, email_editado, ativo_editado)
                        st.success("Usuário atualizado.")
                        if st.session_state.operator == str(usuario.get("nome") or "") and not ativo_editado:
                            st.session_state.operator = ""
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Não foi possível atualizar o usuário: {exc}")

            with st.expander("Excluir usuário", expanded=False):
                st.warning("A exclusão remove o usuário da lista de operadores. Os registros históricos já gravados permanecem preservados.")
                confirmar_exclusao = st.checkbox("Confirmo a exclusão deste usuário", key="confirmar_exclusao_usuario")
                if st.button("EXCLUIR USUÁRIO", disabled=not confirmar_exclusao, use_container_width=True):
                    try:
                        db.delete_user(str(usuario.get("id")))
                        if st.session_state.operator == str(usuario.get("nome") or ""):
                            st.session_state.operator = ""
                        st.success("Usuário excluído.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Não foi possível excluir o usuário: {exc}")


st.markdown(f'<div class="footer">{cfg["footer"]}</div>', unsafe_allow_html=True)
