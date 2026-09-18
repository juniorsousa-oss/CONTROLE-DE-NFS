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

st.set_page_config(
    page_title="Controle de NFs | Setta",
    page_icon="📄",
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
    st.session_state.operator = st.text_input("Nome do operador", value=st.session_state.operator, label_visibility="collapsed", placeholder="Informe o responsável")
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
    tab_personalizacao, tab_alimentacao = st.tabs(["Personalização", "Alimentação"])

    with tab_personalizacao:
        st.markdown("### Personalização do aplicativo")
        cur = st.session_state.cfg.copy()
        with st.form("cfg"):
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



st.markdown(f'<div class="footer">{cfg["footer"]}</div>', unsafe_allow_html=True)
