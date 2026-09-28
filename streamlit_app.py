from __future__ import annotations

import base64
import io
import json
import re
import uuid
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from rapidfuzz import fuzz
from PIL import Image
from openpyxl import load_workbook

import db
from nf_processor import (
    build_final_name,
    digits_only,
    extract_pdf_text,
    inspect_nf_pdf_identity,
    process_nf_pdf,
    supplier_dataframe,
    valid_cnpj,
    normalize_text,
    match_supplier,
)

ROOT = Path(__file__).parent
SUPPLIERS_FILE = ROOT / "data" / "fornecedores.csv"
LOGO_FILE = ROOT / "config" / "logo_setta.svg"
TZ = ZoneInfo("America/Sao_Paulo")

# Persistência operacional reativada para homologação integrada.
SAVE_NF_HISTORY = True
ENABLE_PENDING_REPORT = True

FAVICON_FILE = ROOT / "config" / "favicon_setta.b64"


# O motor DANFE é carregado somente quando a função XML/PDF é usada.
# Assim uma falha isolada no renderizador não derruba o app inteiro no startup.
def extract_danfe_metadata(raw_xml: bytes):
    from danfe_generator import extract_danfe_metadata as _impl
    return _impl(raw_xml)


def extract_nfe_processing_data(raw_xml: bytes):
    from danfe_generator import extract_nfe_processing_data as _impl
    return _impl(raw_xml)


def generate_danfe_pdf(raw_xml: bytes) -> bytes:
    from danfe_generator import generate_danfe_pdf as _impl
    return _impl(raw_xml)


def apply_operational_stamp(
    pdf_bytes: bytes,
    data_chegada,
    cr,
    desc_cr,
    natureza,
    recebido_por,
) -> bytes:
    from danfe_generator import apply_operational_stamp as _impl
    return _impl(
        pdf_bytes,
        data_chegada=data_chegada,
        cr=cr,
        desc_cr=desc_cr,
        natureza=natureza,
        recebido_por=recebido_por,
    )


def danfe_file_name(meta) -> str:
    from danfe_generator import danfe_file_name as _impl
    return _impl(meta)


def extract_cte_metadata(raw_xml: bytes):
    from cte_generator import extract_cte_metadata as _impl
    return _impl(raw_xml)


def generate_dacte_pdf(raw_xml: bytes) -> bytes:
    from cte_generator import generate_dacte_pdf as _impl
    return _impl(raw_xml)


def cte_output_name(meta, linked_nf_numbers, supplier_name: str = "") -> str:
    from cte_generator import cte_output_name as _impl
    return _impl(meta, linked_nf_numbers, supplier_name)


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
    "control_docs_label": "CONTROLE DE DOC.",
    "intro": "Envie os PDFs, valide as correspondências encontradas e somente depois gere os arquivos com o padrão definitivo.",
    "button_color": "#111111",
    "footer": "SETTA | Controle de Notas Fiscais",
    "favicon_data": "",
    "favicon_mime": "image/png",
}


def now_local() -> datetime:
    return datetime.now(TZ)


def dataframe_records_for_db(frame: pd.DataFrame) -> list[dict]:
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return []
    return json.loads(
        frame.to_json(
            orient="records",
            date_format="iso",
            force_ascii=False,
        )
    )


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
        "prefilter_rejected": [],
        "prefilter_resolved": [],
        "prefilter_files": {},
        "prefilter_stats": {},
        "cte_links": [],
        "cte_rejected": [],
        "cte_outputs": {},
        "cte_ignored_count": 0,
        "document_link_stats": {},
        "document_upload_cache": [],
        "document_reprocess_needed": False,
        "base_analysis_ready": False,
        "base_analysis_at": None,
        "base_analysis_missing_mrp": pd.DataFrame(),
        "danfe_outputs": {},
        "danfe_results": [],
        "danfe_errors": [],
        "history": [],
        "current_test_manifest": [],
        "pre_notes": pd.DataFrame(),
        "priority_nf_numbers": set(),
        "priority_nf_keys": set(),
        "priority_nf_doc_keys": set(),
        "priority_date_nf_keys": set(),
        "mrp_priority_summary": pd.DataFrame(),
        "mrp_impact_detail": pd.DataFrame(),
        "mrp_import_preview_detail": pd.DataFrame(),
        "mrp_import_preview_summary": pd.DataFrame(),
        "mrp_priority_stats": {},
        "mrp_priority_files": (),
        "mrp_ignored_records": [],
        "pre_import_preview": pd.DataFrame(),
        "pre_import_invalid_count": 0,
        "pre_import_name": "",
        "supplier_import_preview": pd.DataFrame(),
        "supplier_import_stats": {},
        "supplier_import_conflicts": pd.DataFrame(),
        "supplier_import_name": "",
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
            if SAVE_NF_HISTORY:
                remote_pre_notes = db.load_pre_notes()
                if remote_pre_notes:
                    pre_frame = pd.DataFrame(remote_pre_notes)
                    if "data_pre_nota" in pre_frame.columns:
                        pre_frame["data_pre_nota"] = pd.to_datetime(
                            pre_frame["data_pre_nota"],
                            errors="coerce",
                        ).dt.date
                    st.session_state.pre_notes = pre_frame

                remote_mrp = db.load_mrp_load()
                if remote_mrp:
                    detail = pd.DataFrame(remote_mrp.get("detalhe") or [])
                    summary = pd.DataFrame(remote_mrp.get("resumo") or [])
                    for frame in (detail, summary):
                        for column in ("data_pre_nota", "data_cm"):
                            if column in frame.columns:
                                frame[column] = pd.to_datetime(
                                    frame[column],
                                    errors="coerce",
                                ).dt.date

                    st.session_state.mrp_impact_detail = detail
                    st.session_state.mrp_priority_summary = summary
                    st.session_state.mrp_priority_files = tuple(
                        remote_mrp.get("arquivos") or []
                    )
                    st.session_state.mrp_priority_stats = (
                        remote_mrp.get("stats") or {}
                    )

                    if not summary.empty:
                        high = summary[
                            summary["prioridade"]
                            .fillna("")
                            .astype(str)
                            .str.upper()
                            .eq("ALTA")
                        ]
                        st.session_state.priority_date_nf_keys = set(
                            high.get(
                                "data_nf",
                                pd.Series(dtype=str),
                            ).dropna().astype(str).tolist()
                        )
                        st.session_state.priority_nf_numbers = set(
                            high.get(
                                "numero_nf",
                                pd.Series(dtype=str),
                            ).dropna().astype(str).tolist()
                        )

                st.session_state.history = db.list_process_records()
            st.session_state.db_synced = True
        except Exception as exc:
            st.session_state.db_sync_error = str(exc)


init()

# Reinício controlado da homologação: notas enviadas, lote de arquivos,
# resultados intermediários e cargas MRP são zerados uma única vez após
# este deploy. Mantém a base de Pré-notas, fornecedores, usuários e
# configurações, que não fazem parte do reset solicitado.
_reset_marker = "_nf_mrp_operational_reset_20260919_v1"
if not st.session_state.get(_reset_marker):
    for _key in (
        "analysis",
        "mrp_priority_summary",
        "mrp_impact_detail",
        "mrp_import_preview_detail",
        "mrp_import_preview_summary",
    ):
        st.session_state[_key] = pd.DataFrame()
    for _key in (
        "pdfs", "zip_outputs", "prefilter_stats", "prefilter_files",
        "mrp_priority_stats", "danfe_outputs",
    ):
        st.session_state[_key] = {}
    for _key in (
        "prefilter_rejected", "prefilter_resolved", "danfe_results", "danfe_errors",
        "history", "current_test_manifest", "mrp_ignored_records",
    ):
        st.session_state[_key] = []
    st.session_state["mrp_priority_files"] = ()
    for _key in (
        "priority_nf_numbers", "priority_nf_keys",
        "priority_nf_doc_keys", "priority_date_nf_keys",
    ):
        st.session_state[_key] = set()

    # Também desmarca arquivos previamente enviados para que a análise não
    # reaproveite silenciosamente o lote anterior após atualizar a página.
    for _key in (
        "nf_hybrid_uploads", "danfe_xml_uploads",
        "mrp_materials", "mrp_entries",
        "treatment_editor", "_flash_mrp",
        "_flash_process", "_flash_nf",
    ):
        st.session_state.pop(_key, None)

    st.session_state[_reset_marker] = True

if not SAVE_NF_HISTORY:
    # Histórico oficial permanece vazio durante os testes.
    st.session_state.history = []

    # Limpa uma única vez qualquer base antiga de pré-notas carregada do banco.
    # Depois disso, novas cargas ficam somente na sessão para permitir os testes.
    _pre_test_reset_key = "_pre_notes_test_reset_20260918_v1"
    if not st.session_state.get(_pre_test_reset_key):
        st.session_state.pre_notes = pd.DataFrame()
        st.session_state.pre_import_preview = pd.DataFrame()
        st.session_state.pre_import_invalid_count = 0
        st.session_state.pre_import_name = ""
        st.session_state[_pre_test_reset_key] = True

cfg = st.session_state.cfg


def browser_icon():
    """Retorna o favicon salvo pelo usuário ou o favicon padrão do repositório."""
    data = str(cfg.get("favicon_data") or "").strip()
    try:
        if data:
            raw = base64.b64decode(data, validate=True)
        elif FAVICON_FILE.exists():
            raw = base64.b64decode(FAVICON_FILE.read_text(encoding="utf-8").strip(), validate=True)
        else:
            return "📄"
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
.intro,.setta-logo-card,.kpi-card,.panel{background:#fff;border:1px solid #e5e8ee;border-radius:14px}

.sidebar-brand{background:#f8fafc;border:1px solid #e5e8ee;border-radius:12px;padding:.9rem 1rem;margin:0 0 1.05rem 0}
.sidebar-brand-title{font-size:.92rem;font-weight:800;color:#111827;letter-spacing:-.01em}
.sidebar-brand-sub{margin-top:.18rem;font-size:.75rem;color:#6b7280}
.sidebar-section-label{margin:.25rem 0 .45rem 0;color:#374151;font-size:.76rem;font-weight:800;text-transform:uppercase;letter-spacing:.055em}
.sidebar-logo-preview{width:100%;min-height:82px;display:flex;justify-content:center;align-items:center;margin:.65rem 0 .5rem 0;padding:.65rem .8rem;background:#fff;border:1px dashed #d1d5db;border-radius:10px;box-sizing:border-box;overflow:hidden}
.sidebar-logo-preview img{display:block;width:auto;height:auto;max-width:140px;max-height:62px;object-fit:contain}
.sidebar-info-card{background:#f8fafc;border:1px solid #e5e8ee;border-radius:10px;padding:.75rem .85rem;color:#6b7280;font-size:.76rem;line-height:1.55}

section[data-testid="stSidebar"] div[role="radiogroup"]{display:flex;flex-direction:column;gap:.34rem}
section[data-testid="stSidebar"] div[role="radiogroup"] input[type="radio"],
section[data-testid="stSidebar"] div[role="radiogroup"] [data-testid="stMarkdownContainer"] + div{position:absolute!important;opacity:0!important;pointer-events:none!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label{position:relative;width:100%;min-height:42px;display:flex!important;align-items:center!important;padding:.56rem .72rem .56rem .88rem!important;margin:0!important;border:1px solid transparent!important;border-radius:10px!important;background:transparent!important;cursor:pointer;transition:background .14s ease,border-color .14s ease,box-shadow .14s ease,transform .14s ease;box-sizing:border-box}
section[data-testid="stSidebar"] div[role="radiogroup"] label>div:first-child{position:absolute!important;opacity:0!important;width:0!important;height:0!important;overflow:hidden!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label p{margin:0!important;font-size:.83rem!important;font-weight:600!important;color:#374151!important;line-height:1.2!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label:hover{background:#f8fafc!important;border-color:#e5e7eb!important;transform:translateX(1px)}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked){background:#111827!important;border-color:#111827!important;box-shadow:0 5px 14px rgba(17,24,39,.14)!important}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked)::before{content:"";position:absolute;left:.42rem;top:50%;width:4px;height:20px;border-radius:999px;background:#ef4444;transform:translateY(-50%)}
section[data-testid="stSidebar"] div[role="radiogroup"] label:has(input:checked) p{color:#fff!important;font-weight:700!important}

[data-testid="stAppViewContainer"] > .main,
[data-testid="stAppViewContainer"] .main,
[data-testid="stMain"],
.stMain{width:100%!important;max-width:100%!important;margin-left:0!important;margin-right:0!important}
[data-testid="stAppViewContainer"] .main .block-container,
[data-testid="stMain"] .block-container,
.stMain .block-container{width:100%!important;max-width:100%!important;margin-left:0!important;margin-right:0!important}
section[data-testid="stSidebar"][aria-expanded="false"]{width:0!important;min-width:0!important;max-width:0!important;flex-basis:0!important}

.setta-logo-card{width:100%;min-height:128px;display:flex;align-items:center;justify-content:center;background:#fff;border:1px solid #e5e8ee;border-radius:16px;box-shadow:0 4px 14px rgba(24,39,75,.08);box-sizing:border-box;margin:0 0 2.55rem 0;padding:1.1rem 2rem}
.setta-logo-card img{display:block;width:auto;height:auto;max-width:205px;max-height:86px;object-fit:contain}.fallback{font-size:2rem;letter-spacing:.08em}
.app-title{margin:0!important;padding:0!important;font-size:2.55rem!important;line-height:1.08!important;font-weight:800!important;letter-spacing:-.04em!important;color:#050505!important}
.app-sub{margin-top:.72rem!important;margin-bottom:1.65rem!important;color:#4f5661!important;font-size:.94rem!important;line-height:1.35!important}
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


def recalc(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    def cell_text(value: object) -> str:
        try:
            if value is None or pd.isna(value):
                return ""
        except Exception:
            pass
        return str(value).strip()

    out = df.copy()
    names, stats, issues = [], [], []

    for _, row in out.iterrows():
        due = row.get("vencimento")

        # Pandas transforma datas ausentes em NaT. NaT se comporta como data em
        # alguns testes de tipo, mas lança ValueError ao chamar strftime().
        try:
            if due is None or pd.isna(due):
                due = None
        except Exception:
            pass

        if isinstance(due, (pd.Timestamp, datetime)):
            due = due.date()
        elif isinstance(due, str) and due.strip():
            parsed = pd.to_datetime(due, errors="coerce", dayfirst=True)
            due = None if pd.isna(parsed) else parsed.date()

        num = cell_text(row.get("numero_nf"))
        cnpj = digits_only(cell_text(row.get("cnpj_fornecedor")))
        supplier = cell_text(row.get("fornecedor_padrao"))
        nature = cell_text(row.get("natureza")).upper()
        company = cell_text(row.get("empresa_sigla")).upper()

        missing = []
        if due is None:
            missing.append("vencimento")
        if not digits_only(num):
            missing.append("número NF")
        if not valid_cnpj(cnpj):
            missing.append("CNPJ")
        if not supplier:
            missing.append("fornecedor")
        if not nature:
            missing.append("natureza")
        if company not in {"SEN", "SEE", "STA"}:
            missing.append("empresa")

        names.append(build_final_name(due, num, supplier))

        current = cell_text(row.get("status")) or "REVISAR"
        xml_status = cell_text(row.get("xml_status_codigo"))
        origin = cell_text(row.get("origem_dados")).upper()

        # Campo obrigatório ausente sempre exige tratativa.
        # XML autorizado (cStat=100) pode ser aprovado automaticamente quando
        # todos os dados obrigatórios estiverem completos — inclusive natureza
        # recuperada da carga STSUP01. Casos PDF/baixa confiança continuam
        # respeitando a decisão manual do operador.
        if missing:
            final_status = "REVISAR"
        elif "XML" in origin and xml_status == "100":
            final_status = "APROVADO"
        else:
            final_status = (
                current
                if current in {"APROVADO", "REVISAR"}
                else "REVISAR"
            )

        stats.append(final_status)
        issues.append(
            "Campos pendentes: " + ", ".join(missing)
            if missing else ""
        )

    out["nome_sugerido"] = names
    out["status"] = stats
    out["validacao"] = issues
    return out


def treatment_mask(df: pd.DataFrame) -> pd.Series:
    if df.empty:
        return pd.Series(False, index=df.index)
    return (
        df["nome_sugerido"].fillna("").astype(str).str.strip().eq("")
        | df["status"].fillna("").astype(str).ne("APROVADO")
        | df["validacao"].fillna("").astype(str).str.strip().ne("")
    )


def metrics(df: pd.DataFrame):
    pending = treatment_mask(df)
    ready = int((~pending).sum())
    values = [
        ("Documentos", len(df), "XML/PDF analisados"),
        ("Prontos", ready, "Sem tratativa"),
        ("Tratativas", int(pending.sum()), "Corrigir antes do ZIP"),
        ("Prioridade", int(df.get("prioridade_mrp", pd.Series(False, index=df.index)).fillna(False).astype(bool).sum()), "ZIP separado"),
    ]
    for col, (title, number, desc) in zip(st.columns(4), values):
        col.markdown(
            f'<div class="metric"><small>{title}</small><strong>{number}</strong><span>{desc}</span></div>',
            unsafe_allow_html=True,
        )


def excel_bytes(frame: pd.DataFrame, sheet: str = "Dados") -> bytes:
    """Gera XLSX seguro para dados vindos do Supabase.

    O Excel/openpyxl não aceita datetimes com timezone. A exportação usa uma
    cópia do DataFrame, converte timestamps com fuso para o horário local e
    remove somente a informação de timezone da célula. O DataFrame original
    e os registros persistidos permanecem inalterados.
    """
    export = frame.copy()

    def excel_safe_value(value):
        if value is None:
            return None

        try:
            if pd.isna(value):
                return None
        except Exception:
            pass

        if isinstance(value, pd.Timestamp):
            if value.tzinfo is not None:
                try:
                    value = value.tz_convert(TZ).tz_localize(None)
                except Exception:
                    value = value.tz_localize(None)
            return value.to_pydatetime()

        if isinstance(value, datetime):
            if value.tzinfo is not None:
                try:
                    value = value.astimezone(TZ).replace(tzinfo=None)
                except Exception:
                    value = value.replace(tzinfo=None)
            return value

        if isinstance(value, (dict, list, tuple, set)):
            return json.dumps(
                value,
                ensure_ascii=False,
                default=str,
            )

        item_method = getattr(value, "item", None)
        if callable(item_method):
            try:
                return excel_safe_value(item_method())
            except Exception:
                pass

        return value

    for column in export.columns:
        series = export[column]

        # DatetimeTZDtype precisa ser normalizado antes do to_excel.
        if isinstance(series.dtype, pd.DatetimeTZDtype):
            export[column] = (
                series.dt.tz_convert(TZ)
                .dt.tz_localize(None)
            )
            continue

        # Colunas object podem conter Timestamp/datetime individuais,
        # listas JSON ou escalares NumPy.
        if series.dtype == "object":
            export[column] = series.map(excel_safe_value)

    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        export.to_excel(writer, index=False, sheet_name=sheet[:31])
    return buffer.getvalue()


def set_flash(key: str, level: str, message: str) -> None:
    st.session_state[key] = {"level": level, "message": message}


def show_flash(key: str) -> None:
    payload = st.session_state.pop(key, None)
    if not isinstance(payload, dict):
        return
    level = str(payload.get("level") or "info")
    message = str(payload.get("message") or "")
    fn = getattr(st, level, st.info)
    if message:
        fn(message)


def _format_update_timestamp(value: object) -> str:
    if value is None or str(value).strip() == "":
        return "Ainda não atualizada"
    try:
        ts = pd.to_datetime(value, errors="coerce", utc=True)
        if pd.isna(ts):
            return "Ainda não atualizada"
        return ts.tz_convert(TZ).strftime("%d/%m/%Y às %H:%M")
    except Exception:
        return str(value)


def _last_update_info(kind: str) -> tuple[str, str]:
    """Retorna data/hora real da última gravação e a origem, quando disponível."""
    if not db.configured():
        return "Banco não conectado", ""

    try:
        if kind == "pre":
            rows = db.list_pre_note_imports(limit=1)
            if not rows:
                return "Ainda não atualizada", ""
            row = rows[0]
            return (
                _format_update_timestamp(row.get("importado_em")),
                str(row.get("arquivo_nome") or "").strip(),
            )

        if kind == "mrp":
            row = db.load_mrp_load()
            if not row:
                return "Ainda não atualizada", ""
            files = row.get("arquivos") or []
            source = " + ".join(str(item) for item in files if str(item).strip())
            return _format_update_timestamp(row.get("atualizado_em")), source

        if kind == "suppliers":
            rows = db.list_supplier_imports(limit=1)
            if not rows:
                return "Ainda não atualizada", ""
            row = rows[0]
            return (
                _format_update_timestamp(row.get("importado_em")),
                str(row.get("arquivo_nome") or "").strip(),
            )

        if kind == "process":
            rows = db.list_process_records(limit=1)
            if not rows:
                return "Ainda não atualizada", ""
            row = rows[0]
            return (
                _format_update_timestamp(row.get("processado_em")),
                str(row.get("arquivo_final") or row.get("arquivo_original") or "").strip(),
            )
    except Exception:
        return "Não foi possível consultar", ""

    return "Ainda não atualizada", ""


def show_last_update(kind: str) -> None:
    updated, source = _last_update_info(kind)
    suffix = f" • {source}" if source else ""
    st.caption(f"Última atualização: **{updated}**{suffix}")


@st.cache_data(show_spinner=False, max_entries=20)
def _read_uploaded_table_cached(
    raw: bytes,
    name: str,
    sheet_name: str | None,
    header_row: int | None,
) -> tuple[pd.DataFrame, list[str]]:
    suffix = Path(name.lower()).suffix.lower()

    if suffix == ".csv":
        for sep in [None, ";", ",", "\t"]:
            try:
                frame = pd.read_csv(
                    io.BytesIO(raw),
                    dtype=str,
                    sep=sep,
                    engine="python" if sep is None else "c",
                    header=header_row,
                ).fillna("")
                if frame.shape[1] > 1 or sep == "\t":
                    return frame, []
            except Exception:
                pass
        raise ValueError("Não foi possível interpretar o CSV.")

    if suffix in {".xls", ".xlt"}:
        try:
            book = pd.ExcelFile(io.BytesIO(raw), engine="xlrd")
            sheets = book.sheet_names
            selected = sheet_name if sheet_name in sheets else sheets[0]
            frame = pd.read_excel(
                io.BytesIO(raw),
                sheet_name=selected,
                dtype=str,
                header=header_row,
                engine="xlrd",
            ).fillna("")
            return frame, sheets
        except Exception as exc:
            raise ValueError(f"Não foi possível abrir o arquivo {suffix}: {exc}") from exc

    # XLSX / XLTX: leitura streaming. Evita o travamento causado por relatórios
    # do Protheus com grande área formatada/used-range.
    try:
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        sheets = list(wb.sheetnames)
        selected = sheet_name if sheet_name in sheets else sheets[0]
        ws = wb[selected]

        rows = []
        started = False
        blank_streak = 0
        max_rows = 250_000

        for row in ws.iter_rows(values_only=True):
            values = list(row)
            is_blank = not any(v is not None and str(v).strip() != "" for v in values)

            if is_blank:
                if started:
                    blank_streak += 1
                    if blank_streak >= 150:
                        break
                continue

            started = True
            blank_streak = 0
            rows.append(values)
            if len(rows) >= max_rows:
                raise ValueError(
                    "A planilha excede 250.000 linhas úteis. Gere o relatório novamente com apenas os dados necessários."
                )

        wb.close()

        if not rows:
            return pd.DataFrame(), sheets

        width = max(len(row) for row in rows)
        rows = [row + [None] * (width - len(row)) for row in rows]

        if header_row is None:
            frame = pd.DataFrame(rows)
        else:
            h = int(header_row)
            if h >= len(rows):
                return pd.DataFrame(), sheets
            columns = [
                str(v).strip() if v is not None and str(v).strip() else f"COL_{i+1}"
                for i, v in enumerate(rows[h])
            ]
            frame = pd.DataFrame(rows[h + 1 :], columns=columns)

        return frame.fillna(""), sheets
    except Exception as exc:
        raise ValueError(f"Não foi possível abrir o arquivo {suffix or 'Excel'}: {exc}") from exc


def read_uploaded_table(
    uploaded,
    sheet_name: str | None = None,
    header_row: int | None = 0,
) -> tuple[pd.DataFrame, list[str]]:
    return _read_uploaded_table_cached(
        uploaded.getvalue(),
        uploaded.name,
        sheet_name,
        header_row,
    )


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


def normalized_material_code(value) -> str:
    raw = str(value or "").strip()
    digits = digits_only(raw)
    if digits and re.fullmatch(r"[\d\s.\-/]+", raw):
        return digits.lstrip("0") or "0"
    return normalize_text(raw)


def pre_note_key(numero_nf, cnpj) -> str:
    nf = normalized_nf(numero_nf)
    doc = digits_only(cnpj)
    return f"{nf}|{doc}" if nf and doc else ""


def normalized_business_date(value) -> date | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    return None if pd.isna(parsed) else parsed.date()


def date_nf_key(data_pre_nota, numero_nf) -> str:
    op_date = normalized_business_date(data_pre_nota)
    nf = normalized_nf(numero_nf)
    return f"{op_date.isoformat()}|{nf}" if op_date and nf else ""


def supplier_name_from_cnpj(cnpj: object) -> str:
    doc = digits_only(cnpj)
    if not doc:
        return ""
    suppliers = supplier_dataframe(st.session_state.suppliers)
    if suppliers.empty:
        return ""
    hit = suppliers[
        suppliers["cnpj"].map(digits_only).eq(doc)
        & suppliers["ativo"].fillna(True).astype(bool)
    ]
    if hit.empty:
        return ""
    return str(hit.iloc[0].get("nome_padrao") or "").strip()


def supplier_validation_name(value: object) -> str:
    raw = str(value or "").strip()
    if not raw or raw.upper() == "NÃO LOCALIZADO":
        return ""
    # A validação do vínculo usa o nome efetivamente presente nos relatórios.
    # A base de fornecedores pode complementar o nome da pré-nota quando necessário,
    # mas não deve substituir os dois lados por uma inferência fuzzy antes da comparação.
    return normalize_text(raw)


def supplier_similarity(name_a: object, name_b: object) -> int:
    a = supplier_validation_name(name_a)
    b = supplier_validation_name(name_b)
    if not a or not b:
        return 0
    if a == b:
        return 100

    # Combina comparação por conjunto e por ordem de palavras para evitar
    # falsos positivos como um nome muito curto contido em outro fornecedor.
    set_score = float(fuzz.token_set_ratio(a, b))
    sort_score = float(fuzz.token_sort_ratio(a, b))
    score = int(round((set_score * 0.55) + (sort_score * 0.45)))

    a_tokens = set(a.split())
    b_tokens = set(b.split())
    common = a_tokens & b_tokens
    min_tokens = min(len(a_tokens), len(b_tokens))
    max_tokens = max(len(a_tokens), len(b_tokens))

    # Quando os nomes compartilham pelo menos duas palavras relevantes e
    # possuem boa cobertura mútua, reforça a equivalência sem aceitar siglas
    # isoladas como correspondência automática.
    if (
        len(common) >= 2
        and min_tokens >= 2
        and max_tokens > 0
        and len(common) / max_tokens >= 0.60
    ):
        score = max(score, 90)

    return min(100, max(0, score))



def mrp_row_key(row: pd.Series | dict) -> str:
    data_nf = str(row.get("data_nf") or "").strip()
    if not data_nf:
        data_nf = date_nf_key(
            row.get("data_pre_nota"),
            row.get("numero_nf"),
        )

    supplier = str(
        row.get("fornecedor_validacao")
        or row.get("fornecedor")
        or ""
    ).strip()
    supplier_norm = supplier_validation_name(supplier)

    return f"{data_nf}|{supplier_norm}" if data_nf and supplier_norm else data_nf




def pre_supplier_name(row: pd.Series | dict) -> str:
    direct = str(row.get("fornecedor") or "").strip()
    if direct and direct.upper() != "NÃO LOCALIZADO":
        return direct
    return supplier_name_from_cnpj(row.get("cnpj"))


def match_pre_note_to_mrp(
    pre_row: pd.Series | dict,
    summary: pd.DataFrame,
    min_supplier_score: int = 82,
) -> dict:
    result = {
        "matched": False,
        "situacao": "NÃO LOCALIZADA NO IMPACTO MRP",
        "score_fornecedor": 0,
        "row": None,
    }
    if not isinstance(summary, pd.DataFrame) or summary.empty:
        result["situacao"] = "IMPACTO MRP NÃO CARREGADO"
        return result

    key = date_nf_key(pre_row.get("data_pre_nota"), pre_row.get("numero_nf"))
    if not key:
        result["situacao"] = "DATA OU NF INVÁLIDA"
        return result

    if "data_nf" not in summary.columns:
        return result

    candidates = summary[summary["data_nf"].astype(str).eq(key)].copy()
    if candidates.empty:
        return result

    pre_supplier = pre_supplier_name(pre_row)
    if not pre_supplier:
        result["situacao"] = "FORNECEDOR DA PRÉ-NOTA NÃO LOCALIZADO"
        return result

    candidates["_score_supplier"] = candidates["fornecedor"].map(
        lambda value: supplier_similarity(pre_supplier, value)
    )
    candidates = candidates.sort_values(
        ["_score_supplier", "prioridade", "data_cm"],
        ascending=[False, True, True],
        na_position="last",
    )

    best = candidates.iloc[0]
    best_score = int(best["_score_supplier"])

    if best_score < min_supplier_score:
        result["situacao"] = "FORNECEDOR DIVERGENTE"
        result["score_fornecedor"] = best_score
        return result

    if len(candidates) > 1:
        second_score = int(candidates.iloc[1]["_score_supplier"])
        best_supplier = supplier_validation_name(best.get("fornecedor"))
        second_supplier = supplier_validation_name(candidates.iloc[1].get("fornecedor"))
        if (
            best_supplier != second_supplier
            and second_score >= min_supplier_score
            and best_score - second_score <= 3
        ):
            result["situacao"] = "CORRESPONDÊNCIA AMBÍGUA"
            result["score_fornecedor"] = best_score
            return result

    result.update(
        matched=True,
        situacao="OK",
        score_fornecedor=best_score,
        row=best.to_dict(),
    )
    return result


def match_mrp_to_pre_note(
    mrp_row: pd.Series | dict,
    pre_notes: pd.DataFrame,
    min_supplier_score: int = 82,
) -> dict:
    result = {
        "matched": False,
        "situacao": "AUSENTE NAS PRÉ-NOTAS",
        "score_fornecedor": 0,
        "row": None,
    }
    if not isinstance(pre_notes, pd.DataFrame) or pre_notes.empty:
        return result

    key = date_nf_key(mrp_row.get("data_pre_nota"), mrp_row.get("numero_nf"))
    if not key:
        result["situacao"] = "DATA OU NF INVÁLIDA"
        return result

    candidates = pre_notes.copy()
    candidates["_data_nf"] = candidates.apply(
        lambda row: date_nf_key(row.get("data_pre_nota"), row.get("numero_nf")),
        axis=1,
    )
    candidates = candidates[candidates["_data_nf"].eq(key)].copy()
    if candidates.empty:
        return result

    mrp_supplier = str(mrp_row.get("fornecedor") or "").strip()
    candidates["_supplier_pre"] = candidates.apply(pre_supplier_name, axis=1)
    candidates["_score_supplier"] = candidates["_supplier_pre"].map(
        lambda value: supplier_similarity(value, mrp_supplier)
    )
    candidates = candidates.sort_values("_score_supplier", ascending=False)

    best = candidates.iloc[0]
    best_score = int(best["_score_supplier"])

    if best_score < min_supplier_score:
        result["situacao"] = "FORNECEDOR DIVERGENTE"
        result["score_fornecedor"] = best_score
        return result

    strong_candidates = candidates[
        candidates["_score_supplier"] >= min_supplier_score
    ].copy()
    if len(strong_candidates) > 1:
        strong_dates = {
            normalized_business_date(value)
            for value in strong_candidates["data_pre_nota"].tolist()
            if normalized_business_date(value) is not None
        }
        if len(strong_dates) > 1:
            result["situacao"] = "CORRESPONDÊNCIA AMBÍGUA ENTRE DATAS"
            result["score_fornecedor"] = best_score
            return result

    if len(candidates) > 1:
        second = candidates.iloc[1]
        second_score = int(second["_score_supplier"])
        if (
            supplier_validation_name(best.get("_supplier_pre"))
            != supplier_validation_name(second.get("_supplier_pre"))
            and second_score >= min_supplier_score
            and best_score - second_score <= 3
        ):
            result["situacao"] = "CORRESPONDÊNCIA AMBÍGUA"
            result["score_fornecedor"] = best_score
            return result

    result.update(
        matched=True,
        situacao="OK",
        score_fornecedor=best_score,
        row=best.to_dict(),
    )
    return result


def priority_key(numero_nf, fornecedor) -> str:
    nf = normalized_nf(numero_nf)
    nome = normalize_text(fornecedor)
    return f"{nf}|{nome}" if nf and nome else ""


def standard_supplier_name(name: object) -> str:
    raw = str(name or "").strip()
    if not raw:
        return ""
    matched = match_supplier("", raw, st.session_state.suppliers)
    return str(matched.get("nome_padrao") or raw).strip()



def _supplier_code_norm(value: object) -> str:
    digits = digits_only(value)
    return (digits.lstrip("0") or "0") if digits else ""


def _join_unique(values) -> str:
    out = []
    seen = set()
    for value in values:
        text_value = str(value or "").strip()
        if not text_value or text_value.lower() == "nan" or text_value in seen:
            continue
        seen.add(text_value)
        out.append(text_value)
    return ", ".join(out)


@st.cache_data(show_spinner=False, max_entries=8)
def _clean_mrp_materials_cached(raw: bytes, name: str) -> tuple[pd.DataFrame, dict]:
    suffix = Path(name.lower()).suffix.lower()
    rows = []

    if suffix in {".xlsx", ".xltx"}:
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        try:
            ws = wb[wb.sheetnames[0]]
            for idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
                if idx == 1:
                    continue
                projeto = row[1] if len(row) > 1 else None
                produto = row[2] if len(row) > 2 else None
                data_cm = row[5] if len(row) > 5 else None
                rows.append((projeto, produto, data_cm))
        finally:
            wb.close()
        base = pd.DataFrame(rows, columns=["projeto", "produto", "data_cm"])
    else:
        temp, _ = _read_uploaded_table_cached(raw, name, None, None)
        if temp.shape[1] < 6:
            raise ValueError("O relatório de Materiais precisa conter pelo menos as colunas A até F.")
        base = pd.DataFrame({
            "projeto": temp.iloc[:, 1],
            "produto": temp.iloc[:, 2],
            "data_cm": temp.iloc[:, 5],
        })

    base["produto"] = base["produto"].map(normalized_material_code)
    base["projeto"] = (
        base["projeto"].fillna("").astype(str).str.replace(r"\.0$", "", regex=True).str.strip()
    )
    base["data_cm"] = pd.to_datetime(base["data_cm"], errors="coerce", dayfirst=True).dt.date

    total_raw = len(base)
    invalid = int((base["produto"].eq("") | base["data_cm"].isna()).sum())
    base = base[base["produto"].ne("") & base["data_cm"].notna()].copy()

    cleaned = (
        base.groupby(["produto", "data_cm"], as_index=False, dropna=False)
        .agg(
            ops=("projeto", _join_unique),
            linhas_origem=("projeto", "size"),
        )
        .sort_values(["produto", "data_cm"], ascending=[True, True])
        .reset_index(drop=True)
    )

    stats = {
        "linhas_origem": total_raw,
        "invalidas": invalid,
        "linhas_limpas": len(cleaned),
        "produtos": int(cleaned["produto"].nunique()) if not cleaned.empty else 0,
        "linhas_unificadas": max(0, total_raw - invalid - len(cleaned)),
    }
    return cleaned, stats


@st.cache_data(show_spinner=False, max_entries=8)
def _clean_mrp_nf_cached(
    raw: bytes,
    name: str,
    reference_date_iso: str,
) -> tuple[pd.DataFrame, dict]:
    reference_date = date.fromisoformat(reference_date_iso)
    cutoff = reference_date - timedelta(days=29)
    suffix = Path(name.lower()).suffix.lower()

    columns = [
        "data_pre_nota", "numero_nf", "fornecedor_codigo", "fornecedor",
        "cr", "desc_cr", "natureza", "produto", "descricao", "tes",
    ]
    rows = []
    total_raw = 0
    dropped_tes = 0
    dropped_date = 0
    invalid_date = 0

    def accept(values):
        nonlocal total_raw, dropped_tes, dropped_date, invalid_date
        total_raw += 1

        tes = str(values[9] or "").strip()
        if re.fullmatch(r"\d{3}", tes):
            dropped_tes += 1
            return

        parsed = pd.to_datetime(values[0], errors="coerce", dayfirst=True)
        if pd.isna(parsed):
            invalid_date += 1
            return

        op_date = parsed.date()
        if op_date < cutoff or op_date > reference_date:
            dropped_date += 1
            return

        numero_nf = normalized_nf(values[1])
        produto = normalized_material_code(values[7])
        fornecedor_codigo = _supplier_code_norm(values[2])
        fornecedor = str(values[3] or "").strip()

        if not numero_nf or not produto or not fornecedor_codigo:
            return

        rows.append({
            "data_pre_nota": op_date,
            "numero_nf": numero_nf,
            "fornecedor_codigo": fornecedor_codigo,
            "fornecedor": fornecedor,
            "cr": re.sub(r"\.0$", "", str(values[4] or "").strip()),
            "desc_cr": str(values[5] or "").strip(),
            "natureza": str(values[6] or "").strip(),
            "produto": produto,
            "descricao": str(values[8] or "").strip(),
            "tes": tes,
        })

    if suffix in {".xlsx", ".xltx"}:
        wb = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
        try:
            ws = wb[wb.sheetnames[0]]
            for idx, row in enumerate(ws.iter_rows(values_only=True), start=1):
                if idx <= 2:
                    continue
                if len(row) < 31:
                    continue
                accept((
                    row[0], row[3], row[4], row[5], row[6],
                    row[7], row[8], row[11], row[12], row[30],
                ))
        finally:
            wb.close()
    else:
        temp, _ = _read_uploaded_table_cached(raw, name, None, None)
        if temp.shape[1] < 31:
            raise ValueError("O relatório de NFs precisa conter pelo menos as colunas A até AE.")
        for row in temp.itertuples(index=False, name=None):
            accept((
                row[0], row[3], row[4], row[5], row[6],
                row[7], row[8], row[11], row[12], row[30],
            ))

    base = pd.DataFrame(rows, columns=columns)
    stats = {
        "linhas_origem": total_raw,
        "linhas_30_dias_tes": len(base),
        "descartadas_tes": dropped_tes,
        "descartadas_data": dropped_date,
        "datas_invalidas": invalid_date,
        "inicio_periodo": cutoff,
        "fim_periodo": reference_date,
    }
    return base, stats


def _supplier_cnpj_lookup(entries: pd.DataFrame) -> tuple[pd.Series, int]:
    suppliers = supplier_dataframe(st.session_state.suppliers).copy()
    if suppliers.empty:
        return pd.Series([""] * len(entries), index=entries.index), len(entries)

    suppliers = suppliers[suppliers["ativo"]].copy()
    suppliers["_codigo_norm"] = suppliers["codigo"].map(_supplier_code_norm)
    suppliers = suppliers[
        suppliers["_codigo_norm"].ne("")
        & suppliers["cnpj"].map(valid_cnpj)
    ].copy()

    by_code = {
        code: group.copy()
        for code, group in suppliers.groupby("_codigo_norm", sort=False)
    }

    cache = {}
    unresolved = 0
    result = []

    for _, row in entries.iterrows():
        code = _supplier_code_norm(row.get("fornecedor_codigo"))
        desc = str(row.get("fornecedor") or "").strip()
        cache_key = (code, normalize_text(desc))

        if cache_key in cache:
            cnpj = cache[cache_key]
            result.append(cnpj)
            if not cnpj:
                unresolved += 1
            continue

        group = by_code.get(code)
        cnpj = ""
        if group is not None and not group.empty:
            unique_docs = group["cnpj"].dropna().astype(str).unique().tolist()
            if len(unique_docs) == 1:
                cnpj = unique_docs[0]
            else:
                matched = match_supplier("", desc, group)
                matched_name = str(matched.get("nome_padrao") or "").strip()
                if matched_name:
                    hit = group[group["nome_padrao"].astype(str).eq(matched_name)]
                    hit_docs = hit["cnpj"].dropna().astype(str).unique().tolist()
                    if len(hit_docs) == 1:
                        cnpj = hit_docs[0]

        cache[cache_key] = cnpj
        result.append(cnpj)
        if not cnpj:
            unresolved += 1

    return pd.Series(result, index=entries.index), unresolved


def _build_mrp_impact(
    materials: pd.DataFrame,
    entries: pd.DataFrame,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    if entries.empty:
        empty_detail = pd.DataFrame(columns=[
            "data_pre_nota", "numero_nf", "cnpj", "fornecedor",
            "produto", "descricao", "prioridade", "ops", "data_cm",
            "data_nf", "fornecedor_validacao", "cr", "desc_cr", "natureza",
        ])
        empty_summary = pd.DataFrame(columns=[
            "data_nf", "data_pre_nota", "numero_nf", "cnpj", "fornecedor",
            "fornecedor_validacao", "natureza", "cr", "desc_cr",
            "prioridade", "ops", "data_cm", "itens_impacto",
        ])
        return empty_detail, empty_summary, {"cnpj_nao_localizado": 0}

    material_priority = (
        materials.sort_values(["produto", "data_cm"], ascending=[True, True])
        .drop_duplicates("produto", keep="first")
        [["produto", "data_cm", "ops"]]
        .copy()
    )

    detail = entries.merge(
        material_priority,
        on="produto",
        how="left",
        validate="many_to_one",
    )
    detail["prioridade"] = detail["data_cm"].notna().map({True: "ALTA", False: "BAIXA"})
    detail["ops"] = detail["ops"].fillna("").astype(str)

    # O CNPJ continua disponível como dado auxiliar, mas não participa mais
    # da chave de vínculo entre Pré-notas e Impacto MRP.
    cnpj_series, unresolved = _supplier_cnpj_lookup(detail)
    detail["cnpj"] = cnpj_series.map(digits_only)

    detail["data_nf"] = detail.apply(
        lambda row: date_nf_key(row.get("data_pre_nota"), row.get("numero_nf")),
        axis=1,
    )
    detail["fornecedor_validacao"] = detail["fornecedor"].map(
        lambda value: standard_supplier_name(value) or str(value or "").strip()
    )
    detail["_fornecedor_norm"] = detail["fornecedor_validacao"].map(
        supplier_validation_name
    )
    detail["_grupo_vinculo"] = detail.apply(
        lambda row: (
            f"{row.get('data_nf')}|{row.get('_fornecedor_norm')}"
            if row.get("data_nf") and row.get("_fornecedor_norm")
            else ""
        ),
        axis=1,
    )

    detail = detail[
        [
            "data_pre_nota", "numero_nf", "cnpj", "fornecedor",
            "fornecedor_validacao", "produto", "descricao", "prioridade",
            "ops", "data_cm", "data_nf", "_grupo_vinculo",
            "fornecedor_codigo", "cr", "desc_cr", "natureza", "tes",
        ]
    ].copy()

    summary_rows = []
    valid_groups = detail[
        detail["data_nf"].ne("")
        & detail["_grupo_vinculo"].ne("")
    ].copy()

    for group_key, group in valid_groups.groupby("_grupo_vinculo", sort=False):
        high = group[group["prioridade"].eq("ALTA")].copy()
        is_high = not high.empty
        oldest_cm = high["data_cm"].dropna().min() if is_high else None
        ops = _join_unique(high["ops"].tolist()) if is_high else ""
        natureza = _join_unique(
            group["natureza"].fillna("").astype(str).str.strip().tolist()
        )
        cr = _join_unique(
            group["cr"].fillna("").astype(str).str.strip().tolist()
        )
        desc_cr = _join_unique(
            group["desc_cr"].fillna("").astype(str).str.strip().tolist()
        )

        summary_rows.append({
            "data_nf": group["data_nf"].iloc[0],
            "data_pre_nota": group["data_pre_nota"].dropna().min(),
            "numero_nf": group["numero_nf"].iloc[0],
            "cnpj": group["cnpj"].iloc[0],
            "fornecedor": group["fornecedor"].iloc[0],
            "fornecedor_validacao": group["fornecedor_validacao"].iloc[0],
            "natureza": natureza,
            "cr": cr,
            "desc_cr": desc_cr,
            "prioridade": "ALTA" if is_high else "BAIXA",
            "ops": ops,
            "data_cm": oldest_cm,
            "itens_impacto": int(high["produto"].nunique()) if is_high else 0,
        })

    summary = pd.DataFrame(summary_rows)
    if not summary.empty:
        summary["_ord"] = summary["prioridade"].map({"ALTA": 0, "BAIXA": 1}).fillna(9)
        summary = summary.sort_values(
            ["_ord", "data_cm", "data_pre_nota", "numero_nf", "fornecedor_validacao"],
            ascending=[True, True, False, True, True],
            na_position="last",
        ).drop(columns="_ord").reset_index(drop=True)

    stats = {
        "cnpj_nao_localizado": unresolved,
        "linhas_detalhe": len(detail),
        "nfs_total": len(summary),
        "nfs_alta": int(summary["prioridade"].eq("ALTA").sum()) if not summary.empty else 0,
        "nfs_baixa": int(summary["prioridade"].eq("BAIXA").sum()) if not summary.empty else 0,
    }
    return detail, summary, stats


def render_mrp_priority_feed(key_prefix: str = "mrp", allow_feed: bool = True) -> None:
    show_flash("_flash_mrp")
    st.markdown("### Priorização por impacto no MRP")
    show_last_update("mrp")

    if allow_feed:
        st.write(
            "Carregue os dois relatórios. Antes do confronto, o aplicativo reduz as bases para somente "
            "os campos necessários: Materiais usa **B Projeto, C Produto e F Data CM**; Entradas/NFs usa "
            "**A, D, E, F, G, H, I, L, M e AE**. No relatório de NFs são mantidos apenas os últimos "
            "**30 dias** e são mantidos somente os registros cujo **TES NÃO seja um código de exatamente 3 dígitos** "
            "(na prática, normalmente TES em branco)."
        )

        material_file = st.file_uploader(
            "Relatório de Materiais",
            type=["xlsx", "xltx", "xls", "csv"],
            key=f"{key_prefix}_materials",
        )
        nf_file = st.file_uploader(
            "Relatório de NFs / STSUP01",
            type=["xlsx", "xltx", "xls", "csv"],
            key=f"{key_prefix}_entries",
        )

        can_validate = bool(material_file and nf_file)
        validate = st.button(
            "VALIDAR IMPACTO MRP",
            type="primary",
            use_container_width=True,
            disabled=not can_validate,
            key=f"{key_prefix}_process",
        )

        if validate:
            try:
                with st.spinner("Limpando os relatórios e montando a base de impacto MRP..."):
                    materials, mat_stats = _clean_mrp_materials_cached(
                        material_file.getvalue(),
                        material_file.name,
                    )
                    entries, nf_stats = _clean_mrp_nf_cached(
                        nf_file.getvalue(),
                        nf_file.name,
                        now_local().date().isoformat(),
                    )
                    detail, summary, impact_stats = _build_mrp_impact(materials, entries)

                    st.session_state.mrp_import_preview_detail = detail.copy()
                    st.session_state.mrp_import_preview_summary = summary.copy()
                    st.session_state.mrp_priority_stats = {
                        **mat_stats,
                        **nf_stats,
                        **impact_stats,
                    }
                    st.session_state.mrp_priority_files = (
                        material_file.name,
                        nf_file.name,
                    )

                set_flash(
                    "_flash_mrp",
                    "success" if not detail.empty else "warning",
                    (
                        f"Validação concluída: {len(detail)} linha(s) na tabela principal, "
                        f"{impact_stats['nfs_alta']} NF(s) em prioridade ALTA."
                        if not detail.empty
                        else "Os relatórios foram processados, mas a base final ficou vazia."
                    ),
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Falha ao validar impacto MRP: {exc}")

        preview = st.session_state.get("mrp_import_preview_detail")
        summary_preview = st.session_state.get("mrp_import_preview_summary")
        stats = st.session_state.get("mrp_priority_stats") or {}
        files_used = st.session_state.get("mrp_priority_files") or ()

        if isinstance(preview, pd.DataFrame) and not preview.empty:
            if files_used:
                st.caption(f"Carga validada: {files_used[0]} + {files_used[1]}")

            st.markdown("#### Conferência da carga")
            st.caption(
                f"Materiais: {stats.get('linhas_origem', 0)} linha(s) de origem. "
                f"Base de NFs após 30 dias + exclusão de TES com 3 dígitos: {stats.get('linhas_30_dias_tes', 0)} linha(s). "
                f"CNPJs não localizados pelo código do fornecedor: {stats.get('cnpj_nao_localizado', 0)}."
            )

            display = preview[
                [
                    "data_pre_nota", "numero_nf", "cnpj", "fornecedor",
                    "natureza", "cr", "desc_cr",
                    "produto", "descricao", "prioridade", "ops", "data_cm",
                ]
            ].copy()

            st.dataframe(
                display,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "data_pre_nota": st.column_config.DateColumn(
                        "DATA DA PRÉ-NOTA", format="DD/MM/YYYY"
                    ),
                    "numero_nf": "NF",
                    "cnpj": "CNPJ",
                    "fornecedor": st.column_config.TextColumn("FORNECEDOR", width="large"),
                    "natureza": st.column_config.TextColumn("NATUREZA", width="medium"),
                    "cr": st.column_config.TextColumn("CR", width="small"),
                    "desc_cr": st.column_config.TextColumn("DESC. CR", width="medium"),
                    "produto": "PRODUTO",
                    "descricao": st.column_config.TextColumn("DESCRIÇÃO", width="large"),
                    "prioridade": "PRIORIDADE",
                    "ops": st.column_config.TextColumn("OPS", width="large"),
                    "data_cm": st.column_config.DateColumn("DATA CM", format="DD/MM/YYYY"),
                },
            )

            if st.button(
                "CONFIRMAR E APLICAR CARGA",
                type="primary",
                use_container_width=True,
                key=f"{key_prefix}_confirm",
            ):
                st.session_state.mrp_impact_detail = preview.copy()
                st.session_state.mrp_ignored_records = []
                st.session_state.mrp_priority_summary = (
                    summary_preview.copy()
                    if isinstance(summary_preview, pd.DataFrame)
                    else pd.DataFrame()
                )

                summary = st.session_state.mrp_priority_summary
                high = (
                    summary[summary["prioridade"].eq("ALTA")].copy()
                    if not summary.empty
                    else pd.DataFrame()
                )

                # A prioridade oficial passa a ser vinculada por DATA + NF.
                # O nome do fornecedor é usado como validação da correspondência,
                # não o CNPJ.
                st.session_state.priority_date_nf_keys = set(
                    high.get("data_nf", pd.Series(dtype=str)).dropna().astype(str).tolist()
                )
                st.session_state.priority_nf_doc_keys = set()
                st.session_state.priority_nf_keys = set()
                st.session_state.priority_nf_numbers = set(
                    high.get("numero_nf", pd.Series(dtype=str)).dropna().astype(str).tolist()
                )

                if not st.session_state.analysis.empty:
                    st.session_state.analysis = apply_cross_checks(st.session_state.analysis)

                try:
                    persisted = persist_mrp_current()
                    if db.configured() and not bool(persisted.get("ok", False)):
                        raise RuntimeError(
                            "O Supabase não confirmou a gravação da carga MRP."
                        )
                except Exception as exc:
                    st.error(
                        "A carga foi validada, mas NÃO foi gravada no Supabase. "
                        f"A prévia foi mantida para nova tentativa. Detalhe: {exc}"
                    )
                    return

                st.session_state.mrp_import_preview_detail = pd.DataFrame()
                st.session_state.mrp_import_preview_summary = pd.DataFrame()
                set_flash(
                    "_flash_mrp",
                    "success",
                    (
                        f"Carga aplicada e gravada: {len(summary)} NF(s) avaliadas, "
                        f"{len(high)} em prioridade ALTA. "
                        f"Supabase: {int(persisted.get('resumo', len(summary)))} NF(s) no resumo atual."
                    ),
                )
                st.rerun()

        elif isinstance(st.session_state.get("mrp_priority_summary"), pd.DataFrame) and not st.session_state.mrp_priority_summary.empty:
            st.success(
                f"Carga MRP atual aplicada: {len(st.session_state.mrp_priority_summary)} NF(s) avaliadas."
            )
        else:
            st.info("Nenhuma carga de impacto MRP confirmada nesta sessão.")

    else:
        summary = st.session_state.get("mrp_priority_summary")
        if not isinstance(summary, pd.DataFrame) or summary.empty:
            st.info(
                "Nenhuma carga de impacto MRP aplicada. "
                "Alimente em Processamento de arquivos → Alimentação."
            )
            return

        st.caption(
            "Acompanhamento da carga aplicada em Processamento de arquivos → Alimentação."
        )

        show = summary.copy()

        # Na visão operacional, prioridade BAIXA não precisa exibir dados de
        # necessidade MRP. Mantemos os valores internos intactos e criamos
        # colunas apenas de exibição para que Streamlit não mostre "None".
        low_mask = show["prioridade"].fillna("").astype(str).str.upper().eq("BAIXA")
        show.loc[low_mask, "ops"] = ""

        show["data_cm_exibicao"] = show["data_cm"].map(
            lambda value: (
                normalized_business_date(value).strftime("%d/%m/%Y")
                if normalized_business_date(value)
                else ""
            )
        )
        show["itens_impacto_exibicao"] = show["itens_impacto"].map(
            lambda value: (
                ""
                if value is None or pd.isna(value)
                else str(int(value))
                if str(value).replace(".", "", 1).isdigit()
                else str(value)
            )
        )

        show.loc[low_mask, "data_cm_exibicao"] = ""
        show.loc[low_mask, "itens_impacto_exibicao"] = ""

        visible_cols = [
            "data_pre_nota",
            "numero_nf",
            "fornecedor",
            "natureza",
            "cr",
            "desc_cr",
            "prioridade",
            "ops",
            "data_cm_exibicao",
            "itens_impacto_exibicao",
            "fornecedor_validacao",
        ]

        st.dataframe(
            show[visible_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "data_pre_nota": st.column_config.DateColumn("Data pré-nota", format="DD/MM/YYYY"),
                "numero_nf": "NF",
                "fornecedor": st.column_config.TextColumn("Fornecedor", width="large"),
                "natureza": st.column_config.TextColumn("Natureza", width="medium"),
                "cr": st.column_config.TextColumn("CR", width="small"),
                "desc_cr": st.column_config.TextColumn("Desc. CR", width="medium"),
                "prioridade": "Prioridade",
                "ops": st.column_config.TextColumn("OPs", width="large"),
                "data_cm_exibicao": st.column_config.TextColumn("Data CM"),
                "itens_impacto_exibicao": st.column_config.TextColumn("Itens impacto"),
                "fornecedor_validacao": st.column_config.TextColumn(
                    "Fornecedor validado",
                    width="large",
                ),
            },
        )

        ignored_records = st.session_state.get("mrp_ignored_records") or []
        if ignored_records:
            with st.expander(
                f"NFs desconsideradas nesta carga ({len(ignored_records)})",
                expanded=False,
            ):
                ignored_df = pd.DataFrame(ignored_records)
                st.dataframe(
                    ignored_df,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "data_pre_nota": st.column_config.DateColumn(
                            "Data",
                            format="DD/MM/YYYY",
                        ),
                        "numero_nf": "NF",
                        "fornecedor": st.column_config.TextColumn(
                            "Fornecedor",
                            width="large",
                        ),
                        "prioridade": "Prioridade anterior",
                        "data_cm": st.column_config.DateColumn(
                            "Data CM",
                            format="DD/MM/YYYY",
                        ),
                        "desconsiderada_em": "Desconsiderada em",
                    },
                )

        pre = st.session_state.pre_notes.copy()
        if isinstance(pre, pd.DataFrame) and not pre.empty:
            comparison_rows = []
            for idx, row in summary.iterrows():
                match = match_mrp_to_pre_note(row, pre)
                comparison_rows.append({
                    "_idx": idx,
                    "situacao_vinculo": match["situacao"],
                    "score_fornecedor": match["score_fornecedor"],
                    "correspondente": bool(match["matched"]),
                })

            comparison = pd.DataFrame(comparison_rows).set_index("_idx")
            checked_summary = summary.join(comparison)
            missing_pre = checked_summary[
                ~checked_summary["correspondente"].fillna(False).astype(bool)
            ].copy()

            if not missing_pre.empty:
                st.warning(
                    f"{len(missing_pre)} NF(s) do Impacto MRP não tiveram correspondência segura "
                    "na lista de pré-notas. O confronto usa Data + NF e valida o nome do fornecedor."
                )
                missing_pre["_mrp_key"] = missing_pre.apply(
                    mrp_row_key,
                    axis=1,
                )

                add_view = missing_pre[
                    [
                        "_mrp_key",
                        "data_pre_nota",
                        "numero_nf",
                        "cnpj",
                        "fornecedor",
                        "prioridade",
                        "data_cm",
                        "situacao_vinculo",
                        "score_fornecedor",
                    ]
                ].copy()
                add_view.insert(0, "Selecionar", False)

                st.caption(
                    "Marque as NFs desejadas e escolha uma única ação para as selecionadas."
                )

                edited = st.data_editor(
                    add_view,
                    use_container_width=True,
                    hide_index=True,
                    disabled=[
                        x for x in add_view.columns if x != "Selecionar"
                    ],
                    key=f"{key_prefix}_missing_pre_editor",
                    column_config={
                        "_mrp_key": None,
                        "Selecionar": st.column_config.CheckboxColumn(
                            "Selecionar",
                            help="Marque as NFs que receberão a ação escolhida abaixo.",
                        ),
                        "data_pre_nota": st.column_config.DateColumn(
                            "Data",
                            format="DD/MM/YYYY",
                        ),
                        "numero_nf": "NF",
                        "cnpj": "CNPJ",
                        "fornecedor": st.column_config.TextColumn(
                            "Fornecedor",
                            width="large",
                        ),
                        "prioridade": "Prioridade",
                        "data_cm": st.column_config.DateColumn(
                            "Data CM",
                            format="DD/MM/YYYY",
                        ),
                        "situacao_vinculo": st.column_config.TextColumn(
                            "Situação do vínculo",
                            width="large",
                        ),
                        "score_fornecedor": st.column_config.NumberColumn(
                            "Aderência fornecedor",
                            format="%d%%",
                        ),
                    },
                )

                selected = edited[
                    edited["Selecionar"].fillna(False).astype(bool)
                ].copy()

                action = st.selectbox(
                    "Ação para as NFs selecionadas",
                    options=[
                        "Escolha uma ação",
                        "Adicionar às Pré-notas pendentes",
                        "Desconsiderar do Impacto MRP",
                    ],
                    key=f"{key_prefix}_missing_pre_action",
                )

                if st.button(
                    "APLICAR AÇÃO NAS SELECIONADAS",
                    type="primary",
                    use_container_width=True,
                    disabled=(
                        selected.empty
                        or action == "Escolha uma ação"
                    ),
                    key=f"{key_prefix}_apply_missing_pre_action",
                ):
                    if action == "Adicionar às Pré-notas pendentes":
                        additions = []
                        for _, row in selected.iterrows():
                            additions.append({
                                "data_pre_nota": normalized_business_date(
                                    row["data_pre_nota"]
                                ),
                                "numero_nf": normalized_nf(row["numero_nf"]),
                                "cnpj": digits_only(row["cnpj"]),
                                "fornecedor": str(
                                    row["fornecedor"] or ""
                                ).strip(),
                                "status": "Pré-nota lançada",
                                "origem": "Impacto MRP / Protheus",
                            })

                        updated = pd.concat(
                            [
                                st.session_state.pre_notes,
                                pd.DataFrame(additions),
                            ],
                            ignore_index=True,
                            sort=False,
                        )
                        updated["_data_nf"] = updated.apply(
                            lambda row: date_nf_key(
                                row.get("data_pre_nota"),
                                row.get("numero_nf"),
                            ),
                            axis=1,
                        )
                        updated["_supplier_norm"] = updated.apply(
                            lambda row: supplier_validation_name(
                                pre_supplier_name(row)
                            ),
                            axis=1,
                        )
                        updated = (
                            updated.sort_index()
                            .drop_duplicates(
                                ["_data_nf", "_supplier_norm"],
                                keep="last",
                            )
                            .drop(
                                columns=[
                                    "_data_nf",
                                    "_supplier_norm",
                                ],
                                errors="ignore",
                            )
                            .reset_index(drop=True)
                        )
                        st.session_state.pre_notes = updated
                        persist_pre_notes_current("Impacto MRP / Protheus")

                        set_flash(
                            "_flash_mrp",
                            "success",
                            (
                                f"{len(additions)} NF(s) adicionada(s) "
                                "à lista de Pré-notas pendentes e gravada(s) no Supabase."
                            ),
                        )
                        st.rerun()

                    if action == "Desconsiderar do Impacto MRP":
                        ignore_keys = set(
                            selected["_mrp_key"]
                            .fillna("")
                            .astype(str)
                            .loc[lambda s: s.ne("")]
                            .tolist()
                        )

                        current_summary = (
                            st.session_state.mrp_priority_summary.copy()
                        )
                        current_summary["_mrp_key"] = (
                            current_summary.apply(
                                mrp_row_key,
                                axis=1,
                            )
                        )

                        ignored_rows = current_summary[
                            current_summary["_mrp_key"].isin(ignore_keys)
                        ].copy()

                        if ignored_rows.empty:
                            st.error(
                                "Nenhuma NF selecionada foi localizada "
                                "na carga atual. Recarregue a página e tente novamente."
                            )
                        else:
                            st.session_state.mrp_priority_summary = (
                                current_summary[
                                    ~current_summary["_mrp_key"].isin(
                                        ignore_keys
                                    )
                                ]
                                .drop(
                                    columns="_mrp_key",
                                    errors="ignore",
                                )
                                .reset_index(drop=True)
                            )

                            current_detail = st.session_state.get(
                                "mrp_impact_detail"
                            )
                            if (
                                isinstance(current_detail, pd.DataFrame)
                                and not current_detail.empty
                            ):
                                current_detail = current_detail.copy()
                                current_detail["_mrp_key"] = (
                                    current_detail.apply(
                                        mrp_row_key,
                                        axis=1,
                                    )
                                )
                                st.session_state.mrp_impact_detail = (
                                    current_detail[
                                        ~current_detail["_mrp_key"].isin(
                                            ignore_keys
                                        )
                                    ]
                                    .drop(
                                        columns="_mrp_key",
                                        errors="ignore",
                                    )
                                    .reset_index(drop=True)
                                )

                            ignored_log = list(
                                st.session_state.get(
                                    "mrp_ignored_records"
                                )
                                or []
                            )
                            for _, row in ignored_rows.iterrows():
                                ignored_log.append({
                                    "data_pre_nota": row.get(
                                        "data_pre_nota"
                                    ),
                                    "numero_nf": normalized_nf(
                                        row.get("numero_nf")
                                    ),
                                    "fornecedor": str(
                                        row.get("fornecedor") or ""
                                    ).strip(),
                                    "prioridade": str(
                                        row.get("prioridade") or ""
                                    ).strip(),
                                    "data_cm": row.get("data_cm"),
                                    "desconsiderada_em": (
                                        now_local().isoformat(
                                            timespec="seconds"
                                        )
                                    ),
                                })
                            st.session_state.mrp_ignored_records = (
                                ignored_log
                            )

                            remaining = (
                                st.session_state.mrp_priority_summary
                            )
                            high = (
                                remaining[
                                    remaining["prioridade"].eq("ALTA")
                                ].copy()
                                if not remaining.empty
                                else pd.DataFrame()
                            )

                            st.session_state.priority_date_nf_keys = set(
                                high.get(
                                    "data_nf",
                                    pd.Series(dtype=str),
                                )
                                .dropna()
                                .astype(str)
                                .tolist()
                            )
                            st.session_state.priority_nf_numbers = set(
                                high.get(
                                    "numero_nf",
                                    pd.Series(dtype=str),
                                )
                                .dropna()
                                .astype(str)
                                .tolist()
                            )
                            st.session_state.priority_nf_doc_keys = set()
                            st.session_state.priority_nf_keys = set()

                            if not st.session_state.analysis.empty:
                                st.session_state.analysis = (
                                    apply_cross_checks(
                                        st.session_state.analysis
                                    )
                                )

                            persist_mrp_current()

                            set_flash(
                                "_flash_mrp",
                                "success",
                                (
                                    f"{len(ignored_rows)} NF(s) "
                                    "desconsiderada(s) da carga atual de Impacto MRP "
                                    "e a base persistida foi atualizada."
                                ),
                            )
                            st.rerun()


def match_document_to_pre_note(
    document_row: pd.Series | dict,
    min_supplier_score: int = 82,
    pre_notes: pd.DataFrame | None = None,
) -> dict:
    frame = (
        pre_notes
        if isinstance(pre_notes, pd.DataFrame)
        else st.session_state.pre_notes
    )
    result = {
        "matched": False,
        "situacao": "PRÉ-NOTA NÃO LOCALIZADA",
        "score_fornecedor": 0,
        "row": None,
    }
    if not isinstance(frame, pd.DataFrame) or frame.empty:
        return result

    nf = normalized_nf(document_row.get("numero_nf"))
    if not nf:
        result["situacao"] = "NF INVÁLIDA"
        return result

    candidates = frame[
        frame["numero_nf"].map(normalized_nf).eq(nf)
    ].copy()
    if candidates.empty:
        return result

    doc_cnpj = digits_only(
        document_row.get("cnpj_fornecedor")
        or document_row.get("cnpj")
    )

    # O CNPJ é o vínculo mais forte quando existe nos dois lados. Isso é
    # especialmente importante para NFs adicionadas pela análise do MRP.
    if doc_cnpj and "cnpj" in candidates.columns:
        candidate_cnpj = candidates["cnpj"].map(digits_only)
        exact_cnpj = candidates[candidate_cnpj.eq(doc_cnpj)].copy()
        if len(exact_cnpj) == 1:
            best = exact_cnpj.iloc[0]
            result.update(
                matched=True,
                situacao="OK",
                score_fornecedor=100,
                row=best.to_dict(),
            )
            return result
        if len(exact_cnpj) > 1:
            candidates = exact_cnpj

    supplier_names = [
        str(document_row.get("fornecedor_padrao") or "").strip(),
        str(document_row.get("fornecedor_lido") or "").strip(),
    ]
    supplier_names = [name for name in supplier_names if name]

    candidates["_supplier_pre"] = candidates.apply(
        pre_supplier_name,
        axis=1,
    )

    if supplier_names:
        candidates["_score_supplier"] = candidates["_supplier_pre"].map(
            lambda pre_name: max(
                [
                    supplier_similarity(pre_name, doc_name)
                    for doc_name in supplier_names
                ]
                or [0]
            )
        )
    else:
        candidates["_score_supplier"] = 0

    candidates = candidates.sort_values(
        "_score_supplier",
        ascending=False,
    )

    best = candidates.iloc[0]
    best_score = int(best["_score_supplier"])

    # Se existe uma única NF com esse número no universo válido e a base não
    # dispõe de CNPJ para confrontar (situação comum de inclusão via MRP),
    # o número da NF é suficiente para o vínculo. A base é a autoridade do fluxo.
    if len(candidates) == 1:
        candidate_cnpj = digits_only(best.get("cnpj"))
        if doc_cnpj and candidate_cnpj and doc_cnpj != candidate_cnpj:
            result["situacao"] = "CNPJ DIVERGENTE"
            result["score_fornecedor"] = best_score
            return result

        if not candidate_cnpj or not doc_cnpj:
            result.update(
                matched=True,
                situacao="OK - NF ÚNICA NA BASE",
                score_fornecedor=max(best_score, 90),
                row=best.to_dict(),
            )
            return result

    if not supplier_names:
        result["situacao"] = "FORNECEDOR DO DOCUMENTO NÃO LOCALIZADO"
        return result

    if best_score < min_supplier_score:
        result["situacao"] = "FORNECEDOR DIVERGENTE"
        result["score_fornecedor"] = best_score
        return result

    strong_candidates = candidates[
        candidates["_score_supplier"] >= min_supplier_score
    ].copy()

    if len(strong_candidates) > 1:
        strong_dates = {
            normalized_business_date(value)
            for value in strong_candidates["data_pre_nota"].tolist()
            if normalized_business_date(value) is not None
        }
        if len(strong_dates) > 1:
            result["situacao"] = "CORRESPONDÊNCIA AMBÍGUA ENTRE DATAS"
            result["score_fornecedor"] = best_score
            return result

    if len(candidates) > 1:
        second = candidates.iloc[1]
        second_score = int(second["_score_supplier"])
        if (
            supplier_validation_name(best.get("_supplier_pre"))
            != supplier_validation_name(second.get("_supplier_pre"))
            and second_score >= min_supplier_score
            and best_score - second_score <= 3
        ):
            result["situacao"] = "CORRESPONDÊNCIA AMBÍGUA"
            result["score_fornecedor"] = best_score
            return result

    result.update(
        matched=True,
        situacao="OK",
        score_fornecedor=best_score,
        row=best.to_dict(),
    )
    return result


def operational_fields_from_nf_load(
    pre_row: pd.Series | dict | None,
    document_row: pd.Series | dict,
    min_supplier_score: int = 82,
) -> dict:
    """Busca Natureza, CR e Desc. CR na carga STSUP01/Impacto MRP."""
    result = {
        "natureza": "",
        "cr": "",
        "desc_cr": "",
        "source": "CARGA DE NFs NÃO DISPONÍVEL",
    }

    detail = st.session_state.get("mrp_impact_detail")
    if not isinstance(detail, pd.DataFrame) or detail.empty:
        return result

    if not pre_row:
        result["source"] = "PRÉ-NOTA NÃO LOCALIZADA"
        return result

    key = date_nf_key(
        pre_row.get("data_pre_nota"),
        document_row.get("numero_nf") or pre_row.get("numero_nf"),
    )
    if not key:
        result["source"] = "DATA/NF INVÁLIDA"
        return result

    candidates = detail[
        detail["data_nf"].fillna("").astype(str).eq(key)
    ].copy()
    if candidates.empty:
        result["source"] = "NF NÃO LOCALIZADA NA CARGA"
        return result

    supplier_names = [
        pre_supplier_name(pre_row),
        str(document_row.get("fornecedor_padrao") or "").strip(),
        str(document_row.get("fornecedor_lido") or "").strip(),
    ]
    supplier_names = [name for name in supplier_names if name]

    if supplier_names and "fornecedor" in candidates.columns:
        candidates["_op_supplier_score"] = candidates["fornecedor"].map(
            lambda value: max(
                [supplier_similarity(value, name) for name in supplier_names] or [0]
            )
        )
        strong = candidates[
            candidates["_op_supplier_score"] >= min_supplier_score
        ].copy()
        if not strong.empty:
            candidates = strong

    def unique_join(column: str) -> str:
        if column not in candidates.columns:
            return ""
        values = (
            candidates[column]
            .fillna("")
            .astype(str)
            .str.strip()
        )
        values = values[
            values.ne("")
            & ~values.str.upper().isin({"NAN", "NONE", "NULL"})
        ]
        return _join_unique(values.tolist())

    result["natureza"] = unique_join("natureza").upper()
    result["cr"] = unique_join("cr")
    result["desc_cr"] = unique_join("desc_cr")
    result["source"] = "CARGA NF"

    if not result["natureza"]:
        result["source"] = "NATUREZA NÃO INFORMADA NA CARGA"

    return result


def nature_from_nf_load(
    pre_row: pd.Series | dict | None,
    document_row: pd.Series | dict,
    min_supplier_score: int = 82,
) -> tuple[str, str]:
    fields = operational_fields_from_nf_load(
        pre_row,
        document_row,
        min_supplier_score=min_supplier_score,
    )
    return fields["natureza"], fields["source"]



def company_sigla_from_document(
    destinatario: object = "",
    cnpj_destinatario: object = "",
    text: object = "",
) -> str:
    """Retorna a sigla operacional SETTA a partir do destinatário do documento."""
    source = normalize_text(
        " ".join(
            value
            for value in [
                str(destinatario or "").strip(),
                str(text or "").strip(),
            ]
            if value
        )
    )

    if any(token in source for token in [
        "ASTEC",
        "ASSISTENCIA TECNICA",
        "ASSISTENCIA TECNICA SETTA",
    ]):
        return "STA"

    if any(token in source for token in [
        "ENGENHARIA",
        "SETTA ENGENHARIA",
    ]):
        return "SEE"

    if any(token in source for token in [
        "ENERGY",
        "SETTA ENERGY",
        "ENERGIA",
    ]):
        return "SEN"

    _ = digits_only(cnpj_destinatario)
    return ""


def company_sigla_from_pdf_text(text: object) -> str:
    """Lê somente a região do destinatário para evitar confundir o emitente."""
    raw = str(text or "")
    normalized = normalize_text(raw)

    start = normalized.find("DESTINATARIO/REMETENTE")
    if start < 0:
        start = normalized.find("DESTINATARIO")

    if start >= 0:
        end_candidates = [
            normalized.find(marker, start + 10)
            for marker in [
                "FATURA",
                "DUPLICATA",
                "CALCULO DO IMPOSTO",
                "TRANSPORTADOR",
                "DADOS DOS PRODUTOS",
            ]
        ]
        end_candidates = [value for value in end_candidates if value > start]
        end = min(end_candidates) if end_candidates else min(len(raw), start + 2500)
        scope = raw[start:end]
    else:
        scope = raw[:3500]

    return company_sigla_from_document(text=scope)


def nf_package_class(natureza: object) -> str:
    """MP somente para matéria-prima; todas as demais naturezas seguem como UC."""
    value = normalize_text(natureza)
    return "MP" if "MATERIA PRIMA" in value else "UC"


def apply_cross_checks(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()
    mrp_summary = st.session_state.get("mrp_priority_summary")
    if not isinstance(mrp_summary, pd.DataFrame):
        mrp_summary = pd.DataFrame()

    priority_flags = []
    priority_base_flags = []
    priority_manual_flags = []
    pre_status = []
    pre_dates = []
    pre_link_status = []
    pre_supplier_scores = []
    resolved_natures = []
    nature_sources = []
    resolved_crs = []
    resolved_desc_crs = []

    for _, row in out.iterrows():
        pre_match = match_document_to_pre_note(row)
        pre_row = pre_match.get("row") if pre_match.get("matched") else None

        if pre_row:
            mrp_match = match_pre_note_to_mrp(pre_row, mrp_summary)
        else:
            mrp_match = {
                "matched": False,
                "situacao": pre_match.get("situacao") or "PRÉ-NOTA NÃO LOCALIZADA",
                "score_fornecedor": pre_match.get("score_fornecedor") or 0,
                "row": None,
            }

        mrp_row = mrp_match.get("row") if mrp_match.get("matched") else None
        priority_base = bool(
            mrp_row
            and str(mrp_row.get("prioridade") or "").upper() == "ALTA"
        )
        priority_manual = bool(row.get("prioridade_manual", False))
        priority = bool(priority_base or priority_manual)

        current_nature = str(row.get("natureza") or "").strip().upper()
        nature_source = str(row.get("natureza_origem") or "").strip()
        current_cr = str(row.get("cr") or "").strip()
        current_desc_cr = str(row.get("desc_cr") or "").strip()

        operational = operational_fields_from_nf_load(
            pre_row,
            row,
        )
        if operational.get("natureza") and not current_nature:
            current_nature = str(operational["natureza"]).strip().upper()
            nature_source = str(operational.get("source") or "CARGA NF")
        if operational.get("cr"):
            current_cr = str(operational["cr"]).strip()
        if operational.get("desc_cr"):
            current_desc_cr = str(operational["desc_cr"]).strip()

        priority_flags.append(priority)
        priority_base_flags.append(priority_base)
        priority_manual_flags.append(priority_manual)
        pre_status.append(str(pre_row.get("status") or "") if pre_row else "")
        pre_dates.append(pre_row.get("data_pre_nota") if pre_row else None)
        pre_link_status.append(str(mrp_match.get("situacao") or ""))
        pre_supplier_scores.append(
            int(
                mrp_match.get("score_fornecedor")
                or pre_match.get("score_fornecedor")
                or 0
            )
        )
        resolved_natures.append(current_nature)
        nature_sources.append(nature_source)
        resolved_crs.append(current_cr)
        resolved_desc_crs.append(current_desc_cr)

    out["prioridade_mrp"] = priority_flags
    out["prioridade_mrp_base"] = priority_base_flags
    out["prioridade_manual"] = priority_manual_flags
    out["pre_nota_status"] = pre_status
    out["pre_nota_em"] = pre_dates
    out["vinculo_mrp_status"] = pre_link_status
    out["vinculo_fornecedor_score"] = pre_supplier_scores
    out["natureza"] = resolved_natures
    out["natureza_origem"] = nature_sources
    out["cr"] = resolved_crs
    out["desc_cr"] = resolved_desc_crs
    return out


def make_zip_outputs(df: pd.DataFrame):
    outputs: dict[str, bytes] = {}
    manifest: list[dict] = []
    batch = f"NF-{now_local():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:5].upper()}"
    operator = str(st.session_state.operator or "").strip()
    processed_at = now_local().isoformat(timespec="seconds")
    date_label = now_local().strftime("%d.%m")

    work = df.copy()
    work["empresa_sigla"] = (
        work.get("empresa_sigla", pd.Series("", index=work.index))
        .fillna("")
        .astype(str)
        .str.upper()
        .str.strip()
    )
    work["pacote"] = work["natureza"].map(nf_package_class)

    invalid_company = work[
        ~work["empresa_sigla"].isin({"SEN", "SEE", "STA"})
    ].copy()
    if not invalid_company.empty:
        nfs = ", ".join(
            invalid_company["numero_nf"]
            .fillna("")
            .astype(str)
            .tolist()
        )
        raise ValueError(
            "Não foi possível identificar a empresa destinatária "
            f"(SEN/SEE/STA) para: {nfs}."
        )

    # NF-e: um ZIP por empresa e classe MP/UC.
    for (company, package), group in work.groupby(
        ["empresa_sigla", "pacote"],
        dropna=False,
        sort=True,
    ):
        buffer = io.BytesIO()
        used_paths = set()

        with zipfile.ZipFile(
            buffer,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            if package == "MP":
                # Mantém a estrutura fixa solicitada, mesmo que uma pasta fique vazia.
                archive.writestr("URGENTES/", b"")
                archive.writestr("NORMAIS/", b"")

            for _, row in group.iterrows():
                item = st.session_state.pdfs.get(str(row.file_id))
                final_name = str(row.nome_sugerido or "").strip()
                nature = str(row.get("natureza") or "").strip().upper()

                if not item:
                    raise ValueError(
                        f"PDF original indisponível: {row.arquivo_original}"
                    )
                if not final_name:
                    raise ValueError(
                        f"Nome final vazio para a NF {row.numero_nf}."
                    )

                if package == "MP":
                    folder = (
                        "URGENTES"
                        if bool(row.get("prioridade_mrp"))
                        else "NORMAIS"
                    )
                    archive_path = f"{folder}/{final_name}"
                else:
                    archive_path = final_name

                if archive_path in used_paths:
                    raise ValueError(
                        f"Nome final duplicado no pacote: {archive_path}"
                    )
                used_paths.add(archive_path)

                data_chegada = (
                    normalized_business_date(row.get("pre_nota_em"))
                    or normalized_business_date(row.get("pre_nota_data"))
                )
                recebedor = str(
                    row.get("pre_nota_recebedor")
                    or row.get("recebedor")
                    or ""
                ).strip()
                cr = str(row.get("cr") or "").strip()
                desc_cr = str(row.get("desc_cr") or "").strip()

                final_pdf_bytes = item["bytes"]
                try:
                    final_pdf_bytes = apply_operational_stamp(
                        final_pdf_bytes,
                        data_chegada=data_chegada,
                        cr=cr,
                        desc_cr=desc_cr,
                        natureza=nature,
                        recebido_por=recebedor,
                    )
                    stamp_applied = True
                except Exception as exc:
                    raise ValueError(
                        f"Falha ao aplicar o controle interno na NF "
                        f"{row.numero_nf}: {exc}"
                    ) from exc

                archive.writestr(
                    archive_path,
                    final_pdf_bytes,
                )

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
                        "vencimento": (
                            row.vencimento.isoformat()
                            if isinstance(row.vencimento, date)
                            else None
                        ),
                        "natureza": nature,
                        "prioridade_mrp": bool(
                            row.get("prioridade_mrp")
                        ),
                        "pre_nota_status": str(
                            row.get("pre_nota_status") or ""
                        ),
                        "pre_nota_em": (
                            str(row.get("pre_nota_em") or "") or None
                        ),
                        "metodo_fornecedor": str(
                            row.metodo_fornecedor
                        ),
                        "confianca": int(row.confianca),
                        "status": "REALIZADO",
                        "operador": operator or None,
                        "recebido_em": processed_at,
                        "pdf_criado_em": processed_at,
                        "processado_em": processed_at,
                        "cr": cr or None,
                        "desc_cr": desc_cr or None,
                        "recebedor": recebedor or None,
                        "origem_dados": (
                            str(row.get("origem_dados") or "").strip()
                            or None
                        ),
                        "data_chegada": (
                            data_chegada.isoformat()
                            if data_chegada
                            else None
                        ),
                        "carimbo_aplicado": stamp_applied,
                        "empresa_sigla": str(
                            row.get("empresa_sigla") or ""
                        ).upper().strip() or None,
                    }
                )

        zip_name = (
            f"NF´s - {date_label} - {package} - {company}.zip"
        )
        outputs[zip_name] = buffer.getvalue()

    # CT-e: um único ZIP por empresa, independentemente de MP/UC/prioridade.
    file_company = {
        str(row.get("file_id") or ""): str(
            row.get("empresa_sigla") or ""
        ).upper().strip()
        for _, row in work.iterrows()
        if str(row.get("file_id") or "").strip()
    }

    ctes_by_company: dict[str, list[dict]] = {
        "SEN": [],
        "SEE": [],
        "STA": [],
    }

    for cte in st.session_state.get("cte_links") or []:
        linked_ids = {
            str(value)
            for value in (cte.get("linked_file_ids") or [])
            if str(value).strip()
        }
        companies = {
            file_company.get(file_id, "")
            for file_id in linked_ids
        }
        companies = {
            company
            for company in companies
            if company in {"SEN", "SEE", "STA"}
        }

        for company in companies:
            ctes_by_company[company].append(cte)

    cte_manifested = set()
    for company, ctes in ctes_by_company.items():
        if not ctes:
            continue

        buffer = io.BytesIO()
        used = set()
        with zipfile.ZipFile(
            buffer,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as archive:
            for cte in ctes:
                cte_name = str(
                    cte.get("arquivo_final")
                    or cte.get("arquivo_original")
                    or ""
                ).strip()
                cte_bytes = cte.get("bytes")

                if not cte_name or not cte_bytes:
                    raise ValueError(
                        f"CT-e {cte.get('numero_cte') or ''} "
                        "vinculado sem arquivo disponível."
                    )

                if cte_name in used:
                    continue
                used.add(cte_name)
                archive.writestr(cte_name, cte_bytes)

                cte_key = (
                    str(cte.get("chave_cte") or "").strip()
                    or str(cte.get("cte_id") or "").strip()
                    or cte_name
                )
                if cte_key not in cte_manifested:
                    cte_manifested.add(cte_key)
                    manifest.append(
                        {
                            "lote_id": batch,
                            "arquivo_original": str(
                                cte.get("arquivo_original") or ""
                            ),
                            "arquivo_final": cte_name,
                            "tipo_documento": "CT-e",
                            "numero_cte": str(
                                cte.get("numero_cte") or ""
                            ),
                            "chave_cte": str(
                                cte.get("chave_cte") or ""
                            ),
                            "nfs_vinculadas": ", ".join(
                                [
                                    normalized_nf(value)
                                    for value in (
                                        cte.get("linked_nf_numbers") or []
                                    )
                                    if normalized_nf(value)
                                ]
                            ),
                            "transportadora": str(
                                cte.get("transportadora") or ""
                            ),
                            "cnpj_transportadora": str(
                                cte.get("cnpj_transportadora") or ""
                            ),
                            "empresa_sigla": company,
                            "status": "REALIZADO",
                            "operador": operator or None,
                            "recebido_em": processed_at,
                            "pdf_criado_em": processed_at,
                            "processado_em": processed_at,
                            "origem_dados": str(
                                cte.get("origem") or "CT-e"
                            ),
                            "carimbo_aplicado": False,
                            "prioridade_mrp": False,
                        }
                    )

        zip_name = f"CTE´s - {date_label} - {company}.zip"
        outputs[zip_name] = buffer.getvalue()

    return outputs, manifest


def save_config_or_session(new_cfg: dict) -> tuple[bool, str]:
    new_cfg = dict(new_cfg)
    new_cfg.pop("naturezas", None)
    st.session_state.cfg = new_cfg
    if not db.configured():
        return False, "Configuração aplicada somente nesta sessão: SUPABASE_ANON_KEY ainda não está configurada neste app."
    db.save_config(new_cfg)
    st.session_state.db_synced = True
    return True, "Configuração salva no Supabase."


def current_process_records_for_tests() -> pd.DataFrame:
    """Retorna somente processamentos que concluíram o fluxo operacional."""
    if not SAVE_NF_HISTORY:
        return pd.DataFrame(st.session_state.get("current_test_manifest") or [])

    if db.configured():
        try:
            frame = pd.DataFrame(db.list_process_records())
        except Exception:
            frame = pd.DataFrame(st.session_state.history)
    else:
        frame = pd.DataFrame(st.session_state.history)

    if frame.empty or "status" not in frame.columns:
        return frame

    completed = {
        "REALIZADO",
        "ENVIADO",
        "PDF CRIADO",
    }
    return frame[
        frame["status"]
        .fillna("")
        .astype(str)
        .str.upper()
        .isin(completed)
    ].copy()


def persist_pre_notes_current(source_name: str = "app") -> dict:
    frame = st.session_state.pre_notes
    if not SAVE_NF_HISTORY or not db.configured():
        return {"registros": len(frame) if isinstance(frame, pd.DataFrame) else 0}

    rows = []
    if isinstance(frame, pd.DataFrame) and not frame.empty:
        for _, row in frame.iterrows():
            data_pre = normalized_business_date(row.get("data_pre_nota"))
            rows.append({
                "numero_nf": normalized_nf(row.get("numero_nf")),
                "cnpj": digits_only(row.get("cnpj")),
                "fornecedor": str(row.get("fornecedor") or "").strip(),
                "recebedor": str(row.get("recebedor") or "").strip(),
                "status": str(row.get("status") or "").strip(),
                "data_pre_nota": data_pre.isoformat() if data_pre else None,
                "natureza": str(row.get("natureza") or "").strip(),
            })
    return db.replace_pre_notes(rows, source_name)


def persist_mrp_current() -> dict:
    detail = st.session_state.get("mrp_impact_detail")
    summary = st.session_state.get("mrp_priority_summary")
    if not SAVE_NF_HISTORY or not db.configured():
        return {
            "detalhe": len(detail) if isinstance(detail, pd.DataFrame) else 0,
            "resumo": len(summary) if isinstance(summary, pd.DataFrame) else 0,
        }

    return db.save_mrp_load(
        dataframe_records_for_db(detail if isinstance(detail, pd.DataFrame) else pd.DataFrame()),
        dataframe_records_for_db(summary if isinstance(summary, pd.DataFrame) else pd.DataFrame()),
        list(st.session_state.get("mrp_priority_files") or []),
        st.session_state.get("mrp_priority_stats") or {},
    )


def current_pending_pre_notes() -> pd.DataFrame:
    """Retorna exatamente a base ainda pendente na tela de Pré-notas pendentes."""
    base = st.session_state.pre_notes
    if not isinstance(base, pd.DataFrame) or base.empty:
        return pd.DataFrame()

    pending = base.copy()
    processed = current_process_records_for_tests()

    processed_pairs: list[tuple[str, str]] = []
    legacy_processed_keys = set()

    if isinstance(processed, pd.DataFrame) and not processed.empty:
        for _, row in processed.iterrows():
            data_nf = date_nf_key(
                row.get("pre_nota_em"),
                row.get("numero_nf"),
            )
            supplier = str(row.get("fornecedor_padrao") or "").strip()
            if data_nf and supplier:
                processed_pairs.append((data_nf, supplier))

            # Compatibilidade apenas com lotes antigos da sessão.
            legacy_key = pre_note_key(
                row.get("numero_nf"),
                row.get("cnpj_fornecedor"),
            )
            if legacy_key:
                legacy_processed_keys.add(legacy_key)

    def already_processed(row) -> bool:
        pre_data_nf = date_nf_key(
            row.get("data_pre_nota"),
            row.get("numero_nf"),
        )
        pre_supplier = pre_supplier_name(row)

        if pre_data_nf and pre_supplier:
            for processed_data_nf, processed_supplier in processed_pairs:
                if (
                    processed_data_nf == pre_data_nf
                    and supplier_similarity(pre_supplier, processed_supplier) >= 82
                ):
                    return True

        legacy_key = pre_note_key(
            row.get("numero_nf"),
            row.get("cnpj"),
        )
        return bool(legacy_key and legacy_key in legacy_processed_keys)

    processed_mask = pending.apply(already_processed, axis=1)
    return pending[~processed_mask].copy().reset_index(drop=True)


def pending_document_group_key(pre_row: pd.Series | dict) -> str:
    base = date_nf_key(pre_row.get("data_pre_nota"), pre_row.get("numero_nf"))
    supplier = supplier_validation_name(pre_supplier_name(pre_row))
    cnpj = digits_only(pre_row.get("cnpj"))
    return f"{base}|{supplier or cnpj}" if base else ""


def _xml_prefilter_identity(xml_data: dict) -> dict:
    supplier_read = str(xml_data.get("fornecedor_lido") or "").strip()
    supplier_match = match_supplier(
        str(xml_data.get("cnpj_fornecedor") or ""),
        supplier_read,
        st.session_state.suppliers,
    )
    supplier_standard = str(
        supplier_match.get("nome_padrao") or supplier_read
    ).strip()
    return {
        "numero_nf": normalized_nf(xml_data.get("numero_nf")),
        "cnpj_fornecedor": str(xml_data.get("cnpj_fornecedor") or ""),
        "fornecedor_lido": supplier_read,
        "fornecedor_padrao": supplier_standard,
    }


def _build_hybrid_nf_document(group: dict) -> tuple[dict, dict]:
    """Monta uma única NF processada usando XML, PDF ou a combinação dos dois."""
    pre_row = group["pre"]
    xml_item = group["xmls"][0] if group.get("xmls") else None
    pdf_item = group["pdfs"][0] if group.get("pdfs") else None

    pdf_result = None
    if pdf_item:
        pdf_result = process_nf_pdf(
            pdf_item["name"],
            pdf_item["raw"],
            st.session_state.suppliers,
            ocr_fallback=True,
        )

    if pdf_result is not None:
        # O PDF pode complementar leitura/validação, mas nunca prevalece como
        # arquivo-base quando também existe XML.
        row = pdf_result.to_dict()
        # Natureza interna não é aceita do PDF/carimbo antigo. Ela será
        # preenchida exclusivamente pela carga de Nota Fiscal (STSUP01).
        row["natureza"] = ""
        row["natureza_origem"] = ""
    elif xml_item is not None:
        row = {
            "file_id": uuid.uuid4().hex[:16],
            "arquivo_original": xml_item["name"],
            "tipo": "NF-e",
            "chave_nfe": "",
            "numero_nf": "",
            "serie": "",
            "cnpj_fornecedor": "",
            "fornecedor_lido": "",
            "fornecedor_padrao": "",
            "vencimento": None,
            "natureza": "",
            "metodo_fornecedor": "",
            "confianca": 0,
            "leitura": "XML",
            "status": "REVISAR",
            "nome_sugerido": "",
            "observacao": "",
        }
    else:
        raise ValueError("O PDF não pôde ser interpretado e não há XML correspondente.")

    # Regra de precedência do documento visual:
    # XML presente -> DANFE reconstruída exclusivamente do XML.
    # Sem XML -> preserva o PDF recebido como base.
    if xml_item is not None:
        output_bytes = generate_danfe_pdf(xml_item["raw"])
        source_name = xml_item["name"]
    else:
        output_bytes = pdf_item["raw"]
        source_name = pdf_item["name"]

    notes = []
    source_mode = "PDF"

    if xml_item:
        xml_data = xml_item["data"]
        source_mode = "XML + PDF" if pdf_item else "XML"

        supplier_read = str(xml_data.get("fornecedor_lido") or "").strip()
        supplier_match = match_supplier(
            str(xml_data.get("cnpj_fornecedor") or ""),
            supplier_read,
            st.session_state.suppliers,
        )
        pre_supplier = pre_supplier_name(pre_row)
        supplier_standard = str(
            supplier_match.get("nome_padrao")
            or standard_supplier_name(pre_supplier)
            or supplier_read
        ).strip()

        row["numero_nf"] = normalized_nf(xml_data.get("numero_nf"))
        row["serie"] = str(xml_data.get("serie") or "").strip()
        row["chave_nfe"] = str(xml_data.get("chave_nfe") or "").strip()
        row["cnpj_fornecedor"] = str(xml_data.get("cnpj_fornecedor") or "").strip()
        row["fornecedor_lido"] = supplier_read
        row["fornecedor_padrao"] = supplier_standard
        row["destinatario"] = str(xml_data.get("destinatario") or "").strip()
        row["cnpj_destinatario"] = digits_only(
            xml_data.get("cnpj_destinatario")
        )
        row["empresa_sigla"] = company_sigla_from_document(
            row["destinatario"],
            row["cnpj_destinatario"],
        )
        row["metodo_fornecedor"] = (
            f"XML + {supplier_match.get('metodo') or 'fornecedor validado'}"
        )
        row["confianca"] = max(int(row.get("confianca") or 0), 98)

        xml_due = xml_data.get("vencimento")
        if xml_due:
            row["vencimento"] = xml_due
            notes.append("Vencimento obtido das duplicatas do XML.")
        elif pdf_result is not None and row.get("vencimento"):
            notes.append("Vencimento mantido da leitura do PDF.")

        natureza_fiscal = str(xml_data.get("natureza_fiscal") or "").strip()
        if natureza_fiscal:
            notes.append(
                f"Natureza fiscal do XML: {natureza_fiscal}. "
                "Ela não substitui a natureza interna operacional."
            )

        status_code = str(xml_data.get("status_codigo") or "").strip()
        row["xml_status_codigo"] = status_code
        if status_code == "100":
            notes.append("Identidade fiscal confirmada pelo XML autorizado.")
        elif status_code:
            notes.append(
                f"XML com status {status_code} - {xml_data.get('status_motivo') or ''}."
            )
        else:
            notes.append("XML sem protocolo de autorização identificado.")

        if pdf_item:
            row["arquivo_original"] = f"{pdf_item['name']} + {xml_item['name']}"
        else:
            row["arquivo_original"] = xml_item["name"]

    if not str(row.get("empresa_sigla") or "").strip() and pdf_item is not None:
        try:
            pdf_text, _ = extract_pdf_text(
                pdf_item["raw"],
                ocr_fallback=False,
            )
        except Exception:
            pdf_text = ""
        row["empresa_sigla"] = company_sigla_from_pdf_text(
            pdf_text,
        )

    row["origem_dados"] = source_mode
    row["pre_nota_data"] = normalized_business_date(pre_row.get("data_pre_nota"))
    row["pre_nota_recebedor"] = str(pre_row.get("recebedor") or "").strip()
    row["pre_nota_fornecedor"] = pre_supplier_name(pre_row)
    row["pre_nota_cnpj"] = digits_only(pre_row.get("cnpj"))
    row["leitura"] = source_mode

    # Natureza, CR e Desc. CR vêm da própria carga STSUP01 usada no Impacto MRP.
    # Esses são exatamente os campos que antes compunham o carimbo manual.
    operational = operational_fields_from_nf_load(pre_row, row)
    if operational.get("natureza"):
        row["natureza"] = str(operational["natureza"]).strip().upper()
        row["natureza_origem"] = str(operational.get("source") or "CARGA NF")
    row["cr"] = str(operational.get("cr") or "").strip()
    row["desc_cr"] = str(operational.get("desc_cr") or "").strip()

    # O carimbo é aplicado somente na geração final dos arquivos, depois
    # das tratativas. Assim qualquer correção de Natureza/CR/Desc. CR é
    # refletida no PDF que efetivamente sai no ZIP.
    notes.append(
        "Dados do carimbo operacional preparados a partir da carga de NFs."
    )
    row["observacao"] = " ".join(
        value
        for value in [
            str(row.get("observacao") or "").strip(),
            *notes,
        ]
        if value
    ).strip()

    required = bool(
        normalized_nf(row.get("numero_nf"))
        and valid_cnpj(digits_only(row.get("cnpj_fornecedor")))
        and str(row.get("fornecedor_padrao") or "").strip()
        and row.get("vencimento")
        and str(row.get("natureza") or "").strip()
    )
    if required and xml_item and str(xml_item["data"].get("status_codigo") or "") == "100":
        row["status"] = "APROVADO"

    row["nome_sugerido"] = build_final_name(
        row.get("vencimento"),
        row.get("numero_nf"),
        row.get("fornecedor_padrao"),
    )

    # ID próprio do registro final para evitar colisão quando PDF + XML são combinados.
    row["file_id"] = uuid.uuid4().hex[:16]

    stored = {
        "name": source_name,
        "bytes": output_bytes,
        "origem": source_mode,
    }
    return row, stored



def render_mrp_background_feed() -> None:
    """Alimenta o cálculo de impacto MRP sem expor a grade técnica ao operador."""
    show_flash("_flash_mrp")
    st.markdown("### Relatórios para cálculo de impacto MRP")
    st.caption(
        "O resultado é usado automaticamente na priorização das NFs. "
        "A tabela técnica de Impacto MRP não é exibida no fluxo operacional."
    )

    material_file = st.file_uploader(
        "Relatório de Materiais",
        type=["xlsx", "xltx", "xls", "csv"],
        key="process_feed_mrp_materials",
    )
    nf_file = st.file_uploader(
        "Relatório de NFs / STSUP01",
        type=["xlsx", "xltx", "xls", "csv"],
        key="process_feed_mrp_entries",
    )

    if st.button(
        "PROCESSAR RELATÓRIOS MRP",
        type="primary",
        use_container_width=True,
        disabled=not bool(material_file and nf_file),
        key="process_feed_mrp_process",
    ):
        try:
            with st.spinner("Calculando impacto MRP e atualizando prioridades..."):
                materials, mat_stats = _clean_mrp_materials_cached(
                    material_file.getvalue(),
                    material_file.name,
                )
                entries, nf_stats = _clean_mrp_nf_cached(
                    nf_file.getvalue(),
                    nf_file.name,
                    now_local().date().isoformat(),
                )
                detail, summary, impact_stats = _build_mrp_impact(materials, entries)

                st.session_state.mrp_impact_detail = detail.copy()
                st.session_state.mrp_priority_summary = summary.copy()
                st.session_state.mrp_priority_stats = {
                    **mat_stats,
                    **nf_stats,
                    **impact_stats,
                }
                st.session_state.mrp_priority_files = (
                    material_file.name,
                    nf_file.name,
                )
                st.session_state.mrp_ignored_records = []

                high = (
                    summary[summary["prioridade"].eq("ALTA")].copy()
                    if isinstance(summary, pd.DataFrame) and not summary.empty
                    else pd.DataFrame()
                )
                st.session_state.priority_date_nf_keys = set(
                    high.get("data_nf", pd.Series(dtype=str)).dropna().astype(str).tolist()
                )
                st.session_state.priority_nf_doc_keys = set()
                st.session_state.priority_nf_keys = set()
                st.session_state.priority_nf_numbers = set(
                    high.get("numero_nf", pd.Series(dtype=str)).dropna().astype(str).tolist()
                )

                if not st.session_state.analysis.empty:
                    st.session_state.analysis = apply_cross_checks(
                        st.session_state.analysis
                    )

                persisted = persist_mrp_current()
                if db.configured() and not bool(persisted.get("ok", False)):
                    raise RuntimeError("O Supabase não confirmou a gravação da carga MRP.")

            set_flash(
                "_flash_mrp",
                "success",
                (
                    f"Cálculo MRP atualizado: {len(summary)} NF(s) avaliadas; "
                    f"{len(high)} com prioridade ALTA."
                ),
            )
            st.rerun()
        except Exception as exc:
            st.error(f"Falha ao calcular impacto MRP: {exc}")

    summary = st.session_state.get("mrp_priority_summary")
    if isinstance(summary, pd.DataFrame) and not summary.empty:
        high_count = int(
            summary["prioridade"].fillna("").astype(str).str.upper().eq("ALTA").sum()
        )
        st.success(
            f"Impacto MRP carregado: {len(summary)} NF(s) avaliadas, "
            f"{high_count} prioridade(s) ALTA."
        )
    else:
        st.info("Nenhum cálculo MRP carregado.")


def render_pre_notes_feed() -> None:
    show_flash("_flash_pre")
    st.markdown("### Validação de pré-notas")
    show_last_update("pre")
    st.write(
        "Formato validado: A = Data, B = Recebedor, C = Número da NF, D = Fornecedor, E = CNPJ e F = Status. "
        "Somente registros com status **Pré-nota lançada** entram na base. "
        "Carregue o arquivo, valide a prévia e confirme a carga."
    )

    upload = st.file_uploader(
        "Relatório de pré-notas",
        type=["csv", "xlsx", "xls", "xlt", "xltx"],
        key="prenota_file",
    )

    if upload:
        st.caption(
            f"Arquivo selecionado: {upload.name} — {len(upload.getvalue()) / 1024 / 1024:.1f} MB"
        )
        validate_pre = st.button(
            "VALIDAR RELATÓRIO DE PRÉ-NOTAS",
            type="primary",
            use_container_width=True,
            key="validate_pre_import",
        )

        if validate_pre:
            try:
                with st.spinner("Lendo e validando pré-notas..."):
                    temp, sheets = read_uploaded_table(upload, header_row=None)
                    if temp.shape[1] < 6:
                        raise ValueError("O relatório precisa ter pelo menos as colunas A até F.")

                    normalized = pd.DataFrame({
                        "data_pre_nota": pd.to_datetime(
                            temp.iloc[:, 0], errors="coerce", dayfirst=True
                        ).dt.date,
                        "recebedor": temp.iloc[:, 1].fillna("").astype(str).str.strip(),
                        "numero_nf": temp.iloc[:, 2].map(normalized_nf),
                        "fornecedor": temp.iloc[:, 3].fillna("").astype(str).str.strip(),
                        "cnpj": temp.iloc[:, 4].map(digits_only),
                        "status": temp.iloc[:, 5].fillna("").astype(str).str.strip(),
                    })
                    normalized["status_normalizado"] = normalized["status"].map(normalize_text)

                    only_pre = normalized[
                        normalized["status_normalizado"].eq("PRE-NOTA LANCADA")
                    ].copy()
                    only_pre["cnpj_valido"] = only_pre["cnpj"].map(valid_cnpj)
                    only_pre["fornecedor_valido"] = (
                        only_pre["fornecedor"].fillna("").astype(str).str.strip().ne("")
                    )
                    only_pre["data_valida"] = only_pre["data_pre_nota"].notna()

                    invalid_count = int(
                        (
                            only_pre["numero_nf"].eq("")
                            | ~only_pre["fornecedor_valido"]
                            | ~only_pre["data_valida"]
                        ).sum()
                    )

                    preview = only_pre[
                        only_pre["numero_nf"].ne("")
                        & only_pre["fornecedor_valido"]
                        & only_pre["data_valida"]
                    ].copy()
                    preview = (
                        preview.sort_values(
                            ["data_pre_nota", "numero_nf"],
                            ascending=[False, True],
                            na_position="last",
                        )
                        .drop_duplicates(
                            ["data_pre_nota", "numero_nf", "fornecedor"],
                            keep="last",
                        )
                        .drop(
                            columns=[
                                "status_normalizado",
                                "cnpj_valido",
                                "fornecedor_valido",
                                "data_valida",
                            ],
                            errors="ignore",
                        )
                        .reset_index(drop=True)
                    )

                    st.session_state.pre_import_preview = preview
                    st.session_state.pre_import_invalid_count = invalid_count
                    st.session_state.pre_import_name = upload.name

                set_flash(
                    "_flash_pre",
                    "success" if not preview.empty else "warning",
                    (
                        f"Relatório validado: {len(preview)} pré-nota(s) válida(s). "
                        f"Confira a tabela abaixo antes de confirmar a carga."
                        if not preview.empty
                        else "Relatório processado, mas nenhuma Pré-nota lançada válida foi encontrada."
                    ),
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Falha ao interpretar relatório: {exc}")

    preview = st.session_state.get("pre_import_preview")
    invalid_count = int(st.session_state.get("pre_import_invalid_count") or 0)
    preview_name = str(st.session_state.get("pre_import_name") or "")

    if isinstance(preview, pd.DataFrame) and not preview.empty:
        st.markdown(f"#### Conferência da carga — {preview_name}")
        if invalid_count:
            st.warning(
                f"{invalid_count} registro(s) sem Data, NF ou Fornecedor válido foram ignorados na validação."
            )

        st.dataframe(
            preview,
            use_container_width=True,
            hide_index=True,
            column_config={
                "data_pre_nota": st.column_config.DateColumn(
                    "Data", format="DD/MM/YYYY"
                ),
                "numero_nf": "NF",
                "recebedor": st.column_config.TextColumn("Recebedor", width="medium"),
                "cnpj": "CNPJ",
                "fornecedor": st.column_config.TextColumn("Fornecedor", width="large"),
                "status": "Status",
            },
        )

        if st.button(
            "CONFIRMAR E APLICAR CARGA",
            type="primary",
            use_container_width=True,
            key="replace_pre_import",
        ):
            try:
                st.session_state.pre_notes = preview.copy()

                if SAVE_NF_HISTORY and db.configured():
                    rows = []
                    for _, row in preview.iterrows():
                        rows.append({
                            "numero_nf": row["numero_nf"],
                            "cnpj": row["cnpj"],
                            "fornecedor": str(row.get("fornecedor") or "").strip(),
                            "recebedor": str(row.get("recebedor") or "").strip(),
                            "status": row["status"],
                            "data_pre_nota": (
                                row["data_pre_nota"].isoformat()
                                if isinstance(row["data_pre_nota"], date)
                                else None
                            ),
                            "natureza": "",
                        })
                    result = db.replace_pre_notes(rows, preview_name or "relatorio")
                    message = (
                        f"Carga confirmada: "
                        f"{int(result.get('registros', len(rows)))} registro(s) gravado(s)."
                    )
                elif not SAVE_NF_HISTORY:
                    message = (
                        f"Carga confirmada para testes: {len(preview)} registro(s) aplicados "
                        "somente nesta sessão. Nada foi gravado no Supabase."
                    )
                else:
                    message = f"Carga confirmada: {len(preview)} registro(s) aplicados nesta sessão."

                if not st.session_state.analysis.empty:
                    st.session_state.analysis = apply_cross_checks(
                        st.session_state.analysis
                    )

                set_flash("_flash_pre", "success", message)
                # Limpa somente a prévia para o menu voltar ao estado enxuto.
                st.session_state.pre_import_preview = pd.DataFrame()
                st.session_state.pre_import_invalid_count = 0
                st.session_state.pre_import_name = ""
                st.rerun()
            except Exception as exc:
                st.error(f"Falha ao aplicar base de pré-notas: {exc}")

    elif not st.session_state.pre_notes.empty:
        st.success(
            f"Carga atual confirmada: {len(st.session_state.pre_notes)} pré-nota(s). "
            "A base está disponível para análise e comparação nesta mesma área."
        )
    else:
        st.info("Nenhuma carga de pré-notas confirmada nesta sessão.")



def render_suppliers_feed() -> None:
    show_flash("_flash_supplier")
    st.markdown("### Base de fornecedores")
    show_last_update("suppliers")
    st.write(
        "Formato validado: A = Código, B = Loja, C = Razão Social, "
        "D = Nome Fantasia, K = Tipo e O = CNPJ/CPF. "
        "A leitura só começa ao clicar em **Validar base de fornecedores**."
    )

    current = supplier_dataframe(st.session_state.suppliers)
    c1, c2, c3 = st.columns(3)
    c1.metric("Fornecedores atuais", len(current))
    c2.metric(
        "CNPJs válidos",
        int(current["cnpj"].map(valid_cnpj).sum())
        if not current.empty else 0,
    )
    c3.metric(
        "Origem",
        "Supabase"
        if db.configured() and st.session_state.db_synced
        else "Sessão/local",
    )

    upload = st.file_uploader(
        "Relatório FORNECEDORES",
        type=["csv", "xlsx", "xls", "xlt", "xltx"],
        key="supplier_import",
    )

    if upload:
        st.caption(
            f"Arquivo selecionado: {upload.name} — {len(upload.getvalue()) / 1024 / 1024:.1f} MB"
        )
        validate_supplier = st.button(
            "VALIDAR BASE DE FORNECEDORES",
            type="primary",
            use_container_width=True,
            key="validate_supplier_import",
        )

        if validate_supplier:
            try:
                with st.spinner("Lendo e validando fornecedores..."):
                    raw, sheets = read_uploaded_table(upload, header_row=None)
                    if raw.shape[1] < 15:
                        raise ValueError(
                            "O relatório FORNECEDORES precisa conter pelo menos as colunas A até O."
                        )

                    incoming = pd.DataFrame({
                        "codigo": raw.iloc[:, 0].fillna("").astype(str).str.strip(),
                        "loja": raw.iloc[:, 1].fillna("").astype(str).str.strip(),
                        "nome_padrao": raw.iloc[:, 2].fillna("").astype(str).str.strip(),
                        "nome_fantasia": raw.iloc[:, 3].fillna("").astype(str).str.strip(),
                        "tipo": raw.iloc[:, 10].fillna("").astype(str).str.strip(),
                        "cnpj": raw.iloc[:, 14].map(digits_only),
                    })

                    # Remove eventual linha de cabeçalho, pois a leitura é posicional.
                    incoming = incoming[
                        ~incoming["cnpj"].map(normalize_text).str.contains("CNPJ", na=False)
                    ].copy()

                    incoming["aliases"] = incoming["nome_fantasia"]
                    incoming["ativo"] = True
                    incoming["cnpj_valido"] = incoming["cnpj"].map(valid_cnpj)
                    incoming["nome_valido"] = incoming["nome_padrao"].ne("")

                    invalid = incoming[
                        ~incoming["cnpj_valido"]
                        | ~incoming["nome_valido"]
                    ].copy()
                    valid = incoming[
                        incoming["cnpj_valido"]
                        & incoming["nome_valido"]
                    ].copy()

                    duplicate_rows = valid[
                        valid["cnpj"].duplicated(keep=False)
                    ].copy()
                    conflict_cnpjs = []
                    preferred_rows = []

                    for cnpj, group in valid.groupby("cnpj", sort=False):
                        if len(group) == 1:
                            preferred_rows.append(group.iloc[0])
                            continue

                        compact_names = [
                            re.sub(
                                r"[^A-Z0-9]",
                                "",
                                normalize_text(name),
                            )
                            for name in group["nome_padrao"].tolist()
                        ]
                        base_name = min(compact_names, key=len)
                        equivalent = all(
                            name == base_name
                            or name.startswith(base_name)
                            or base_name.startswith(name)
                            for name in compact_names
                        )

                        if equivalent:
                            chosen_idx = group["nome_padrao"].map(
                                lambda x: len(normalize_text(x))
                            ).idxmin()
                            preferred_rows.append(group.loc[chosen_idx])
                        else:
                            conflict_cnpjs.append(cnpj)

                    clean = pd.DataFrame(preferred_rows).copy()
                    if not clean.empty:
                        clean = clean[
                            ~clean["cnpj"].isin(conflict_cnpjs)
                        ].copy()

                    conflicts = duplicate_rows[
                        duplicate_rows["cnpj"].isin(conflict_cnpjs)
                    ].copy()

                    stats = {
                        "total": len(incoming),
                        "validos": len(clean),
                        "invalidos": len(invalid),
                        "duplicados": int(
                            len(valid) - valid["cnpj"].nunique()
                        ),
                        "conflitos": len(conflict_cnpjs),
                    }

                    st.session_state.supplier_import_preview = clean
                    st.session_state.supplier_import_stats = stats
                    st.session_state.supplier_import_conflicts = conflicts
                    st.session_state.supplier_import_name = upload.name

                set_flash(
                    "_flash_supplier",
                    "success" if len(clean) else "warning",
                    (
                        f"Base validada: {len(clean)} CNPJ(s) válido(s)."
                        if len(clean)
                        else "Relatório processado, mas nenhum fornecedor válido foi encontrado."
                    ),
                )
                st.rerun()
            except Exception as exc:
                st.error(f"Falha ao interpretar base de fornecedores: {exc}")

    clean = st.session_state.get("supplier_import_preview")
    stats = st.session_state.get("supplier_import_stats") or {}
    conflicts = st.session_state.get("supplier_import_conflicts")
    supplier_name = str(st.session_state.get("supplier_import_name") or "")

    if isinstance(clean, pd.DataFrame) and not clean.empty:
        st.markdown(f"#### Prévia validada — {supplier_name}")
        s1, s2, s3, s4 = st.columns(4)
        s1.metric("Linhas do relatório", stats.get("total", 0))
        s2.metric("CNPJs válidos", stats.get("validos", 0))
        s3.metric("Duplicidades equivalentes", stats.get("duplicados", 0))
        s4.metric("Ignoradas", stats.get("invalidos", 0))

        if isinstance(conflicts, pd.DataFrame) and not conflicts.empty:
            st.error(
                f"Há {stats.get('conflitos', 0)} CNPJ(s) vinculados a Razões Sociais diferentes."
            )
            st.dataframe(
                conflicts,
                use_container_width=True,
                hide_index=True,
            )

        show_cols = [
            "codigo",
            "loja",
            "cnpj",
            "nome_padrao",
            "nome_fantasia",
            "tipo",
            "aliases",
        ]
        st.dataframe(
            clean[show_cols].head(500),
            use_container_width=True,
            hide_index=True,
        )

        can_replace = not (
            isinstance(conflicts, pd.DataFrame) and not conflicts.empty
        )
        if st.button(
            "SUBSTITUIR BASE DE FORNECEDORES",
            type="primary",
            use_container_width=True,
            disabled=not can_replace,
            key="replace_supplier_import",
        ):
            try:
                final = supplier_dataframe(
                    clean[
                        [
                            "cnpj",
                            "nome_padrao",
                            "aliases",
                            "ativo",
                            "codigo",
                            "loja",
                            "nome_fantasia",
                            "tipo",
                        ]
                    ]
                )
                if db.configured():
                    result = db.replace_suppliers(
                        final.to_dict("records"),
                        supplier_name or "fornecedores",
                        stats,
                    )
                    st.session_state.suppliers = final
                    message = (
                        f"Base de fornecedores substituída: "
                        f"{int(result.get('fornecedores', len(final)))} registro(s)."
                    )
                else:
                    st.session_state.suppliers = final
                    message = "Base de fornecedores aplicada somente nesta sessão."

                set_flash("_flash_supplier", "success", message)
                st.rerun()
            except Exception as exc:
                st.error(f"Falha ao gravar base de fornecedores: {exc}")



def render_nf_treatment_center() -> None:
    """Central única para todas as decisões operacionais de NF."""
    rejected = [
        item
        for item in (st.session_state.get("prefilter_rejected") or [])
        if bool(item.get("vinculado_base"))
    ]
    # Remove também do estado qualquer sobra antiga sem vínculo com a base.
    st.session_state.prefilter_rejected = rejected
    resolved = list(st.session_state.get("prefilter_resolved") or [])
    file_store = st.session_state.get("prefilter_files") or {}

    st.markdown("### Central de tratativas de NF")
    st.caption(
        "Aqui aparecem somente problemas de documentos já reconhecidos como pertencentes "
        "às NFs válidas da base. Arquivos sobressalentes são ignorados automaticamente."
    )

    if rejected:
        st.markdown("#### Arquivos que exigem decisão")
        st.warning(
            f"{len(rejected)} arquivo(s) precisam ser avaliados antes de encerrar a carga."
        )

        pending_pre = current_pending_pre_notes()
        target_map = {}
        target_options = [""]
        if isinstance(pending_pre, pd.DataFrame) and not pending_pre.empty:
            for idx, row in pending_pre.iterrows():
                nf = normalized_nf(row.get("numero_nf"))
                supplier = pre_supplier_name(row)
                date_value = normalized_business_date(row.get("data_pre_nota"))
                label = " | ".join(
                    part for part in [
                        f"NF {nf}" if nf else "",
                        supplier,
                        date_value.strftime("%d/%m/%Y") if date_value else "",
                    ]
                    if part
                )
                key = f"{idx}::{label}"
                target_map[key] = row
                target_options.append(key)

        # Se o XML/PDF estiver inválido ou precisar ser corrigido na origem,
        # o operador pode substituir o arquivo aqui mesmo, sem retornar à tela
        # de Processamento de arquivos.
        replace_map = {}
        for item in rejected:
            rid = str(item.get("file_id") or "").strip()
            if not rid:
                continue
            label = (
                f"{item.get('arquivo') or 'Arquivo'}"
                f" | {str(item.get('motivo') or '')[:90]}"
            )
            # Garante rótulos únicos mesmo quando há nomes repetidos.
            replace_map[f"{rid}::{label}"] = rid

        if replace_map:
            with st.expander("Substituir XML/PDF corrigido", expanded=False):
                selected_replace = st.selectbox(
                    "Arquivo que será substituído",
                    list(replace_map.keys()),
                    format_func=lambda value: value.split("::", 1)[-1],
                    key="prefilter_replace_target",
                )
                replacement_file = st.file_uploader(
                    "Selecione o XML ou PDF corrigido",
                    type=["xml", "pdf"],
                    key="prefilter_replacement_file",
                )

                if st.button(
                    "REPROCESSAR ARQUIVO CORRIGIDO",
                    type="primary",
                    use_container_width=True,
                    disabled=not bool(replacement_file),
                    key="reprocess_corrected_file",
                ):
                    file_id = replace_map.get(selected_replace, "")
                    try:
                        raw = replacement_file.getvalue()
                        ext = Path(replacement_file.name).suffix.lower()
                        pending_base = current_pending_pre_notes()
                        if pending_base.empty:
                            raise ValueError(
                                "Não há pré-notas pendentes disponíveis para validar o arquivo."
                            )

                        group = None
                        if ext == ".xml":
                            xml_data = extract_nfe_processing_data(raw)
                            identity = _xml_prefilter_identity(xml_data)
                            match = match_document_to_pre_note(
                                identity,
                                pre_notes=pending_base,
                            )
                            if not match.get("matched"):
                                raise ValueError(
                                    "O XML corrigido ainda não possui correspondência segura "
                                    f"com as pré-notas: {match.get('situacao') or 'SEM CORRESPONDÊNCIA'}."
                                )
                            group = {
                                "pre": match["row"],
                                "xmls": [{
                                    "file_id": file_id,
                                    "name": replacement_file.name,
                                    "raw": raw,
                                    "data": xml_data,
                                    "score": int(match.get("score_fornecedor") or 100),
                                }],
                                "pdfs": [],
                            }
                        elif ext == ".pdf":
                            identity = inspect_nf_pdf_identity(
                                replacement_file.name,
                                raw,
                                st.session_state.suppliers,
                            )
                            match = match_document_to_pre_note(
                                identity,
                                pre_notes=pending_base,
                            )
                            if not match.get("matched"):
                                raise ValueError(
                                    "O PDF corrigido ainda não possui correspondência segura "
                                    f"com as pré-notas: {match.get('situacao') or 'SEM CORRESPONDÊNCIA'}."
                                )
                            group = {
                                "pre": match["row"],
                                "xmls": [],
                                "pdfs": [{
                                    "file_id": file_id,
                                    "name": replacement_file.name,
                                    "raw": raw,
                                    "identity": identity,
                                    "score": int(match.get("score_fornecedor") or 100),
                                }],
                            }
                        else:
                            raise ValueError("Tipo de arquivo não suportado.")

                        row, stored = _build_hybrid_nf_document(group)
                        row["status"] = "REVISAR"
                        row["observacao"] = (
                            (str(row.get("observacao") or "") + " | ")
                            + "ARQUIVO CORRIGIDO E REPROCESSADO PELO OPERADOR"
                        ).strip(" |")

                        current = st.session_state.analysis.copy()
                        appended = pd.DataFrame([row])
                        combined = (
                            pd.concat([current, appended], ignore_index=True)
                            if not current.empty
                            else appended
                        )
                        combined = apply_cross_checks(combined)
                        combined = recalc(combined)
                        st.session_state.analysis = combined
                        st.session_state.pdfs[row["file_id"]] = stored

                        st.session_state.prefilter_files[file_id] = {
                            "name": replacement_file.name,
                            "ext": ext,
                            "raw": raw,
                        }
                        original = next(
                            (
                                item for item in rejected
                                if str(item.get("file_id") or "") == file_id
                            ),
                            {},
                        )
                        resolved_item = dict(original)
                        resolved_item["decisao"] = "ARQUIVO CORRIGIDO E REPROCESSADO"
                        resolved_item["tratado_em"] = now_local().isoformat(timespec="seconds")
                        st.session_state.prefilter_resolved = (
                            list(st.session_state.get("prefilter_resolved") or [])
                            + [resolved_item]
                        )
                        st.session_state.prefilter_rejected = [
                            item for item in rejected
                            if str(item.get("file_id") or "") != file_id
                        ]

                        st.session_state.pop("prefilter_replacement_file", None)
                        st.success("Arquivo corrigido reprocessado e enviado para conferência.")
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Não foi possível reprocessar o arquivo corrigido: {exc}")

        review_df = pd.DataFrame(rejected).copy()
        if "file_id" not in review_df.columns:
            review_df["file_id"] = ""
        review_df.insert(0, "Decisão", "PENDENTE")
        review_df["Vincular à pré-nota"] = ""

        editor = st.data_editor(
            review_df,
            use_container_width=True,
            hide_index=True,
            num_rows="fixed",
            key="prefilter_treatment_editor",
            disabled=[
                col for col in review_df.columns
                if col not in {"Decisão", "Vincular à pré-nota"}
            ],
            column_config={
                "file_id": None,
                "Decisão": st.column_config.SelectboxColumn(
                    "Decisão",
                    options=["PENDENTE", "INCLUIR", "NÃO INCLUIR"],
                    required=True,
                ),
                "Vincular à pré-nota": st.column_config.SelectboxColumn(
                    "Vincular à pré-nota",
                    options=target_options,
                    help="Obrigatório quando a decisão for INCLUIR manualmente.",
                ),
                "arquivo": st.column_config.TextColumn("Arquivo", width="large"),
                "tipo": "Tipo",
                "nf": "NF identificada",
                "fornecedor": st.column_config.TextColumn("Fornecedor identificado", width="large"),
                "motivo": st.column_config.TextColumn("Motivo / atenção necessária", width="large"),
                "aderencia_fornecedor": st.column_config.NumberColumn(
                    "Aderência fornecedor",
                    format="%d%%",
                ),
            },
        )

        if st.button(
            "APLICAR DECISÕES DOS ARQUIVOS",
            type="primary",
            use_container_width=True,
            key="apply_prefilter_decisions",
        ):
            remaining = []
            newly_resolved = []
            new_rows = []
            new_store = {}

            for _, decision_row in editor.iterrows():
                decision = str(decision_row.get("Decisão") or "PENDENTE").strip().upper()
                original = {
                    key: decision_row.get(key)
                    for key in ["file_id", "arquivo", "tipo", "nf", "fornecedor", "motivo", "aderencia_fornecedor"]
                }

                if decision == "PENDENTE":
                    remaining.append(original)
                    continue

                if decision == "NÃO INCLUIR":
                    original["decisao"] = "NÃO INCLUIR"
                    original["tratado_em"] = now_local().isoformat(timespec="seconds")
                    newly_resolved.append(original)
                    continue

                target_key = str(decision_row.get("Vincular à pré-nota") or "").strip()
                target_pre = target_map.get(target_key)
                file_id = str(decision_row.get("file_id") or "").strip()
                stored_file = file_store.get(file_id)

                if target_pre is None:
                    original["motivo"] = (
                        str(original.get("motivo") or "")
                        + " | Selecione a pré-nota de destino para incluir."
                    ).strip(" |")
                    remaining.append(original)
                    continue

                if not stored_file:
                    original["motivo"] = (
                        str(original.get("motivo") or "")
                        + " | Arquivo original não está mais disponível nesta sessão."
                    ).strip(" |")
                    remaining.append(original)
                    continue

                try:
                    ext = str(stored_file.get("ext") or "").lower()
                    raw = stored_file.get("raw") or b""
                    group = {
                        "pre": target_pre,
                        "xmls": [],
                        "pdfs": [],
                    }

                    if ext == ".xml":
                        xml_data = extract_nfe_processing_data(raw)
                        group["xmls"].append({
                            "file_id": file_id,
                            "name": stored_file.get("name") or original.get("arquivo") or "arquivo.xml",
                            "raw": raw,
                            "data": xml_data,
                            "score": 100,
                        })
                    elif ext == ".pdf":
                        identity = inspect_nf_pdf_identity(
                            stored_file.get("name") or original.get("arquivo") or "arquivo.pdf",
                            raw,
                            st.session_state.suppliers,
                        )
                        group["pdfs"].append({
                            "file_id": file_id,
                            "name": stored_file.get("name") or original.get("arquivo") or "arquivo.pdf",
                            "raw": raw,
                            "identity": identity,
                            "score": 100,
                        })
                    else:
                        raise ValueError("Tipo de arquivo não suportado para inclusão manual.")

                    row, stored = _build_hybrid_nf_document(group)
                    row["status"] = "REVISAR"
                    row["observacao"] = (
                        (str(row.get("observacao") or "") + " | ")
                        + "INCLUSÃO MANUAL VALIDADA PELO OPERADOR"
                    ).strip(" |")
                    new_rows.append(row)
                    new_store[row["file_id"]] = stored

                    original["decisao"] = "INCLUIR"
                    original["tratado_em"] = now_local().isoformat(timespec="seconds")
                    newly_resolved.append(original)
                except Exception as exc:
                    original["motivo"] = (
                        str(original.get("motivo") or "")
                        + f" | Não foi possível incluir: {exc}"
                    ).strip(" |")
                    remaining.append(original)

            if new_rows:
                current = st.session_state.analysis.copy()
                appended = pd.DataFrame(new_rows)
                combined = (
                    pd.concat([current, appended], ignore_index=True)
                    if not current.empty
                    else appended
                )
                combined = apply_cross_checks(combined)
                combined = recalc(combined)
                st.session_state.analysis = combined
                st.session_state.pdfs.update(new_store)

            st.session_state.prefilter_rejected = remaining
            st.session_state.prefilter_resolved = resolved + newly_resolved
            st.session_state.pop("prefilter_treatment_editor", None)
            st.rerun()

    elif resolved:
        st.success("Nenhum arquivo aguardando decisão manual nesta carga.")

    # Conferência, correções, aprovação, geração e download que antes ficavam
    # em Processamento de arquivos agora vivem integralmente nesta central.
    frame = st.session_state.analysis.copy()
    if not frame.empty and "origem_dados" not in frame.columns:
        frame["origem_dados"] = "PDF"
    if frame.empty:
        st.info("Nenhum lote analisado nesta sessão.")
    else:
        frame = apply_cross_checks(frame)
        frame = recalc(frame)

        merged = frame.copy()
        pending_mask = treatment_mask(merged)
        pending = merged.loc[pending_mask].copy()
        ready_count = int((~pending_mask).sum())
        priority_count = int(
            merged.get(
                "prioridade_mrp",
                pd.Series(False, index=merged.index),
            )
            .fillna(False)
            .astype(bool)
            .sum()
        )

        st.markdown("### Conferência")
        st.caption(
            f"{len(merged)} NF(s) vinculada(s) • {ready_count} pronta(s) • "
            f"{len(pending)} tratativa(s) • {priority_count} prioridade(s)"
        )
        with st.expander("Regras da conferência", expanded=False):
            st.caption(
                "Corrija apenas exceções. Vencimento, NF, fornecedor, empresa e status "
                "podem ser ajustados. A Natureza vem exclusivamente da carga STSUP01."
            )

        with st.expander(
            f"Ver documentos prontos ({int((~pending_mask).sum())})",
            expanded=False,
        ):
            ready_cols = [
                "arquivo_original",
                "origem_dados",
                "numero_nf",
                "fornecedor_padrao",
                "empresa_sigla",
                "vencimento",
                "natureza",
                "nome_sugerido",
                "prioridade_mrp",
            ]
            st.dataframe(
                merged.loc[~pending_mask, ready_cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "arquivo_original": "Arquivo",
                    "origem_dados": "Origem",
                    "numero_nf": "NF",
                    "fornecedor_padrao": "Fornecedor",
                    "empresa_sigla": st.column_config.TextColumn("Empresa"),
                    "vencimento": st.column_config.DateColumn("Vencimento", format="DD/MM/YYYY"),
                    "natureza": "Natureza",
                    "nome_sugerido": "Nome final",
                    "prioridade_mrp": st.column_config.CheckboxColumn("Prioridade"),
                },
            )

        if pending.empty:
            st.caption("Sem tratativas pendentes nesta carga.")
        else:
            st.markdown("### Tratativas necessárias")
            st.warning(
                f"{len(pending)} documento(s) precisam de tratativa. "
                "Corrija somente os campos necessários abaixo e clique em **Aplicar correções**."
            )

            treatment_cols = [
                "arquivo_original",
                "origem_dados",
                "vencimento",
                "numero_nf",
                "cnpj_fornecedor",
                "fornecedor_padrao",
                "empresa_sigla",
                "natureza",
                "status",
                "validacao",
                "observacao",
            ]

            treatment_editor = st.data_editor(
                pending[treatment_cols],
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                key="treatment_editor",
                disabled=[
                    "arquivo_original",
                    "origem_dados",
                    "natureza",
                    "validacao",
                    "observacao",
                ],
                column_config={
                    "arquivo_original": st.column_config.TextColumn(
                        "Arquivo",
                        width="medium",
                    ),
                    "origem_dados": st.column_config.TextColumn(
                        "Origem",
                        width="small",
                    ),
                    "vencimento": st.column_config.DateColumn(
                        "Vencimento",
                        format="DD/MM/YYYY",
                    ),
                    "numero_nf": st.column_config.TextColumn("NF"),
                    "cnpj_fornecedor": st.column_config.TextColumn("CNPJ emitente"),
                    "fornecedor_padrao": st.column_config.TextColumn(
                        "Fornecedor",
                        width="large",
                    ),
                    "empresa_sigla": st.column_config.SelectboxColumn(
                        "Empresa",
                        options=["SEN", "SEE", "STA"],
                        help="SEN = Energy | SEE = Engenharia | STA = Astec",
                    ),
                    "natureza": st.column_config.TextColumn(
                        "Natureza",
                        width="large",
                        help="Somente leitura. Retornada exclusivamente da carga de Nota Fiscal (STSUP01, coluna Natureza).",
                    ),
                    "status": st.column_config.SelectboxColumn(
                        "Status",
                        options=["REVISAR", "APROVADO"],
                        required=True,
                    ),
                    "validacao": st.column_config.TextColumn(
                        "Pendência",
                        width="medium",
                    ),
                    "observacao": st.column_config.TextColumn(
                        "Leitura automática",
                        width="large",
                    ),
                },
            )

            if st.button(
                "APLICAR CORREÇÕES",
                type="primary",
                use_container_width=True,
                key="apply_treatments",
            ):
                updated = merged.copy()
                editable_cols = [
                    "vencimento",
                    "numero_nf",
                    "cnpj_fornecedor",
                    "fornecedor_padrao",
                    "empresa_sigla",
                    "status",
                ]
                for idx in treatment_editor.index:
                    for col in editable_cols:
                        updated.loc[idx, col] = treatment_editor.loc[idx, col]

                updated["natureza"] = (
                    updated["natureza"]
                    .fillna("")
                    .astype(str)
                    .str.strip()
                    .str.upper()
                )
                updated = apply_cross_checks(updated)
                updated = recalc(updated)

                # Clicar em Aplicar correções representa a confirmação do
                # operador. Se a linha ficou completa após as correções,
                # aprova automaticamente; linhas ainda inválidas continuam
                # como REVISAR pelo recalc.
                for idx in treatment_editor.index:
                    validation = str(
                        updated.loc[idx, "validacao"]
                        if idx in updated.index
                        else ""
                    ).strip()
                    final_name = str(
                        updated.loc[idx, "nome_sugerido"]
                        if idx in updated.index
                        else ""
                    ).strip()
                    if idx in updated.index and not validation and final_name:
                        updated.loc[idx, "status"] = "APROVADO"

                updated = recalc(updated)
                st.session_state.analysis = updated

                # Limpa o estado do editor para a próxima renderização usar
                # exatamente os dados já salvos no DataFrame.
                st.session_state.pop("treatment_editor", None)
                st.rerun()

        merged = st.session_state.analysis.copy()
        merged = apply_cross_checks(merged)
        merged = recalc(merged)
        st.session_state.analysis = merged

        invalid_mask = treatment_mask(merged)
        invalid = merged.loc[invalid_mask].copy()
        duplicate = (
            merged["nome_sugerido"].fillna("").astype(str).str.strip().duplicated(keep=False)
            & merged["nome_sugerido"].fillna("").astype(str).str.strip().ne("")
        )

        st.markdown("### Definição de prioridade")
        st.caption(
            "A prioridade calculada pelo MRP permanece automática. O operador pode "
            "marcar prioridade adicional para qualquer NF antes da geração dos arquivos."
        )
        priority_cols = [
            col for col in [
                "file_id",
                "numero_nf",
                "fornecedor_padrao",
                "empresa_sigla",
                "natureza",
                "prioridade_mrp_base",
                "prioridade_manual",
            ]
            if col in merged.columns
        ]
        priority_view = merged[priority_cols].copy()
        if "prioridade_mrp_base" not in priority_view.columns:
            priority_view["prioridade_mrp_base"] = False
        if "prioridade_manual" not in priority_view.columns:
            priority_view["prioridade_manual"] = False

        with st.form("priority_selection_form"):
            priority_editor = st.data_editor(
                priority_view,
                use_container_width=True,
                hide_index=True,
                num_rows="fixed",
                key="priority_selection_editor",
                disabled=[
                    col for col in priority_view.columns
                    if col != "prioridade_manual"
                ],
                column_config={
                    "file_id": None,
                    "numero_nf": "NF",
                    "fornecedor_padrao": st.column_config.TextColumn(
                        "Fornecedor",
                        width="large",
                    ),
                    "empresa_sigla": st.column_config.TextColumn(
                        "Empresa",
                        help="SEN = Energy | SEE = Engenharia | STA = Astec",
                    ),
                    "natureza": st.column_config.TextColumn(
                        "Natureza",
                        width="medium",
                    ),
                    "prioridade_mrp_base": st.column_config.CheckboxColumn(
                        "Prioridade MRP",
                        help="Definida automaticamente pelo cálculo do MRP.",
                    ),
                    "prioridade_manual": st.column_config.CheckboxColumn(
                        "Prioridade",
                        help="Marque para adicionar esta NF ao fluxo prioritário.",
                    ),
                },
            )
            save_priorities = st.form_submit_button(
                "SALVAR PRIORIDADES",
                use_container_width=True,
            )

        if save_priorities:
            updated = st.session_state.analysis.copy()
            if "prioridade_manual" not in updated.columns:
                updated["prioridade_manual"] = False

            if "file_id" in priority_editor.columns and "file_id" in updated.columns:
                priority_map = {
                    str(row.get("file_id") or ""): bool(row.get("prioridade_manual"))
                    for _, row in priority_editor.iterrows()
                }
                updated["prioridade_manual"] = updated.apply(
                    lambda row: priority_map.get(
                        str(row.get("file_id") or ""),
                        bool(row.get("prioridade_manual", False)),
                    ),
                    axis=1,
                )

            updated = apply_cross_checks(updated)
            updated = recalc(updated)
            st.session_state.analysis = updated
            st.session_state.pop("priority_selection_editor", None)
            st.rerun()

        if duplicate.any():
            st.error("Há nomes finais duplicados no lote. Os arquivos duplicados precisam ser tratados antes do ZIP.")
        elif not invalid.empty:
            st.info("O botão de geração ficará liberado quando todas as tratativas forem concluídas.")
        else:
            normal = int((~merged["prioridade_mrp"].fillna(False).astype(bool)).sum())
            priority = int(merged["prioridade_mrp"].fillna(False).astype(bool).sum())
            st.success(
                f"Lote aprovado: {normal} documento(s) no fluxo normal e "
                f"{priority} em prioridade."
            )
            with st.expander("Prévia final dos nomes", expanded=False):
                st.dataframe(
                    merged[
                        [
                            "arquivo_original",
                            "nome_sugerido",
                            "natureza",
                            "prioridade_mrp",
                        ]
                    ],
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "arquivo_original": "Arquivo original",
                        "nome_sugerido": "Nome final",
                        "natureza": "Natureza",
                        "prioridade_mrp": st.column_config.CheckboxColumn("Prioridade MRP"),
                    },
                )

        cte_pending_errors = bool(st.session_state.get("cte_rejected") or [])
        if cte_pending_errors:
            st.info(
                "A geração final fica bloqueada enquanto houver CT-e com erro de vínculo ou processamento."
            )

        if st.button(
            "GERAR ARQUIVOS RENOMEADOS E COMPACTADOS",
            type="primary",
            use_container_width=True,
            disabled=(not invalid.empty or duplicate.any() or cte_pending_errors),
        ):
            try:
                outputs, manifest = make_zip_outputs(merged)
                st.session_state.zip_outputs = outputs

                if SAVE_NF_HISTORY:
                    st.session_state.history.extend(manifest)
                    if db.configured():
                        try:
                            db.save_process_records(manifest)
                            st.success("ZIPs criados e registros gravados no Supabase. Nenhum PDF foi salvo no banco.")
                        except Exception as exc:
                            st.warning(f"ZIPs criados, mas o histórico não pôde ser gravado no Supabase: {exc}")
                    else:
                        st.success("ZIPs criados. Histórico mantido nesta sessão; nenhum PDF foi salvo em banco.")
                else:
                    # Mantém somente a carga atual para testar a conferência.
                    # Ao processar uma nova carga, esta referência é substituída.
                    st.session_state.current_test_manifest = manifest
                    st.success(
                        "ZIPs criados em modo de testes. A conferência usa apenas esta carga atual; "
                        "nenhum histórico foi acumulado e nada foi gravado no Supabase."
                    )

                # Recarrega a central para que a etapa de baixa/confirmação
                # apareça imediatamente na mesma tela.
                st.rerun()
            except Exception as exc:
                st.error(f"Falha ao gerar ZIP: {exc}")

        if st.session_state.zip_outputs:
            all_zips_buffer = io.BytesIO()
            with zipfile.ZipFile(
                all_zips_buffer,
                "w",
                compression=zipfile.ZIP_STORED,
            ) as master_zip:
                for zip_name, zip_bytes in st.session_state.zip_outputs.items():
                    master_zip.writestr(zip_name, zip_bytes)

            all_zips_name = (
                f"{now_local():%d-%m-%Y} - TODOS OS ZIPS - NOTAS FISCAIS.zip"
            )
            st.download_button(
                "BAIXAR TODOS OS ZIPs",
                all_zips_buffer.getvalue(),
                file_name=all_zips_name,
                mime="application/zip",
                type="primary",
                use_container_width=True,
                key="download_all_nf_zips",
            )
            st.caption(
                f"O arquivo acima reúne {len(st.session_state.zip_outputs)} ZIP(s) "
                "gerado(s) nesta carga. Os downloads individuais permanecem disponíveis abaixo."
            )

            for zip_name, zip_bytes in st.session_state.zip_outputs.items():
                st.download_button(
                    f"Baixar {zip_name}",
                    zip_bytes,
                    file_name=zip_name,
                    mime="application/zip",
                    use_container_width=True,
                    key=f"download_{zip_name}",
                )



def _refresh_missing_mrp_analysis() -> pd.DataFrame:
    summary = st.session_state.get("mrp_priority_summary")
    pre = st.session_state.get("pre_notes")

    rows = []
    if (
        isinstance(summary, pd.DataFrame)
        and not summary.empty
        and isinstance(pre, pd.DataFrame)
        and not pre.empty
    ):
        for _, mrp_row in summary.iterrows():
            match = match_mrp_to_pre_note(mrp_row, pre)
            if not match.get("matched"):
                item = mrp_row.to_dict()
                item["situacao_vinculo"] = str(
                    match.get("situacao") or "AUSENTE NAS PRÉ-NOTAS"
                )
                item["score_fornecedor"] = int(
                    match.get("score_fornecedor") or 0
                )
                rows.append(item)

    frame = pd.DataFrame(rows)
    st.session_state.base_analysis_missing_mrp = frame
    return frame


def render_mrp_missing_pre_treatments() -> None:
    if not st.session_state.get("base_analysis_ready"):
        return

    missing = _refresh_missing_mrp_analysis()

    st.markdown("### Conferência entre MRP e Pré-notas")
    if missing.empty:
        st.success(
            "Nenhuma NF do MRP está pendente de decisão em relação à base de Pré-notas."
        )
        return

    st.warning(
        f"{len(missing)} NF(s) do MRP não tiveram correspondência segura na base de Pré-notas. "
        "Resolva essas ocorrências antes de vincular os XMLs."
    )

    missing = missing.copy()
    missing["_mrp_key"] = missing.apply(mrp_row_key, axis=1)
    visible_cols = [
        "_mrp_key",
        "data_pre_nota",
        "numero_nf",
        "cnpj",
        "fornecedor",
        "prioridade",
        "data_cm",
        "situacao_vinculo",
        "score_fornecedor",
    ]
    visible_cols = [col for col in visible_cols if col in missing.columns]
    view = missing[visible_cols].copy()
    view.insert(0, "Selecionar", False)

    edited = st.data_editor(
        view,
        use_container_width=True,
        hide_index=True,
        disabled=[col for col in view.columns if col != "Selecionar"],
        key="base_missing_mrp_editor",
        column_config={
            "_mrp_key": None,
            "Selecionar": st.column_config.CheckboxColumn("Selecionar"),
            "data_pre_nota": st.column_config.DateColumn(
                "Data",
                format="DD/MM/YYYY",
            ),
            "numero_nf": "NF",
            "cnpj": "CNPJ",
            "fornecedor": st.column_config.TextColumn(
                "Fornecedor",
                width="large",
            ),
            "prioridade": "Prioridade",
            "data_cm": st.column_config.DateColumn(
                "Data CM",
                format="DD/MM/YYYY",
            ),
            "situacao_vinculo": st.column_config.TextColumn(
                "Situação",
                width="large",
            ),
            "score_fornecedor": st.column_config.NumberColumn(
                "Aderência fornecedor",
                format="%d%%",
            ),
        },
    )

    selected = edited[
        edited["Selecionar"].fillna(False).astype(bool)
    ].copy()

    action = st.selectbox(
        "Tratativa para as NFs selecionadas",
        [
            "Escolha uma ação",
            "Adicionar às Pré-notas pendentes",
            "Desconsiderar do cálculo atual",
        ],
        key="base_missing_mrp_action",
    )

    if st.button(
        "APLICAR TRATATIVA",
        type="primary",
        use_container_width=True,
        disabled=selected.empty or action == "Escolha uma ação",
        key="apply_base_missing_mrp",
    ):
        if action == "Adicionar às Pré-notas pendentes":
            additions = []
            for _, row in selected.iterrows():
                additions.append({
                    "data_pre_nota": normalized_business_date(
                        row.get("data_pre_nota")
                    ),
                    "numero_nf": normalized_nf(row.get("numero_nf")),
                    "cnpj": digits_only(row.get("cnpj")),
                    "fornecedor": str(row.get("fornecedor") or "").strip(),
                    "recebedor": "",
                    "status": "Pré-nota lançada",
                    "natureza": str(row.get("natureza") or "").strip(),
                    "origem": "Impacto MRP / Protheus",
                })

            current = st.session_state.pre_notes.copy()
            updated = pd.concat(
                [current, pd.DataFrame(additions)],
                ignore_index=True,
                sort=False,
            )
            updated["_data_nf"] = updated.apply(
                lambda row: date_nf_key(
                    row.get("data_pre_nota"),
                    row.get("numero_nf"),
                ),
                axis=1,
            )
            updated["_supplier_norm"] = updated.apply(
                lambda row: supplier_validation_name(
                    pre_supplier_name(row)
                ),
                axis=1,
            )
            updated = (
                updated.drop_duplicates(
                    ["_data_nf", "_supplier_norm"],
                    keep="last",
                )
                .drop(
                    columns=["_data_nf", "_supplier_norm"],
                    errors="ignore",
                )
                .reset_index(drop=True)
            )
            st.session_state.pre_notes = updated
            persist_pre_notes_current("Impacto MRP / Protheus")
            _refresh_missing_mrp_analysis()
            st.session_state.document_reprocess_needed = True
            st.session_state.pop("base_missing_mrp_editor", None)
            st.rerun()

        if action == "Desconsiderar do cálculo atual":
            ignore_keys = set(
                selected["_mrp_key"]
                .fillna("")
                .astype(str)
                .loc[lambda values: values.ne("")]
                .tolist()
            )

            summary = st.session_state.mrp_priority_summary.copy()
            summary["_mrp_key"] = summary.apply(mrp_row_key, axis=1)
            ignored_rows = summary[
                summary["_mrp_key"].isin(ignore_keys)
            ].copy()
            st.session_state.mrp_priority_summary = (
                summary[
                    ~summary["_mrp_key"].isin(ignore_keys)
                ]
                .drop(columns="_mrp_key", errors="ignore")
                .reset_index(drop=True)
            )

            detail = st.session_state.get("mrp_impact_detail")
            if isinstance(detail, pd.DataFrame) and not detail.empty:
                detail = detail.copy()
                detail["_mrp_key"] = detail.apply(mrp_row_key, axis=1)
                st.session_state.mrp_impact_detail = (
                    detail[
                        ~detail["_mrp_key"].isin(ignore_keys)
                    ]
                    .drop(columns="_mrp_key", errors="ignore")
                    .reset_index(drop=True)
                )

            ignored_log = list(
                st.session_state.get("mrp_ignored_records") or []
            )
            now_ignored = now_local().isoformat(timespec="seconds")
            for _, row in ignored_rows.iterrows():
                item = row.drop(labels=["_mrp_key"], errors="ignore").to_dict()
                item["desconsiderada_em"] = now_ignored
                ignored_log.append(item)
            st.session_state.mrp_ignored_records = ignored_log

            current_summary = st.session_state.mrp_priority_summary
            high = (
                current_summary[
                    current_summary["prioridade"]
                    .fillna("")
                    .astype(str)
                    .str.upper()
                    .eq("ALTA")
                ]
                if not current_summary.empty
                else pd.DataFrame()
            )
            st.session_state.priority_date_nf_keys = set(
                high.get("data_nf", pd.Series(dtype=str))
                .dropna().astype(str).tolist()
            )
            st.session_state.priority_nf_numbers = set(
                high.get("numero_nf", pd.Series(dtype=str))
                .dropna().astype(str).tolist()
            )

            persist_mrp_current()
            _refresh_missing_mrp_analysis()
            st.session_state.pop("base_missing_mrp_editor", None)
            st.rerun()


def render_xml_linking_stage() -> None:
    st.markdown("### Vinculação dos XMLs")

    if not st.session_state.get("base_analysis_ready"):
        st.info(
            "Primeiro execute a análise dos relatórios em Processamento de arquivos."
        )
        return

    missing = _refresh_missing_mrp_analysis()
    if not missing.empty:
        st.info(
            "Resolva primeiro as NFs do MRP sem correspondência segura nas Pré-notas. "
            "A vinculação dos XMLs será liberada depois dessa etapa."
        )
        return

    pending_base = current_pending_pre_notes()
    if pending_base.empty:
        st.success("Não há Pré-notas pendentes aguardando XML.")
        return

    st.caption(
        f"{len(pending_base)} Pré-nota(s) estão aptas para receber XML. "
        "Somente XMLs correspondentes a esse universo serão vinculados."
    )

    xml_stats = st.session_state.get("prefilter_stats") or {}
    ignored_previous = int(xml_stats.get("ignorados") or 0)
    if ignored_previous:
        st.caption(
            f"{ignored_previous} XML(s) sobressalente(s) da última carga foram "
            "ignorados automaticamente."
        )

    xml_files = st.file_uploader(
        "Selecione os XMLs das NFs pendentes",
        type=["xml"],
        accept_multiple_files=True,
        key="pending_xml_link_files",
    )

    if not st.button(
        "VINCULAR XMLs ÀS PRÉ-NOTAS",
        type="primary",
        use_container_width=True,
        disabled=not bool(xml_files),
        key="link_pending_xmls",
    ):
        return

    groups = {}
    rejected = []
    ignored_xmls = 0
    file_store = dict(st.session_state.get("prefilter_files") or {})

    progress = st.progress(0, text="Vinculando XMLs...")
    for idx, xml_file in enumerate(xml_files, start=1):
        file_id = uuid.uuid4().hex[:16]
        raw = xml_file.getvalue()
        file_store[file_id] = {
            "name": xml_file.name,
            "ext": ".xml",
            "raw": raw,
        }

        try:
            xml_data = extract_nfe_processing_data(raw)
            identity = _xml_prefilter_identity(xml_data)
            match = match_document_to_pre_note(
                identity,
                pre_notes=pending_base,
            )

            if not match.get("matched"):
                nf_doc = normalized_nf(xml_data.get("numero_nf"))
                nf_candidates = pending_base[
                    pending_base["numero_nf"].map(normalized_nf).eq(nf_doc)
                ].copy()

                if nf_candidates.empty:
                    # A base define o universo de trabalho. XML cujo número de NF
                    # não existe na base é sobressalente e não gera tratativa.
                    ignored_xmls += 1
                    file_store.pop(file_id, None)
                else:
                    # O número da NF pertence ao universo válido; portanto este
                    # XML não pode ser descartado silenciosamente.
                    rejected.append({
                        "file_id": file_id,
                        "arquivo": xml_file.name,
                        "tipo": "XML",
                        "vinculado_base": True,
                        "nf": nf_doc,
                        "fornecedor": str(
                            xml_data.get("fornecedor_lido") or ""
                        ),
                        "motivo": str(
                            match.get("situacao")
                            or "XML NÃO VINCULADO À NF DA BASE"
                        ),
                        "aderencia_fornecedor": int(
                            match.get("score_fornecedor") or 0
                        ),
                    })
            else:
                pre_row = match["row"]
                group_key = pending_document_group_key(pre_row)
                group = groups.setdefault(
                    group_key,
                    {
                        "pre": pre_row,
                        "xmls": [],
                        "pdfs": [],
                    },
                )
                group["xmls"].append({
                    "file_id": file_id,
                    "name": xml_file.name,
                    "raw": raw,
                    "data": xml_data,
                    "score": int(
                        match.get("score_fornecedor") or 0
                    ),
                })
        except Exception:
            # Sem identificação segura não existe vínculo com a base; portanto
            # o arquivo é desconsiderado e não ocupa a fila de tratativas.
            ignored_xmls += 1
            file_store.pop(file_id, None)

        progress.progress(
            idx / max(1, len(xml_files)),
            text=f"Vinculando {idx}/{len(xml_files)} — {xml_file.name}",
        )

    progress.empty()

    # Uma única versão de XML por Pré-nota. Repetições são sobressalentes:
    # usa a melhor correspondência e descarta as demais sem gerar pendência.
    for group in groups.values():
        if len(group["xmls"]) > 1:
            group["xmls"].sort(
                key=lambda item: item.get("score", 0),
                reverse=True,
            )
            duplicates = group["xmls"][1:]
            ignored_xmls += len(duplicates)
            for duplicate in duplicates:
                file_store.pop(str(duplicate.get("file_id") or ""), None)
            group["xmls"] = group["xmls"][:1]

    rows = []
    stored_docs = {}
    for group in groups.values():
        try:
            row, stored = _build_hybrid_nf_document(group)
            rows.append(row)
            stored_docs[row["file_id"]] = stored
        except Exception as exc:
            source = (group.get("xmls") or [{}])[0]
            rejected.append({
                "file_id": str(source.get("file_id") or ""),
                "arquivo": str(source.get("name") or "XML"),
                "tipo": "PROCESSAMENTO",
                "vinculado_base": True,
                "nf": normalized_nf(
                    group["pre"].get("numero_nf")
                ),
                "fornecedor": pre_supplier_name(group["pre"]),
                "motivo": f"Falha ao preparar NF: {exc}",
                "aderencia_fornecedor": 0,
            })

    new_frame = pd.DataFrame(rows)
    if not new_frame.empty:
        new_frame["vencimento"] = pd.to_datetime(
            new_frame["vencimento"],
            errors="coerce",
        ).dt.date
        new_frame = apply_cross_checks(new_frame)
        new_frame = recalc(new_frame)

        current = st.session_state.analysis.copy()
        combined = (
            pd.concat([current, new_frame], ignore_index=True, sort=False)
            if isinstance(current, pd.DataFrame) and not current.empty
            else new_frame
        )
        dedupe_cols = [
            col for col in [
                "pre_nota_data",
                "numero_nf",
                "pre_nota_fornecedor",
            ]
            if col in combined.columns
        ]
        if dedupe_cols:
            combined = combined.drop_duplicates(
                dedupe_cols,
                keep="last",
            ).reset_index(drop=True)

        st.session_state.analysis = combined

    st.session_state.pdfs.update(stored_docs)
    st.session_state.prefilter_files = file_store
    st.session_state.prefilter_rejected = (
        list(st.session_state.get("prefilter_rejected") or [])
        + rejected
    )
    st.session_state.prefilter_stats = {
        "xml_enviados": len(xml_files),
        "notas_correspondentes": len(new_frame),
        "ignorados": ignored_xmls,
        "erros_vinculados": len(rejected),
    }

    st.session_state.pop("pending_xml_link_files", None)
    st.rerun()


def render_cte_linking_stage() -> None:
    st.markdown("### CT-e")
    st.caption(
        "Adicione os XMLs de CT-e depois que as NF-e já estiverem vinculadas. "
        "Somente CT-es que referenciem NFs do lote válido entram no fluxo; "
        "arquivos sobressalentes são ignorados automaticamente."
    )

    analysis = st.session_state.get("analysis")
    if not isinstance(analysis, pd.DataFrame) or analysis.empty:
        st.info("Vincule primeiro os XMLs das NF-e antes de adicionar CT-e.")
        return

    cte_files = st.file_uploader(
        "XMLs de CT-e",
        type=["xml"],
        accept_multiple_files=True,
        key="pending_cte_xml_files",
    )

    if st.button(
        "VINCULAR CT-e E GERAR DACTEs",
        type="primary",
        use_container_width=True,
        disabled=not bool(cte_files),
        key="link_cte_and_generate_dacte",
    ):
        links = list(st.session_state.get("cte_links") or [])
        existing_keys = {
            str(item.get("chave_cte") or "")
            for item in links
            if str(item.get("chave_cte") or "")
        }
        rejected = []
        generated = {}
        ignored_ctes = 0

        for cte_file in cte_files:
            raw = cte_file.getvalue()

            # Se o XML nem sequer puder ser identificado como CT-e, ele não faz
            # parte do universo definido pela base e é descartado silenciosamente.
            try:
                meta = extract_cte_metadata(raw)
            except Exception:
                ignored_ctes += 1
                continue

            if meta.chave and meta.chave in existing_keys:
                ignored_ctes += 1
                continue

            refs = [digits_only(value) for value in (meta.refs_nfe or [])]
            refs = [value for value in refs if len(value) == 44]
            if not refs:
                ignored_ctes += 1
                continue

            linked_rows = []

            for ref_key in refs:
                row_match = pd.DataFrame()

                # Primeiro tenta a chave exata da NF-e.
                if "chave_nfe" in analysis.columns:
                    key_series = (
                        analysis["chave_nfe"]
                        .fillna("")
                        .astype(str)
                        .map(digits_only)
                    )
                    row_match = analysis[key_series.eq(ref_key)].copy()

                # Compatibilidade para documentos em que a chave completa não
                # esteja disponível no DataFrame: NF + CNPJ do emitente.
                if row_match.empty:
                    nf_number = ""
                    supplier_cnpj = ""
                    if len(ref_key) == 44:
                        raw_nf = ref_key[25:34]
                        nf_number = (
                            str(int(raw_nf))
                            if raw_nf.isdigit()
                            else raw_nf
                        )
                        supplier_cnpj = ref_key[6:20]

                    candidates = analysis[
                        analysis.get(
                            "numero_nf",
                            pd.Series("", index=analysis.index),
                        )
                        .fillna("")
                        .astype(str)
                        .map(normalized_nf)
                        .eq(normalized_nf(nf_number))
                    ].copy()

                    if (
                        not candidates.empty
                        and supplier_cnpj
                        and "cnpj_fornecedor" in candidates.columns
                    ):
                        cnpj_series = (
                            candidates["cnpj_fornecedor"]
                            .fillna("")
                            .astype(str)
                            .map(digits_only)
                        )
                        exact_supplier = candidates[
                            cnpj_series.eq(supplier_cnpj)
                        ].copy()
                        if not exact_supplier.empty:
                            candidates = exact_supplier

                    if len(candidates) == 1:
                        row_match = candidates

                if len(row_match) == 1:
                    linked_rows.append(row_match.iloc[0].to_dict())
                # Referências a NFs fora do lote são simplesmente ignoradas.

            unique_rows = {}
            for row in linked_rows:
                row_id = str(row.get("file_id") or "")
                if row_id:
                    unique_rows[row_id] = row
            linked_rows = list(unique_rows.values())

            # CT-e totalmente fora do universo da carga: sobressalente.
            if not linked_rows:
                ignored_ctes += 1
                continue

            # A partir daqui o CT-e pertence ao lote. Qualquer erro real passa
            # a ser tratado porque afeta uma NF válida da base.
            try:
                if meta.status_codigo and meta.status_codigo != "100":
                    raise ValueError(
                        f"CT-e {meta.numero} não autorizado: "
                        f"{meta.status_codigo} - {meta.status_motivo}"
                    )

                dacte_bytes = generate_dacte_pdf(raw)
                nf_numbers = [
                    normalized_nf(row.get("numero_nf"))
                    for row in linked_rows
                    if normalized_nf(row.get("numero_nf"))
                ]
                suppliers = {
                    str(row.get("fornecedor_padrao") or "").strip()
                    for row in linked_rows
                    if str(row.get("fornecedor_padrao") or "").strip()
                }
                supplier_name = (
                    next(iter(suppliers))
                    if len(suppliers) == 1
                    else "MULTIPLOS FORNECEDORES"
                )
                final_name = cte_output_name(
                    meta,
                    nf_numbers,
                    supplier_name,
                )

                cte_id = uuid.uuid4().hex[:16]
                item = {
                    "cte_id": cte_id,
                    "chave_cte": meta.chave,
                    "numero_cte": meta.numero,
                    "serie_cte": meta.serie,
                    "transportadora": meta.emitente,
                    "cnpj_transportadora": meta.cnpj_emitente,
                    "arquivo_original": cte_file.name,
                    "arquivo_final": final_name,
                    "bytes": dacte_bytes,
                    "linked_file_ids": [
                        str(row.get("file_id") or "")
                        for row in linked_rows
                        if str(row.get("file_id") or "")
                    ],
                    "linked_nf_numbers": nf_numbers,
                    "refs_nfe": refs,
                }
                links.append(item)
                existing_keys.add(meta.chave)
                generated[cte_id] = item

            except Exception as exc:
                rejected.append({
                    "arquivo": cte_file.name,
                    "tipo": "CT-e",
                    "motivo": str(exc),
                })

        st.session_state.cte_links = links
        st.session_state.cte_outputs.update(generated)
        st.session_state.cte_rejected = rejected
        st.session_state.cte_ignored_count = ignored_ctes
        st.session_state.pop("pending_cte_xml_files", None)
        st.rerun()

    links = list(st.session_state.get("cte_links") or [])
    rejected = list(st.session_state.get("cte_rejected") or [])
    ignored_ctes = int(st.session_state.get("cte_ignored_count") or 0)

    if links:
        view = pd.DataFrame([
            {
                "CT-e": item.get("numero_cte"),
                "Transportadora": item.get("transportadora"),
                "NFs vinculadas": ", ".join(item.get("linked_nf_numbers") or []),
                "Arquivo": item.get("arquivo_final"),
            }
            for item in links
        ])
        st.success(f"{len(links)} CT-e(s) vinculado(s) e DACTE(s) gerado(s).")
        st.dataframe(
            view,
            use_container_width=True,
            hide_index=True,
        )

        dacte_buffer = io.BytesIO()
        with zipfile.ZipFile(
            dacte_buffer,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as dacte_zip:
            for item in links:
                name = str(item.get("arquivo_final") or "").strip()
                payload = item.get("bytes")
                if name and payload:
                    dacte_zip.writestr(name, payload)

        st.download_button(
            "BAIXAR DACTEs PARA CONFERÊNCIA",
            dacte_buffer.getvalue(),
            file_name=f"DACTEs_{now_local():%Y%m%d_%H%M%S}.zip",
            mime="application/zip",
            use_container_width=True,
            key="download_dactes_preview",
        )

    if ignored_ctes:
        st.caption(
            f"{ignored_ctes} CT-e(s) sobressalente(s) foram ignorados automaticamente."
        )

    if rejected:
        st.error(
            f"{len(rejected)} CT-e(s) vinculados ao lote precisam de atenção antes da geração final."
        )
        st.dataframe(
            pd.DataFrame(rejected),
            use_container_width=True,
            hide_index=True,
            column_config={
                "arquivo": st.column_config.TextColumn("Arquivo", width="large"),
                "tipo": "Tipo",
                "motivo": st.column_config.TextColumn(
                    "Motivo",
                    width="large",
                ),
            },
        )


def _pdf_document_keys(text: str) -> list[str]:
    """Extrai chaves fiscais de 44 dígitos preservando NF-e (55) e CT-e (57)."""
    keys = []
    seen = set()
    patterns = [
        r"(?<!\d)(?:\d[\s\.\-]*){44}(?!\d)",
        r"\b\d{44}\b",
    ]
    for pattern in patterns:
        for match in re.finditer(pattern, str(text or "")):
            key = digits_only(match.group(0))
            if len(key) == 44 and key not in seen:
                seen.add(key)
                keys.append(key)
    return keys


def _analysis_rows_for_nfe_keys(
    analysis: pd.DataFrame,
    nfe_keys: list[str],
) -> list[dict]:
    if not isinstance(analysis, pd.DataFrame) or analysis.empty:
        return []

    linked = {}
    key_series = (
        analysis.get("chave_nfe", pd.Series("", index=analysis.index))
        .fillna("")
        .astype(str)
        .map(digits_only)
    )
    number_series = (
        analysis.get("numero_nf", pd.Series("", index=analysis.index))
        .fillna("")
        .astype(str)
        .map(normalized_nf)
    )
    cnpj_series = (
        analysis.get("cnpj_fornecedor", pd.Series("", index=analysis.index))
        .fillna("")
        .astype(str)
        .map(digits_only)
    )

    for ref_key in nfe_keys:
        ref = digits_only(ref_key)
        if len(ref) != 44 or ref[20:22] != "55":
            continue

        hit = analysis[key_series.eq(ref)].copy()
        if hit.empty:
            raw_nf = ref[25:34]
            nf = str(int(raw_nf)) if raw_nf.isdigit() else raw_nf
            supplier_cnpj = ref[6:20]
            candidates = analysis[number_series.eq(normalized_nf(nf))].copy()
            if not candidates.empty and supplier_cnpj:
                exact = candidates[
                    cnpj_series.loc[candidates.index].eq(supplier_cnpj)
                ].copy()
                if not exact.empty:
                    candidates = exact
            if len(candidates) == 1:
                hit = candidates

        if len(hit) == 1:
            row = hit.iloc[0].to_dict()
            row_id = str(row.get("file_id") or "")
            if row_id:
                linked[row_id] = row

    return list(linked.values())


def _analysis_rows_for_cte_pdf(
    analysis: pd.DataFrame,
    text: str,
) -> list[dict]:
    keys = _pdf_document_keys(text)
    nfe_keys = [key for key in keys if key[20:22] == "55"]
    linked = _analysis_rows_for_nfe_keys(analysis, nfe_keys)
    if linked:
        return linked

    # Fallback somente quando o DACTE não expõe a chave da NF-e como texto.
    # Usa números explicitamente identificados como NF no documento.
    normalized = normalize_text(text)
    nf_numbers = {
        normalized_nf(value)
        for value in re.findall(
            r"\bNF(?:-E)?\s*(?:N[Oº°\.]?\s*)?0*(\d{1,9})\b",
            normalized,
            flags=re.IGNORECASE,
        )
        if normalized_nf(value)
    }
    if not nf_numbers:
        return []

    rows = {}
    series = (
        analysis.get("numero_nf", pd.Series("", index=analysis.index))
        .fillna("")
        .astype(str)
        .map(normalized_nf)
    )
    for nf in nf_numbers:
        hit = analysis[series.eq(nf)].copy()
        if len(hit) == 1:
            row = hit.iloc[0].to_dict()
            row_id = str(row.get("file_id") or "")
            if row_id:
                rows[row_id] = row
    return list(rows.values())


def render_document_linking_stage() -> None:
    st.markdown("### Documentos fiscais")
    st.caption(
        "Envie em um único campo XMLs e PDFs de NF-e e CT-e. O aplicativo separa "
        "automaticamente os tipos e mantém somente documentos vinculados às NFs "
        "válidas da base principal."
    )

    if not st.session_state.get("base_analysis_ready"):
        st.info(
            "Primeiro execute a análise dos relatórios em Processamento de arquivos."
        )
        return

    missing = _refresh_missing_mrp_analysis()
    if not missing.empty:
        st.info(
            "Resolva primeiro as NFs do MRP sem correspondência segura nas Pré-notas. "
            "Depois disso a vinculação documental será liberada."
        )
        return

    pending_base = current_pending_pre_notes()
    if pending_base.empty:
        st.success("Não há NFs pendentes aguardando documentos.")
        return

    uploaded = st.file_uploader(
        "XMLs e PDFs de NF-e / CT-e",
        type=["xml", "pdf"],
        accept_multiple_files=True,
        key="pending_fiscal_documents",
    )

    process_documents = st.button(
        "ANALISAR E VINCULAR DOCUMENTOS",
        type="primary",
        use_container_width=True,
        disabled=not bool(uploaded),
        key="process_fiscal_documents",
    )
    auto_reprocess = bool(
        uploaded
        and st.session_state.get("document_reprocess_needed")
    )

    if process_documents or auto_reprocess:
        st.session_state.document_reprocess_needed = False
        nf_candidates = []
        cte_candidates = []
        ignored = 0
        nf_rejected = []
        cte_rejected = []
        groups = {}
        file_store = dict(st.session_state.get("prefilter_files") or {})

        progress = st.progress(0, text="Classificando documentos...")

        for idx, file in enumerate(uploaded, start=1):
            raw = file.getvalue()
            ext = Path(file.name).suffix.lower()
            file_id = uuid.uuid4().hex[:16]

            if ext == ".xml":
                # CT-e primeiro: o parser valida explicitamente a raiz do modelo 57.
                try:
                    meta = extract_cte_metadata(raw)
                    cte_candidates.append({
                        "file_id": file_id,
                        "name": file.name,
                        "ext": ext,
                        "raw": raw,
                        "source": "XML",
                        "meta": meta,
                    })
                    progress.progress(
                        idx / max(1, len(uploaded)),
                        text=f"Classificando {idx}/{len(uploaded)} — {file.name}",
                    )
                    continue
                except Exception:
                    pass

                try:
                    xml_data = extract_nfe_processing_data(raw)
                    nf_candidates.append({
                        "file_id": file_id,
                        "name": file.name,
                        "ext": ext,
                        "raw": raw,
                        "source": "XML",
                        "data": xml_data,
                    })
                except Exception:
                    ignored += 1

            elif ext == ".pdf":
                try:
                    text, reading_method = extract_pdf_text(
                        raw,
                        ocr_fallback=False,
                    )
                except Exception:
                    ignored += 1
                    progress.progress(
                        idx / max(1, len(uploaded)),
                        text=f"Classificando {idx}/{len(uploaded)} — {file.name}",
                    )
                    continue

                normalized = normalize_text(text)
                is_cte = (
                    "DACTE" in normalized
                    or "CONHECIMENTO DE TRANSPORTE ELETRONICO" in normalized
                )
                if is_cte:
                    cte_candidates.append({
                        "file_id": file_id,
                        "name": file.name,
                        "ext": ext,
                        "raw": raw,
                        "source": "PDF",
                        "text": text,
                        "reading_method": reading_method,
                    })
                else:
                    nf_candidates.append({
                        "file_id": file_id,
                        "name": file.name,
                        "ext": ext,
                        "raw": raw,
                        "source": "PDF",
                    })
            else:
                ignored += 1

            progress.progress(
                idx / max(1, len(uploaded)),
                text=f"Classificando {idx}/{len(uploaded)} — {file.name}",
            )

        # 1) NF-e primeiro, pois os CT-es dependem das NF-e já vinculadas.
        for item in nf_candidates:
            file_id = item["file_id"]
            file_store[file_id] = {
                "name": item["name"],
                "ext": item["ext"],
                "raw": item["raw"],
            }

            if item["source"] == "XML":
                xml_data = item["data"]
                identity = _xml_prefilter_identity(xml_data)
                match = match_document_to_pre_note(
                    identity,
                    pre_notes=pending_base,
                )
                nf_doc = normalized_nf(xml_data.get("numero_nf"))

                if not match.get("matched"):
                    nf_hits = pending_base[
                        pending_base["numero_nf"].map(normalized_nf).eq(nf_doc)
                    ].copy()
                    if nf_hits.empty:
                        ignored += 1
                        file_store.pop(file_id, None)
                    else:
                        nf_rejected.append({
                            "file_id": file_id,
                            "arquivo": item["name"],
                            "tipo": "NF-e XML",
                            "vinculado_base": True,
                            "nf": nf_doc,
                            "fornecedor": str(
                                xml_data.get("fornecedor_lido") or ""
                            ),
                            "motivo": str(
                                match.get("situacao")
                                or "XML NÃO VINCULADO À NF DA BASE"
                            ),
                            "aderencia_fornecedor": int(
                                match.get("score_fornecedor") or 0
                            ),
                        })
                    continue

                pre_row = match["row"]
                key = pending_document_group_key(pre_row)
                group = groups.setdefault(
                    key,
                    {"pre": pre_row, "xmls": [], "pdfs": []},
                )
                group["xmls"].append({
                    "file_id": file_id,
                    "name": item["name"],
                    "raw": item["raw"],
                    "data": xml_data,
                    "score": int(match.get("score_fornecedor") or 0),
                })
                continue

            # NF-e em PDF.
            identity = inspect_nf_pdf_identity(
                item["name"],
                item["raw"],
                st.session_state.suppliers,
            )
            match = match_document_to_pre_note(
                identity,
                pre_notes=pending_base,
            )
            nf_doc = normalized_nf(identity.get("numero_nf"))

            if not match.get("matched"):
                nf_hits = pending_base[
                    pending_base["numero_nf"].map(normalized_nf).eq(nf_doc)
                ].copy() if nf_doc else pd.DataFrame()
                if nf_hits.empty:
                    ignored += 1
                    file_store.pop(file_id, None)
                else:
                    nf_rejected.append({
                        "file_id": file_id,
                        "arquivo": item["name"],
                        "tipo": "NF-e PDF",
                        "vinculado_base": True,
                        "nf": nf_doc,
                        "fornecedor": str(
                            identity.get("fornecedor_lido")
                            or identity.get("fornecedor_padrao")
                            or ""
                        ),
                        "motivo": str(
                            match.get("situacao")
                            or "PDF NÃO VINCULADO À NF DA BASE"
                        ),
                        "aderencia_fornecedor": int(
                            match.get("score_fornecedor") or 0
                        ),
                    })
                continue

            pre_row = match["row"]
            key = pending_document_group_key(pre_row)
            group = groups.setdefault(
                key,
                {"pre": pre_row, "xmls": [], "pdfs": []},
            )
            group["pdfs"].append({
                "file_id": file_id,
                "name": item["name"],
                "raw": item["raw"],
                "identity": identity,
                "score": int(match.get("score_fornecedor") or 0),
            })

        # Mantém somente uma versão por tipo para cada NF.
        for group in groups.values():
            for doc_type in ("xmls", "pdfs"):
                docs = group[doc_type]
                if len(docs) > 1:
                    docs.sort(
                        key=lambda value: value.get("score", 0),
                        reverse=True,
                    )
                    extras = docs[1:]
                    ignored += len(extras)
                    for extra in extras:
                        file_store.pop(
                            str(extra.get("file_id") or ""),
                            None,
                        )
                    group[doc_type] = docs[:1]

        rows = []
        stored_docs = {}
        for group in groups.values():
            try:
                row, stored = _build_hybrid_nf_document(group)
                rows.append(row)
                stored_docs[row["file_id"]] = stored
            except Exception as exc:
                source = (
                    (group.get("xmls") or group.get("pdfs") or [{}])[0]
                )
                nf_rejected.append({
                    "file_id": str(source.get("file_id") or ""),
                    "arquivo": str(source.get("name") or "Documento"),
                    "tipo": "PROCESSAMENTO NF-e",
                    "vinculado_base": True,
                    "nf": normalized_nf(
                        group["pre"].get("numero_nf")
                    ),
                    "fornecedor": pre_supplier_name(group["pre"]),
                    "motivo": f"Falha ao preparar NF: {exc}",
                    "aderencia_fornecedor": 0,
                })

        new_frame = pd.DataFrame(rows)
        if not new_frame.empty:
            new_frame["vencimento"] = pd.to_datetime(
                new_frame["vencimento"],
                errors="coerce",
            ).dt.date
            new_frame = apply_cross_checks(new_frame)
            new_frame = recalc(new_frame)

            current = st.session_state.analysis.copy()
            combined = (
                pd.concat(
                    [current, new_frame],
                    ignore_index=True,
                    sort=False,
                )
                if isinstance(current, pd.DataFrame) and not current.empty
                else new_frame
            )
            dedupe_cols = [
                col
                for col in [
                    "pre_nota_data",
                    "numero_nf",
                    "pre_nota_fornecedor",
                ]
                if col in combined.columns
            ]
            if dedupe_cols:
                combined = combined.drop_duplicates(
                    dedupe_cols,
                    keep="last",
                ).reset_index(drop=True)
            st.session_state.analysis = combined

        st.session_state.pdfs.update(stored_docs)
        st.session_state.prefilter_files = file_store

        # 2) CT-e depois que o lote de NF-e já está atualizado.
        analysis = st.session_state.analysis.copy()
        links = list(st.session_state.get("cte_links") or [])
        existing_cte_keys = {
            str(item.get("chave_cte") or "")
            for item in links
            if str(item.get("chave_cte") or "")
        }

        for item in cte_candidates:
            if not isinstance(analysis, pd.DataFrame) or analysis.empty:
                ignored += 1
                continue

            linked_rows = []
            meta = item.get("meta")

            if item["source"] == "XML":
                refs = [
                    digits_only(value)
                    for value in (meta.refs_nfe or [])
                ]
                refs = [
                    value
                    for value in refs
                    if len(value) == 44 and value[20:22] == "55"
                ]
                linked_rows = _analysis_rows_for_nfe_keys(
                    analysis,
                    refs,
                )
                if not linked_rows:
                    ignored += 1
                    continue

                try:
                    if meta.status_codigo and meta.status_codigo != "100":
                        raise ValueError(
                            f"CT-e {meta.numero} não autorizado: "
                            f"{meta.status_codigo} - {meta.status_motivo}"
                        )

                    if meta.chave and meta.chave in existing_cte_keys:
                        ignored += 1
                        continue

                    payload = generate_dacte_pdf(item["raw"])
                    nf_numbers = [
                        normalized_nf(row.get("numero_nf"))
                        for row in linked_rows
                        if normalized_nf(row.get("numero_nf"))
                    ]
                    suppliers = {
                        str(row.get("fornecedor_padrao") or "").strip()
                        for row in linked_rows
                        if str(row.get("fornecedor_padrao") or "").strip()
                    }
                    supplier_name = (
                        next(iter(suppliers))
                        if len(suppliers) == 1
                        else "MULTIPLOS FORNECEDORES"
                    )
                    final_name = cte_output_name(
                        meta,
                        nf_numbers,
                        supplier_name,
                    )
                    chave_cte = meta.chave
                    numero_cte = meta.numero
                    transportadora = meta.emitente
                    cnpj_transportadora = meta.cnpj_emitente
                    refs_nfe = refs
                except Exception as exc:
                    cte_rejected.append({
                        "arquivo": item["name"],
                        "tipo": "CT-e XML",
                        "motivo": str(exc),
                    })
                    continue

            else:
                text = str(item.get("text") or "")
                linked_rows = _analysis_rows_for_cte_pdf(
                    analysis,
                    text,
                )
                if not linked_rows:
                    ignored += 1
                    continue

                keys = _pdf_document_keys(text)
                cte_keys = [
                    key for key in keys
                    if len(key) == 44 and key[20:22] == "57"
                ]
                chave_cte = cte_keys[0] if cte_keys else ""
                if chave_cte and chave_cte in existing_cte_keys:
                    ignored += 1
                    continue

                numero_cte = ""
                cnpj_transportadora = ""
                if chave_cte:
                    raw_num = chave_cte[25:34]
                    numero_cte = (
                        str(int(raw_num))
                        if raw_num.isdigit()
                        else raw_num
                    )
                    cnpj_transportadora = chave_cte[6:20]
                if not numero_cte:
                    match_number = re.search(
                        r"CT-?E\s*(?:N[Oº°\.]?\s*)?0*(\d{1,9})",
                        normalize_text(text),
                        flags=re.IGNORECASE,
                    )
                    if match_number:
                        numero_cte = normalized_nf(
                            match_number.group(1)
                        )

                payload = item["raw"]
                final_name = item["name"]
                transportadora = ""
                refs_nfe = [
                    key for key in keys
                    if len(key) == 44 and key[20:22] == "55"
                ]

            nf_numbers = [
                normalized_nf(row.get("numero_nf"))
                for row in linked_rows
                if normalized_nf(row.get("numero_nf"))
            ]
            cte_id = uuid.uuid4().hex[:16]
            link = {
                "cte_id": cte_id,
                "chave_cte": chave_cte,
                "numero_cte": numero_cte,
                "serie_cte": (
                    meta.serie
                    if item["source"] == "XML"
                    else ""
                ),
                "transportadora": transportadora,
                "cnpj_transportadora": cnpj_transportadora,
                "arquivo_original": item["name"],
                "arquivo_final": final_name,
                "bytes": payload,
                "linked_file_ids": [
                    str(row.get("file_id") or "")
                    for row in linked_rows
                    if str(row.get("file_id") or "")
                ],
                "linked_nf_numbers": nf_numbers,
                "refs_nfe": refs_nfe,
                "origem": item["source"],
            }
            links.append(link)
            if chave_cte:
                existing_cte_keys.add(chave_cte)

        st.session_state.cte_links = links
        st.session_state.cte_rejected = cte_rejected
        st.session_state.prefilter_rejected = nf_rejected
        st.session_state.prefilter_stats = {
            "enviados": len(uploaded),
            "nf_classificados": len(nf_candidates),
            "cte_classificados": len(cte_candidates),
            "nf_vinculados": len(new_frame),
            "cte_vinculados": len(links),
            "ignorados": ignored,
            "erros_nf_vinculados": len(nf_rejected),
            "erros_cte_vinculados": len(cte_rejected),
        }
        st.session_state.document_link_stats = dict(
            st.session_state.prefilter_stats
        )
        progress.empty()
        st.rerun()

    stats = st.session_state.get("document_link_stats") or {}
    analysis = st.session_state.get("analysis")
    cte_links = list(st.session_state.get("cte_links") or [])

    if isinstance(analysis, pd.DataFrame) and not analysis.empty:
        st.markdown("#### NF-e vinculadas")
        nf_cols = [
            col for col in [
                "numero_nf",
                "fornecedor_padrao",
                "origem_dados",
                "arquivo_original",
                "status",
            ]
            if col in analysis.columns
        ]
        st.dataframe(
            analysis[nf_cols],
            use_container_width=True,
            hide_index=True,
            column_config={
                "numero_nf": "NF",
                "fornecedor_padrao": st.column_config.TextColumn(
                    "Fornecedor",
                    width="large",
                ),
                "origem_dados": "Origem",
                "arquivo_original": st.column_config.TextColumn(
                    "Arquivo",
                    width="large",
                ),
                "status": "Status",
            },
        )

    if cte_links:
        st.markdown("#### CT-e vinculados")
        cte_view = pd.DataFrame([
            {
                "CT-e": item.get("numero_cte") or "",
                "Origem": item.get("origem") or "XML",
                "NFs vinculadas": ", ".join(
                    item.get("linked_nf_numbers") or []
                ),
                "Arquivo": item.get("arquivo_original") or "",
            }
            for item in cte_links
        ])
        st.dataframe(
            cte_view,
            use_container_width=True,
            hide_index=True,
            column_config={
                "CT-e": "CT-e",
                "Origem": "Origem",
                "NFs vinculadas": st.column_config.TextColumn(
                    "NFs vinculadas",
                    width="large",
                ),
                "Arquivo": st.column_config.TextColumn(
                    "Arquivo",
                    width="large",
                ),
            },
        )

    ignored_count = int(stats.get("ignorados") or 0)
    if ignored_count:
        st.caption(
            f"{ignored_count} arquivo(s) sem vínculo com a base principal "
            "foram desconsiderados automaticamente."
        )

    if st.session_state.get("cte_rejected"):
        st.error(
            f"{len(st.session_state.cte_rejected)} CT-e(s) vinculados à base "
            "precisam de correção."
        )


def render_file_processing():
    st.markdown(
        '<div class="section-title">Processamento de arquivos</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Etapa 1 — alimente somente os relatórios-base. O aplicativo identifica "
        "as pré-notas pendentes, verifica NFs ausentes no confronto MRP e calcula "
        "as prioridades. Os XMLs só entram depois, em Pré-notas pendentes."
    )

    with st.container(border=True):
        st.markdown("#### Relatórios-base")
        r1, r2, r3 = st.columns(3)
        pre_file = r1.file_uploader(
            "Pré-notas",
            type=["csv", "xlsx", "xls", "xlt", "xltx"],
            key="base_pre_file",
        )
        material_file = r2.file_uploader(
            "Materiais",
            type=["xlsx", "xltx", "xls", "csv"],
            key="base_material_file",
        )
        nf_file = r3.file_uploader(
            "NFs / STSUP01",
            type=["xlsx", "xltx", "xls", "csv"],
            key="base_nf_file",
        )

        supplier_file = st.file_uploader(
            "Fornecedores — opcional",
            type=["csv", "xlsx", "xls", "xlt", "xltx"],
            key="base_supplier_file",
            help="Se não selecionar, será usada a base de fornecedores já cadastrada.",
        )

    ready = bool(pre_file and material_file and nf_file)
    analyze_bases = st.button(
        "ANALISAR BASES",
        type="primary",
        use_container_width=True,
        disabled=not ready,
        key="analyze_base_reports",
    )

    if analyze_bases:
        # Uma nova análise de base invalida qualquer lote documental anterior.
        st.session_state.analysis = pd.DataFrame()
        st.session_state.pdfs = {}
        st.session_state.zip_outputs = {}
        st.session_state.prefilter_rejected = []
        st.session_state.prefilter_resolved = []
        st.session_state.prefilter_files = {}
        st.session_state.prefilter_stats = {}
        st.session_state.cte_links = []
        st.session_state.cte_rejected = []
        st.session_state.cte_outputs = {}
        st.session_state.cte_ignored_count = 0
        st.session_state.document_link_stats = {}
        st.session_state.document_upload_cache = []
        st.session_state.document_reprocess_needed = False
        st.session_state.pop("pending_fiscal_documents", None)
        st.session_state.current_test_manifest = []
        st.session_state.base_analysis_ready = False
        st.session_state.base_analysis_missing_mrp = pd.DataFrame()

        try:
            with st.spinner("Analisando relatórios e calculando o impacto MRP..."):
                # Fornecedores: atualização opcional antes dos cruzamentos.
                if supplier_file:
                    raw_sup, _ = read_uploaded_table(supplier_file, header_row=None)
                    if raw_sup.shape[1] < 15:
                        raise ValueError(
                            "O relatório FORNECEDORES precisa conter pelo menos as colunas A até O."
                        )

                    incoming = pd.DataFrame({
                        "codigo": raw_sup.iloc[:, 0].fillna("").astype(str).str.strip(),
                        "loja": raw_sup.iloc[:, 1].fillna("").astype(str).str.strip(),
                        "nome_padrao": raw_sup.iloc[:, 2].fillna("").astype(str).str.strip(),
                        "nome_fantasia": raw_sup.iloc[:, 3].fillna("").astype(str).str.strip(),
                        "tipo": raw_sup.iloc[:, 10].fillna("").astype(str).str.strip(),
                        "cnpj": raw_sup.iloc[:, 14].map(digits_only),
                    })
                    incoming = incoming[
                        ~incoming["cnpj"].map(normalize_text).str.contains("CNPJ", na=False)
                    ].copy()
                    incoming["aliases"] = incoming["nome_fantasia"]
                    incoming["ativo"] = True

                    valid_sup = incoming[
                        incoming["cnpj"].map(valid_cnpj)
                        & incoming["nome_padrao"].ne("")
                    ].copy()

                    preferred_rows = []
                    conflict_cnpjs = []
                    for cnpj, group in valid_sup.groupby("cnpj", sort=False):
                        if len(group) == 1:
                            preferred_rows.append(group.iloc[0])
                            continue

                        compact_names = [
                            re.sub(r"[^A-Z0-9]", "", normalize_text(name))
                            for name in group["nome_padrao"].tolist()
                        ]
                        base_name = min(compact_names, key=len)
                        equivalent = all(
                            name == base_name
                            or name.startswith(base_name)
                            or base_name.startswith(name)
                            for name in compact_names
                        )
                        if equivalent:
                            chosen_idx = group["nome_padrao"].map(
                                lambda value: len(normalize_text(value))
                            ).idxmin()
                            preferred_rows.append(group.loc[chosen_idx])
                        else:
                            conflict_cnpjs.append(cnpj)

                    if conflict_cnpjs:
                        raise ValueError(
                            f"A base de fornecedores possui {len(conflict_cnpjs)} CNPJ(s) "
                            "com razões sociais conflitantes."
                        )
                    if not preferred_rows:
                        raise ValueError(
                            "Nenhum fornecedor válido foi encontrado no relatório."
                        )

                    clean_sup = pd.DataFrame(preferred_rows).copy()
                    final_sup = supplier_dataframe(
                        clean_sup[
                            [
                                "cnpj", "nome_padrao", "aliases", "ativo",
                                "codigo", "loja", "nome_fantasia", "tipo",
                            ]
                        ]
                    )
                    if db.configured():
                        db.replace_suppliers(
                            final_sup.to_dict("records"),
                            supplier_file.name,
                            {
                                "total": len(incoming),
                                "validos": len(final_sup),
                                "invalidos": int(
                                    (
                                        ~incoming["cnpj"].map(valid_cnpj)
                                        | incoming["nome_padrao"].eq("")
                                    ).sum()
                                ),
                                "conflitos": 0,
                            },
                        )
                    st.session_state.suppliers = final_sup

                # Pré-notas.
                temp_pre, _ = read_uploaded_table(pre_file, header_row=None)
                if temp_pre.shape[1] < 6:
                    raise ValueError(
                        "O relatório de Pré-notas precisa conter pelo menos as colunas A até F."
                    )

                normalized_pre = pd.DataFrame({
                    "data_pre_nota": pd.to_datetime(
                        temp_pre.iloc[:, 0],
                        errors="coerce",
                        dayfirst=True,
                    ).dt.date,
                    "recebedor": temp_pre.iloc[:, 1].fillna("").astype(str).str.strip(),
                    "numero_nf": temp_pre.iloc[:, 2].map(normalized_nf),
                    "fornecedor": temp_pre.iloc[:, 3].fillna("").astype(str).str.strip(),
                    "cnpj": temp_pre.iloc[:, 4].map(digits_only),
                    "status": temp_pre.iloc[:, 5].fillna("").astype(str).str.strip(),
                })
                normalized_pre["status_normalizado"] = normalized_pre["status"].map(
                    normalize_text
                )
                pre_valid = normalized_pre[
                    normalized_pre["status_normalizado"].eq("PRE-NOTA LANCADA")
                    & normalized_pre["numero_nf"].ne("")
                    & normalized_pre["fornecedor"].ne("")
                    & normalized_pre["data_pre_nota"].notna()
                ].copy()
                pre_valid = (
                    pre_valid.sort_values(
                        ["data_pre_nota", "numero_nf"],
                        ascending=[False, True],
                        na_position="last",
                    )
                    .drop_duplicates(
                        ["data_pre_nota", "numero_nf", "fornecedor"],
                        keep="last",
                    )
                    .drop(columns=["status_normalizado"], errors="ignore")
                    .reset_index(drop=True)
                )
                if pre_valid.empty:
                    raise ValueError(
                        "Nenhuma Pré-nota lançada válida foi encontrada no relatório."
                    )

                st.session_state.pre_notes = pre_valid
                if SAVE_NF_HISTORY and db.configured():
                    persist_pre_notes_current(pre_file.name)

                # Impacto MRP.
                materials, mat_stats = _clean_mrp_materials_cached(
                    material_file.getvalue(),
                    material_file.name,
                )
                entries, nf_stats = _clean_mrp_nf_cached(
                    nf_file.getvalue(),
                    nf_file.name,
                    now_local().date().isoformat(),
                )
                detail, summary, impact_stats = _build_mrp_impact(
                    materials,
                    entries,
                )
                st.session_state.mrp_impact_detail = detail.copy()
                st.session_state.mrp_priority_summary = summary.copy()
                st.session_state.mrp_priority_stats = {
                    **mat_stats,
                    **nf_stats,
                    **impact_stats,
                }
                st.session_state.mrp_priority_files = (
                    material_file.name,
                    nf_file.name,
                )
                st.session_state.mrp_ignored_records = []

                high = (
                    summary[
                        summary["prioridade"]
                        .fillna("")
                        .astype(str)
                        .str.upper()
                        .eq("ALTA")
                    ].copy()
                    if isinstance(summary, pd.DataFrame) and not summary.empty
                    else pd.DataFrame()
                )
                st.session_state.priority_date_nf_keys = set(
                    high.get("data_nf", pd.Series(dtype=str))
                    .dropna().astype(str).tolist()
                )
                st.session_state.priority_nf_doc_keys = set()
                st.session_state.priority_nf_keys = set()
                st.session_state.priority_nf_numbers = set(
                    high.get("numero_nf", pd.Series(dtype=str))
                    .dropna().astype(str).tolist()
                )

                persisted_mrp = persist_mrp_current()
                if db.configured() and not bool(persisted_mrp.get("ok", False)):
                    raise RuntimeError(
                        "O Supabase não confirmou a gravação do cálculo MRP."
                    )

                # NFs existentes no MRP mas ausentes/divergentes nas Pré-notas.
                missing_rows = []
                if isinstance(summary, pd.DataFrame) and not summary.empty:
                    for _, mrp_row in summary.iterrows():
                        match = match_mrp_to_pre_note(mrp_row, pre_valid)
                        if not match.get("matched"):
                            item = mrp_row.to_dict()
                            item["situacao_vinculo"] = str(
                                match.get("situacao") or "AUSENTE NAS PRÉ-NOTAS"
                            )
                            item["score_fornecedor"] = int(
                                match.get("score_fornecedor") or 0
                            )
                            missing_rows.append(item)

                st.session_state.base_analysis_missing_mrp = pd.DataFrame(
                    missing_rows
                )
                st.session_state.base_analysis_ready = True
                st.session_state.base_analysis_at = now_local().isoformat(
                    timespec="seconds"
                )

            st.rerun()
        except Exception as exc:
            st.session_state.base_analysis_ready = False
            st.error(f"Não foi possível concluir a análise das bases: {exc}")

    if st.session_state.get("base_analysis_ready"):
        pending_count = len(current_pending_pre_notes())
        missing = st.session_state.get("base_analysis_missing_mrp")
        missing_count = (
            len(missing)
            if isinstance(missing, pd.DataFrame)
            else 0
        )
        summary = st.session_state.get("mrp_priority_summary")
        high_count = (
            int(
                summary["prioridade"]
                .fillna("")
                .astype(str)
                .str.upper()
                .eq("ALTA")
                .sum()
            )
            if isinstance(summary, pd.DataFrame) and not summary.empty
            else 0
        )

        st.success(
            f"Análise concluída: {pending_count} pré-nota(s) pendente(s), "
            f"{missing_count} NF(s) do MRP sem correspondência segura e "
            f"{high_count} NF(s) com prioridade ALTA. "
            "As tratativas e a vinculação dos XMLs ficam em Pré-notas pendentes."
        )


with st.sidebar:
    st.markdown(
        f'''<div class="sidebar-brand">
            <div class="sidebar-brand-title">{cfg["sidebar_title"]}</div>
            <div class="sidebar-brand-sub">{cfg["sidebar_subtitle"]}</div>
        </div>''',
        unsafe_allow_html=True,
    )
    st.markdown('<div class="sidebar-section-label">Navegação</div>', unsafe_allow_html=True)
    _pages = ["Dashboard", "Configurações"]
    if ENABLE_PENDING_REPORT:
        _pages.insert(1, "Pendências")
    _control_docs_label = str(cfg.get("control_docs_label") or DEFAULT["control_docs_label"]).strip()
    page = st.radio(
        "Página",
        _pages,
        label_visibility="collapsed",
        format_func=lambda item: (
            _control_docs_label.upper()
            if item == "Pendências"
            else str(item).upper()
        ),
    )
    st.divider()
    st.markdown('<div class="sidebar-section-label">Operador</div>', unsafe_allow_html=True)
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
    st.markdown('<div class="sidebar-section-label">Identidade visual</div>', unsafe_allow_html=True)
    st.markdown(f'<div class="sidebar-logo-preview">{logo_html()}</div>', unsafe_allow_html=True)
    st.caption("Logo, títulos e cores ficam em Configurações.")
    st.divider()
    status = db.db_status()
    db_text = "Conectado" if status["configured"] else "Aguardando chave"
    st.markdown('<div class="sidebar-section-label">Informações</div>', unsafe_allow_html=True)
    _mode_text = "TESTES — sem gravação no Supabase" if not SAVE_NF_HISTORY else "Produção"
    st.markdown(
        f'<div class="sidebar-info-card"><b>Data operacional</b><br>{now_local():%d/%m/%Y}<br><br><b>Banco de dados</b><br>{db_text}<br><br><b>Fluxo</b><br>NF-e / CT-e → conferência → ZIP<br><br><b>Modo</b><br>{_mode_text}<br><br><b>Versão</b><br>Protótipo 0.2</div>',
        unsafe_allow_html=True,
    )
    if st.session_state.get("db_sync_error"):
        st.warning("Falha na sincronização inicial do banco. Veja Configurações.")

st.markdown(f'<div class="setta-logo-card">{logo_html()}</div>', unsafe_allow_html=True)
st.markdown(
    f'<h1 class="app-title">{cfg["title"]} | SETTA</h1>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<p class="app-sub">{cfg["subtitle"]}</p>',
    unsafe_allow_html=True,
)


if page == "Dashboard":
    st.markdown('<div class="section-title">Dashboard operacional</div>', unsafe_allow_html=True)
    if not SAVE_NF_HISTORY:
        records = pd.DataFrame(st.session_state.get("current_test_manifest") or [])
        st.caption("Modo de testes: Dashboard considera somente a carga atual e ignora o histórico do banco.")
    elif db.configured():
        try:
            records = pd.DataFrame(db.list_process_records())
        except Exception as exc:
            st.error(f"Não foi possível consultar o histórico: {exc}")
            records = pd.DataFrame(st.session_state.history)
    else:
        records = pd.DataFrame(st.session_state.history)

    if records.empty:
        records = pd.DataFrame(columns=[
            "id", "processado_em", "tipo_documento", "numero_nf", "numero_cte",
            "fornecedor_padrao", "transportadora", "nfs_vinculadas", "empresa_sigla",
            "natureza", "vencimento", "pre_nota_status", "pre_nota_em",
            "prioridade_mrp", "status", "recebido_em", "pdf_criado_em",
            "enviado_em", "operador", "arquivo_final"
        ])

    # Timestamps do banco são gravados em UTC. Converte os eventos operacionais
    # para o horário local de Patos de Minas/São Paulo antes de exibir.
    for col in ["recebido_em", "pdf_criado_em", "enviado_em", "processado_em"]:
        if col in records.columns:
            records[col] = (
                pd.to_datetime(records[col], errors="coerce", utc=True)
                .dt.tz_convert(TZ)
                .dt.tz_localize(None)
            )
    # pre_nota_em representa uma data de negócio, não um instante UTC.
    if "pre_nota_em" in records.columns:
        records["pre_nota_em"] = pd.to_datetime(
            records["pre_nota_em"],
            errors="coerce",
        )

    # O Dashboard é somente consulta. A grade operacional exibe apenas NFs
    # cujo envio já foi confirmado na tela de Pré-notas.
    finalized_records = records.copy()
    if not finalized_records.empty:
        status_final = (
            finalized_records.get("status", pd.Series("", index=finalized_records.index))
            .fillna("")
            .astype(str)
            .str.upper()
            .eq("ENVIADO")
        )
        sent_at = finalized_records.get(
            "enviado_em",
            pd.Series(pd.NaT, index=finalized_records.index),
        ).notna()
        finalized_records = finalized_records[status_final | sent_at].copy()

    if "tipo_documento" not in records.columns:
        records["tipo_documento"] = "NF-e"

    type_norm = (
        records["tipo_documento"]
        .fillna("NF-e")
        .astype(str)
        .map(normalize_text)
    )
    is_cte = type_norm.str.contains("CTE", na=False)
    nf_records = records[~is_cte].copy()
    cte_records = records[is_cte].copy()

    nf_received = int(
        nf_records.get(
            "recebido_em",
            pd.Series(pd.NaT, index=nf_records.index),
        ).notna().sum()
    )
    cte_received = int(
        cte_records.get(
            "recebido_em",
            pd.Series(pd.NaT, index=cte_records.index),
        ).notna().sum()
    )
    nf_completed_status = (
        nf_records.get("status", pd.Series("", index=nf_records.index))
        .fillna("")
        .astype(str)
        .str.upper()
        .isin({"REALIZADO", "ENVIADO", "PDF CRIADO"})
    )
    linked_pre_note = nf_records.get(
        "pre_nota_em",
        pd.Series(pd.NaT, index=nf_records.index),
    ).notna()
    pre_done = int((nf_completed_status & linked_pre_note).sum())
    created = int(
        records.get(
            "pdf_criado_em",
            pd.Series(pd.NaT, index=records.index),
        ).notna().sum()
    )
    nf_sent = int(
        nf_records.get(
            "enviado_em",
            pd.Series(pd.NaT, index=nf_records.index),
        ).notna().sum()
    )
    cte_sent = int(
        cte_records.get(
            "enviado_em",
            pd.Series(pd.NaT, index=cte_records.index),
        ).notna().sum()
    )

    kpis = [
        ("NFs recebidas", nf_received, "Notas fiscais vinculadas", "#2563eb", "#dbeafe", True),
        ("CT-es vinculados", cte_received, "Conhecimentos no controle", "#7c3aed", "#ede9fe", False),
        ("Pré-notas realizadas", pre_done, "Vinculadas ao controle", "#d97706", "#ffedd5", False),
        ("Arquivos criados", created, "DANFEs + DACTEs", "#0891b2", "#cffafe", False),
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

    sent_cards = [
        ("NFs enviadas", nf_sent, "Envio confirmado", "#16a34a", "#dcfce7"),
        ("CT-es enviados", cte_sent, "Envio confirmado", "#15803d", "#dcfce7"),
    ]
    for col, item in zip(st.columns(2), sent_cards):
        label, value, delta, accent, soft = item
        col.markdown(
            f'<div class="kpi-card" style="--accent:{accent};--accent-soft:{soft};margin-top:.7rem">'
            f'<div class="kpi-header"><span class="kpi-dot"></span><span class="kpi-label">{label}</span></div>'
            f'<div class="kpi-value">{value}</div><div class="kpi-delta">{delta}</div></div>',
            unsafe_allow_html=True,
        )

    if not db.configured():
        st.caption("Persistência ainda não conectada neste deployment. Configure a chave do Supabase em Configurações.")

    st.markdown('<div class="section-title" style="margin-top:1.65rem!important;">Consulta de documentos finalizados</div>', unsafe_allow_html=True)
    st.caption(
        "Esta área é somente para consulta. O envio é confirmado em Geração de Arquivos → Pré-notas pendentes."
    )
    if finalized_records.empty:
        st.caption("Nenhum documento teve o envio confirmado até o momento.")
    else:
        ref_date = (
            pd.to_datetime(
                finalized_records.get("enviado_em"),
                errors="coerce",
            ).dt.date
            if "enviado_em" in finalized_records.columns
            else pd.to_datetime(
                finalized_records.get("processado_em"),
                errors="coerce",
            ).dt.date
        )
        min_d = min([d for d in ref_date.dropna().tolist()] or [date.today()])
        max_d = max([d for d in ref_date.dropna().tolist()] or [date.today()])

        f1, f2, f3, f4 = st.columns(4)
        start_date = f1.date_input("De", value=min_d)
        end_date = f2.date_input("Até", value=max_d)

        types = sorted(
            finalized_records.get(
                "tipo_documento",
                pd.Series("NF-e", index=finalized_records.index),
            )
            .fillna("NF-e")
            .astype(str)
            .unique()
            .tolist()
        )
        type_filter = f3.multiselect(
            "Tipo",
            types,
            default=types,
        )
        companies = sorted(
            finalized_records.get(
                "empresa_sigla",
                pd.Series(dtype=str),
            )
            .fillna("")
            .astype(str)
            .loc[lambda x: x.ne("")]
            .unique()
            .tolist()
        )
        company_filter = f4.multiselect(
            "Empresa",
            companies,
            default=companies,
        )

        finalized_records["parte"] = finalized_records.apply(
            lambda row: (
                str(row.get("transportadora") or "").strip()
                if "CTE" in normalize_text(row.get("tipo_documento"))
                else str(row.get("fornecedor_padrao") or "").strip()
            ),
            axis=1,
        )
        finalized_records["documento"] = finalized_records.apply(
            lambda row: (
                str(row.get("numero_cte") or "").strip()
                if "CTE" in normalize_text(row.get("tipo_documento"))
                else normalized_nf(row.get("numero_nf"))
            ),
            axis=1,
        )

        f5, f6 = st.columns(2)
        natures = sorted(
            finalized_records.get(
                "natureza",
                pd.Series(dtype=str),
            )
            .fillna("")
            .astype(str)
            .loc[lambda x: x.ne("")]
            .unique()
            .tolist()
        )
        nature_filter = f5.multiselect(
            "Natureza das NFs",
            natures,
            default=natures,
        )
        parties = sorted(
            finalized_records["parte"]
            .fillna("")
            .astype(str)
            .loc[lambda x: x.ne("")]
            .unique()
            .tolist()
        )
        party_filter = f6.multiselect(
            "Fornecedor / Transportadora",
            parties,
        )

        view = finalized_records.copy()
        mask_date = (ref_date >= start_date) & (ref_date <= end_date)
        view = view[mask_date]

        if type_filter:
            view = view[
                view["tipo_documento"]
                .fillna("NF-e")
                .astype(str)
                .isin(type_filter)
            ]
        if company_filter and "empresa_sigla" in view.columns:
            view = view[
                view["empresa_sigla"]
                .fillna("")
                .astype(str)
                .isin(company_filter)
            ]
        if nature_filter and "natureza" in view.columns:
            cte_mask = (
                view["tipo_documento"]
                .fillna("NF-e")
                .astype(str)
                .map(normalize_text)
                .str.contains("CTE", na=False)
            )
            view = view[
                cte_mask
                | view["natureza"].fillna("").astype(str).isin(nature_filter)
            ]
        if party_filter:
            view = view[view["parte"].isin(party_filter)]

        priority_only = st.checkbox("Exibir somente prioridade")
        if priority_only and "prioridade_mrp" in view.columns:
            view = view[
                view["prioridade_mrp"]
                .fillna(False)
                .astype(bool)
            ]

        display_cols = [
            x for x in [
                "id",
                "tipo_documento",
                "documento",
                "parte",
                "nfs_vinculadas",
                "empresa_sigla",
                "natureza",
                "vencimento",
                "prioridade_mrp",
                "status",
                "pdf_criado_em",
                "enviado_em",
                "operador",
                "arquivo_final",
            ]
            if x in view.columns
        ]
        table = view[display_cols].copy().reset_index(drop=True)

        st.dataframe(
            table.drop(columns=["id"], errors="ignore"),
            use_container_width=True,
            hide_index=True,
            column_config={
                "tipo_documento": "Tipo",
                "documento": "NF / CT-e",
                "parte": st.column_config.TextColumn(
                    "Fornecedor / Transportadora",
                    width="large",
                ),
                "nfs_vinculadas": st.column_config.TextColumn(
                    "NFs vinculadas",
                    width="medium",
                ),
                "empresa_sigla": "Empresa",
                "natureza": "Natureza",
                "prioridade_mrp": st.column_config.CheckboxColumn(
                    "Prioridade"
                ),
                "pdf_criado_em": st.column_config.DatetimeColumn(
                    "PDF criado em",
                    format="DD/MM/YYYY HH:mm",
                ),
                "enviado_em": st.column_config.DatetimeColumn(
                    "Enviado em",
                    format="DD/MM/YYYY HH:mm",
                ),
                "arquivo_final": st.column_config.TextColumn(
                    "Arquivo",
                    width="large",
                ),
            },
        )

        export_view = view.drop(columns=[x for x in ["id"] if x in view.columns])
        try:
            export_payload = excel_bytes(export_view, "Controle NFs")
        except Exception as exc:
            st.warning(
                "O Dashboard continua disponível, mas a exportação para Excel "
                f"não pôde ser preparada: {exc}"
            )
        else:
            st.download_button(
                "Exportar consulta para Excel",
                export_payload,
                file_name=f"controle_documentos_{now_local():%d%m%Y}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                use_container_width=True,
            )



elif page == "Pendências":
    _control_docs_title = str(cfg.get("control_docs_label") or DEFAULT["control_docs_label"]).strip()
    st.markdown(
        f'<div class="section-title">{_control_docs_title}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Pré-notas pendentes é a central de tratativa geral das NFs. O Impacto MRP é calculado em segundo plano e apenas influencia a prioridade."
    )

    pending_records = current_process_records_for_tests()

    pre_base = st.session_state.pre_notes.copy()
    pending_pre = current_pending_pre_notes()

    pre_keys = set()
    if isinstance(pre_base, pd.DataFrame) and not pre_base.empty:
        if "chave_validacao" not in pre_base.columns:
            pre_base["chave_validacao"] = pre_base.apply(
                lambda row: pre_note_key(row.get("numero_nf"), row.get("cnpj")), axis=1
            )
        pre_keys = set(pre_base["chave_validacao"].dropna().astype(str).tolist())

    pdf_without_pre = pd.DataFrame()
    if not pending_records.empty:
        temp = pending_records.copy()
        temp["chave_validacao"] = temp.apply(
            lambda row: pre_note_key(row.get("numero_nf"), row.get("cnpj_fornecedor")), axis=1
        )
        pdf_without_pre = temp[
            temp["chave_validacao"].ne("") & ~temp["chave_validacao"].isin(pre_keys)
        ].copy()

    pend_pre_tab, pend_process_tab = st.tabs(["Pré-notas pendentes", "Processamento de arquivos"])

    with pend_pre_tab:
        show_last_update("pre")
        if pre_base.empty:
            st.info(
                "A base de pré-notas ainda não foi carregada. "
                "Use Processamento de arquivos > Alimentação."
            )
        elif pending_pre.empty:
            st.success("Nenhuma pré-nota pendente de documento na carga atual.")
        else:
            # Complementa a carga com o fornecedor padrão usando o CNPJ.
            supplier_base = supplier_dataframe(st.session_state.suppliers)
            supplier_map = {}
            if not supplier_base.empty:
                supplier_map = (
                    supplier_base[
                        supplier_base["cnpj"].fillna("").astype(str).str.strip().ne("")
                    ]
                    .drop_duplicates("cnpj", keep="first")
                    .set_index("cnpj")["nome_padrao"]
                    .to_dict()
                )

            pending_view = pending_pre.copy()
            pending_view["cnpj"] = pending_view["cnpj"].map(digits_only)
            if "fornecedor" not in pending_view.columns:
                pending_view["fornecedor"] = ""
            pending_view["fornecedor"] = (
                pending_view["fornecedor"]
                .fillna("")
                .astype(str)
                .str.strip()
            )
            supplier_fallback = pending_view["cnpj"].map(supplier_map).fillna("").astype(str).str.strip()
            pending_view["fornecedor"] = pending_view["fornecedor"].where(
                pending_view["fornecedor"].ne(""),
                supplier_fallback,
            ).replace("", "NÃO LOCALIZADO")
            if "recebedor" not in pending_view.columns:
                pending_view["recebedor"] = ""
            # Situação documental da NF dentro da sessão atual.
            cte_by_pre_key = {}
            linked_nf_keys = set()
            analysis_now = st.session_state.get("analysis")
            if isinstance(analysis_now, pd.DataFrame) and not analysis_now.empty:
                analysis_by_file = {
                    str(row.get("file_id") or ""): row.to_dict()
                    for _, row in analysis_now.iterrows()
                    if str(row.get("file_id") or "").strip()
                }
                for nf_row in analysis_by_file.values():
                    key = pre_note_key(
                        nf_row.get("numero_nf"),
                        nf_row.get("cnpj_fornecedor"),
                    )
                    if key:
                        linked_nf_keys.add(key)

                for cte in st.session_state.get("cte_links") or []:
                    cte_number = str(cte.get("numero_cte") or "").strip()
                    if not cte_number:
                        cte_number = "VINCULADO"
                    for file_id in cte.get("linked_file_ids") or []:
                        nf_row = analysis_by_file.get(str(file_id) or "")
                        if not nf_row:
                            continue
                        key = pre_note_key(
                            nf_row.get("numero_nf"),
                            nf_row.get("cnpj_fornecedor"),
                        )
                        if not key:
                            continue
                        cte_by_pre_key.setdefault(key, [])
                        if cte_number not in cte_by_pre_key[key]:
                            cte_by_pre_key[key].append(cte_number)

            def _cte_status(row):
                key = pre_note_key(
                    row.get("numero_nf"),
                    row.get("cnpj"),
                )
                values = cte_by_pre_key.get(key, [])
                if not values:
                    return "SEM CT-e"
                if len(values) == 1:
                    return f"CT-e {values[0]}"
                return f"{len(values)} CT-es"

            pending_view["cte"] = pending_view.apply(
                _cte_status,
                axis=1,
            )

            def _document_status(row):
                key = pre_note_key(
                    row.get("numero_nf"),
                    row.get("cnpj"),
                )
                return (
                    "NF-e VINCULADA"
                    if key in linked_nf_keys
                    else "PENDENTE DE DOCUMENTO"
                )

            pending_view["validacao_documento"] = pending_view.apply(
                _document_status,
                axis=1,
            )
            pending_view["data_nf"] = pending_view.apply(
                lambda row: date_nf_key(row.get("data_pre_nota"), row.get("numero_nf")),
                axis=1,
            )

            impact_summary = st.session_state.get("mrp_priority_summary")
            if isinstance(impact_summary, pd.DataFrame) and not impact_summary.empty:
                match_results = pending_view.apply(
                    lambda row: match_pre_note_to_mrp(row, impact_summary),
                    axis=1,
                )

                pending_view["prioridade"] = match_results.map(
                    lambda result: (
                        str(result["row"].get("prioridade") or "ERRO")
                        if result.get("matched") and result.get("row")
                        else "ERRO"
                    )
                )
                pending_view["data_cm"] = match_results.map(
                    lambda result: (
                        result["row"].get("data_cm")
                        if result.get("matched") and result.get("row")
                        else None
                    )
                )
                pending_view["situacao_mrp"] = match_results.map(
                    lambda result: str(result.get("situacao") or "ERRO")
                )
                pending_view["aderencia_fornecedor"] = match_results.map(
                    lambda result: int(result.get("score_fornecedor") or 0)
                )
            else:
                pending_view["prioridade"] = "AGUARDANDO CARGA MRP"
                pending_view["data_cm"] = None
                pending_view["situacao_mrp"] = "IMPACTO MRP NÃO CARREGADO"
                pending_view["aderencia_fornecedor"] = 0

            def _pending_treatment_label(row):
                situacao = str(row.get("situacao_mrp") or "").strip().upper()
                prioridade = str(row.get("prioridade") or "").strip().upper()
                documento = str(
                    row.get("validacao_documento") or ""
                ).strip().upper()

                if situacao not in {"OK", "IMPACTO MRP NÃO CARREGADO"}:
                    return "REVISAR VÍNCULO MRP"
                if documento == "NF-E VINCULADA":
                    if prioridade == "ALTA":
                        return "PRIORIDADE / PRONTO"
                    return "PRONTO PARA GERAÇÃO"
                if prioridade == "ALTA":
                    return "PRIORIDADE MRP"
                return "AGUARDANDO DOCUMENTO"

            pending_view["tratativa"] = pending_view.apply(
                _pending_treatment_label,
                axis=1,
            )

            mrp_errors = int(
                (
                    ~pending_view["situacao_mrp"].eq("OK")
                    & ~pending_view["situacao_mrp"].eq("IMPACTO MRP NÃO CARREGADO")
                ).sum()
            )
            if mrp_errors:
                st.error(
                    f"{mrp_errors} pré-nota(s) não tiveram correspondência segura no Impacto MRP. "
                    "A chave principal agora é Data + NF e o nome do fornecedor precisa validar a correspondência."
                )

            st.markdown(
                f"""
                <div class="panel" style="padding:1.05rem 1.2rem;margin:0 0 1rem 0;">
                    <div style="display:flex;align-items:center;justify-content:space-between;gap:1rem;flex-wrap:wrap;">
                        <div>
                            <div style="font-size:1.12rem;font-weight:800;color:#0f172a;">Pré-notas pendentes de documento</div>
                            <div style="margin-top:.24rem;font-size:.82rem;color:#64748b;">
                                Vínculo com Impacto MRP por Data + NF, validado pelo nome do fornecedor. O CNPJ permanece apenas informativo.
                            </div>
                        </div>
                        <div style="font-size:.82rem;font-weight:800;color:#0f172a;background:#f8fafc;border:1px solid #e2e8f0;border-radius:999px;padding:.45rem .75rem;">
                            {len(pending_view)} pendente(s)
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Barra de pesquisa no mesmo padrão visual do fluxo operacional.
            if "pre_pending_search" not in st.session_state:
                st.session_state.pre_pending_search = ""
            if "pre_pending_date" not in st.session_state:
                st.session_state.pre_pending_date = "Todas"
            if "pre_pending_supplier" not in st.session_state:
                st.session_state.pre_pending_supplier = "Todos"

            date_values = sorted(
                [
                    d for d in pd.to_datetime(
                        pending_view["data_pre_nota"], errors="coerce"
                    ).dt.date.dropna().unique().tolist()
                ],
                reverse=True,
            )
            date_options = ["Todas"] + [d.strftime("%d/%m/%Y") for d in date_values]

            supplier_options = ["Todos"] + sorted(
                pending_view["fornecedor"].fillna("").astype(str).loc[
                    lambda s: s.str.strip().ne("")
                ].unique().tolist()
            )

            def _clear_pre_pending_filters():
                st.session_state.pre_pending_search = ""
                st.session_state.pre_pending_date = "Todas"
                st.session_state.pre_pending_supplier = "Todos"

            with st.container(border=True):
                f1, f2, f3 = st.columns([1.7, 1, 1.3])
                f1.text_input(
                    "Buscar NF / CNPJ / fornecedor",
                    key="pre_pending_search",
                )
                f2.selectbox(
                    "Data da pré-nota",
                    date_options,
                    key="pre_pending_date",
                )
                f3.selectbox(
                    "Fornecedor",
                    supplier_options,
                    key="pre_pending_supplier",
                )

                b1, b2 = st.columns([9, 1])
                b1.button(
                    "Pesquisar",
                    type="primary",
                    use_container_width=True,
                    key="pre_pending_search_button",
                )
                b2.button(
                    "Limpar",
                    use_container_width=True,
                    key="pre_pending_clear_button",
                    on_click=_clear_pre_pending_filters,
                )

            filtered = pending_view.copy()

            search_term = normalize_text(
                st.session_state.get("pre_pending_search") or ""
            )
            if search_term:
                search_mask = (
                    filtered["numero_nf"].fillna("").astype(str).map(normalize_text).str.contains(search_term, na=False)
                    | filtered["cnpj"].fillna("").astype(str).map(normalize_text).str.contains(search_term, na=False)
                    | filtered["fornecedor"].fillna("").astype(str).map(normalize_text).str.contains(search_term, na=False)
                )
                filtered = filtered[search_mask].copy()

            selected_date = st.session_state.get("pre_pending_date") or "Todas"
            if selected_date != "Todas":
                selected_date_obj = pd.to_datetime(
                    selected_date, format="%d/%m/%Y", errors="coerce"
                )
                if not pd.isna(selected_date_obj):
                    filtered_dates = pd.to_datetime(
                        filtered["data_pre_nota"], errors="coerce"
                    ).dt.date
                    filtered = filtered[
                        filtered_dates.eq(selected_date_obj.date())
                    ].copy()

            selected_supplier = st.session_state.get("pre_pending_supplier") or "Todos"
            if selected_supplier != "Todos":
                filtered = filtered[
                    filtered["fornecedor"].fillna("").astype(str).eq(selected_supplier)
                ].copy()

            priority_order = {
                "ERRO": 0,
                "ALTA": 1,
                "BAIXA": 2,
                "AGUARDANDO CARGA MRP": 3,
            }
            filtered["_priority_order"] = (
                filtered["prioridade"].map(priority_order).fillna(9)
            )
            filtered = filtered.sort_values(
                ["_priority_order", "data_cm", "data_pre_nota", "numero_nf"],
                ascending=[True, True, False, True],
                na_position="last",
            ).drop(columns="_priority_order")

            table_cols = [
                "data_pre_nota",
                "numero_nf",
                "cnpj",
                "fornecedor",
                "recebedor",
                "prioridade",
                "situacao_mrp",
                "aderencia_fornecedor",
                "cte",
                "tratativa",
                "validacao_documento",
            ]

            st.dataframe(
                filtered[table_cols],
                use_container_width=True,
                hide_index=True,
                column_config={
                    "data_pre_nota": st.column_config.DateColumn(
                        "Data da pré-nota",
                        format="DD/MM/YYYY",
                    ),
                    "numero_nf": "NF",
                    "cnpj": "CNPJ",
                    "fornecedor": st.column_config.TextColumn(
                        "Fornecedor",
                        width="large",
                    ),
                    "recebedor": st.column_config.TextColumn(
                        "Recebedor",
                        width="medium",
                    ),
                    "prioridade": "Prioridade",
                    "data_cm": st.column_config.DateColumn(
                        "Data CM",
                        format="DD/MM/YYYY",
                    ),
                    "situacao_mrp": st.column_config.TextColumn(
                        "Situação MRP",
                        width="medium",
                    ),
                    "aderencia_fornecedor": st.column_config.NumberColumn(
                        "Aderência fornecedor",
                        format="%d%%",
                    ),
                    "cte": st.column_config.TextColumn(
                        "CT-e",
                        width="medium",
                    ),
                    "tratativa": st.column_config.TextColumn(
                        "Tratativa",
                        width="medium",
                    ),
                    "validacao_documento": st.column_config.TextColumn(
                        "Validação documento",
                        width="medium",
                    ),
                },
            )
            st.caption(
                f"Exibindo {len(filtered)} de {len(pending_view)} pré-nota(s) pendente(s)."
            )

        st.divider()
        render_mrp_missing_pre_treatments()
        st.divider()
        render_document_linking_stage()
        st.divider()
        render_nf_treatment_center()
        st.divider()

        # Etapa final do fluxo: depois de baixar/enviar os ZIPs, a confirmação
        # acontece ainda nesta aba de Pré-notas. Só após esta ação a NF entra
        # na consulta de finalizados do Dashboard.
        awaiting_send = pd.DataFrame()
        if isinstance(pending_records, pd.DataFrame) and not pending_records.empty:
            awaiting_send = pending_records.copy()
            status_series = (
                awaiting_send.get("status", pd.Series("", index=awaiting_send.index))
                .fillna("")
                .astype(str)
                .str.upper()
            )
            sent_series = awaiting_send.get(
                "enviado_em",
                pd.Series(pd.NaT, index=awaiting_send.index),
            )
            sent_series = pd.to_datetime(sent_series, errors="coerce")
            awaiting_send = awaiting_send[
                status_series.isin({"REALIZADO", "PDF CRIADO"})
                & sent_series.isna()
            ].copy()

        st.markdown("#### Aguardando confirmação de envio")
        if awaiting_send.empty:
            st.caption("Nenhum documento processado aguardando confirmação de envio.")
        else:
            send_cols = [x for x in [
                "id",
                "tipo_documento",
                "pre_nota_em",
                "numero_nf",
                "numero_cte",
                "fornecedor_padrao",
                "transportadora",
                "nfs_vinculadas",
                "natureza",
                "vencimento",
                "prioridade_mrp",
                "pdf_criado_em",
                "arquivo_final",
            ] if x in awaiting_send.columns]

            send_view = awaiting_send[send_cols].copy().reset_index(drop=True)
            if "tipo_documento" not in send_view.columns:
                send_view["tipo_documento"] = "NF-e"

            send_view["tipo_documento"] = (
                send_view["tipo_documento"]
                .fillna("NF-e")
                .astype(str)
            )
            is_cte_row = (
                send_view["tipo_documento"]
                .map(normalize_text)
                .str.contains("CTE", na=False)
            )

            send_view["documento"] = send_view.apply(
                lambda row: (
                    str(row.get("numero_cte") or "").strip()
                    if "CTE" in normalize_text(row.get("tipo_documento"))
                    else normalized_nf(row.get("numero_nf"))
                ),
                axis=1,
            )
            send_view["parte"] = send_view.apply(
                lambda row: (
                    str(row.get("transportadora") or "").strip()
                    if "CTE" in normalize_text(row.get("tipo_documento"))
                    else str(row.get("fornecedor_padrao") or "").strip()
                ),
                axis=1,
            )
            send_view["vinculo"] = send_view.apply(
                lambda row: (
                    str(row.get("nfs_vinculadas") or "").strip()
                    if "CTE" in normalize_text(row.get("tipo_documento"))
                    else ""
                ),
                axis=1,
            )

            if "pdf_criado_em" in send_view.columns:
                send_view["pdf_criado_em"] = (
                    pd.to_datetime(
                        send_view["pdf_criado_em"],
                        errors="coerce",
                        utc=True,
                    )
                    .dt.tz_convert(TZ)
                    .dt.tz_localize(None)
                )
            if "pre_nota_em" in send_view.columns:
                send_view["pre_nota_em"] = pd.to_datetime(
                    send_view["pre_nota_em"],
                    errors="coerce",
                )

            sel1, sel2 = st.columns(2)
            select_all_nf_send = sel1.checkbox(
                "Selecionar todas as NFs",
                value=False,
                key="select_all_nf_send",
            )
            select_all_cte_send = sel2.checkbox(
                "Selecionar todos os CT-es",
                value=False,
                key="select_all_cte_send",
            )

            send_view.insert(
                0,
                "Confirmar",
                [
                    bool(select_all_cte_send)
                    if is_cte
                    else bool(select_all_nf_send)
                    for is_cte in is_cte_row.tolist()
                ],
            )

            display_send_cols = [
                col for col in [
                    "id",
                    "Confirmar",
                    "tipo_documento",
                    "pre_nota_em",
                    "documento",
                    "parte",
                    "vinculo",
                    "natureza",
                    "vencimento",
                    "prioridade_mrp",
                    "pdf_criado_em",
                    "arquivo_final",
                ]
                if col in send_view.columns
            ]
            send_view = send_view[display_send_cols]

            operator_ready = bool(str(st.session_state.operator or "").strip())
            if not operator_ready:
                st.info(
                    "Selecione o operador no menu lateral para confirmar o envio."
                )

            editor_key = (
                "document_send_confirmation_"
                f"{'nf' if select_all_nf_send else 'n'}_"
                f"{'cte' if select_all_cte_send else 'c'}_"
                f"{len(send_view)}"
            )
            with st.form("send_confirmation_form"):
                send_editor = st.data_editor(
                    send_view,
                    use_container_width=True,
                    hide_index=True,
                    disabled=[x for x in send_view.columns if x != "Confirmar"],
                    key=editor_key,
                    column_config={
                        "id": None,
                        "Confirmar": st.column_config.CheckboxColumn(
                            "Confirmar",
                            help="Marque os documentos efetivamente enviados.",
                        ),
                        "tipo_documento": st.column_config.TextColumn(
                            "Tipo",
                            width="small",
                        ),
                        "pre_nota_em": st.column_config.DateColumn(
                            "Data pré-nota",
                            format="DD/MM/YYYY",
                        ),
                        "documento": st.column_config.TextColumn(
                            "NF / CT-e",
                            width="small",
                        ),
                        "parte": st.column_config.TextColumn(
                            "Fornecedor / Transportadora",
                            width="large",
                        ),
                        "vinculo": st.column_config.TextColumn(
                            "NFs vinculadas",
                            width="medium",
                        ),
                        "natureza": st.column_config.TextColumn(
                            "Natureza",
                            width="medium",
                        ),
                        "vencimento": st.column_config.DateColumn(
                            "Vencimento",
                            format="DD/MM/YYYY",
                        ),
                        "prioridade_mrp": st.column_config.CheckboxColumn(
                            "Prioridade"
                        ),
                        "pdf_criado_em": st.column_config.DatetimeColumn(
                            "PDF criado em",
                            format="DD/MM/YYYY HH:mm",
                        ),
                        "arquivo_final": st.column_config.TextColumn(
                            "Arquivo",
                            width="large",
                        ),
                    },
                )
                confirm_send = st.form_submit_button(
                    "CONFIRMAR ENVIO DOS DOCUMENTOS SELECIONADOS",
                    type="primary",
                    use_container_width=True,
                    disabled=not operator_ready,
                )

            if confirm_send:
                selected_send_ids = (
                    send_editor.loc[
                        send_editor["Confirmar"].fillna(False).astype(bool),
                        "id",
                    ]
                    .dropna()
                    .astype(str)
                    .tolist()
                    if "id" in send_editor.columns
                    else []
                )

                if not selected_send_ids:
                    st.warning("Selecione pelo menos um documento para confirmar o envio.")
                else:
                    try:
                        if SAVE_NF_HISTORY and db.configured():
                            result = db.mark_sent(
                                selected_send_ids,
                                st.session_state.operator,
                            )
                            updated_count = int(result.get("atualizados", 0))
                        else:
                            now_sent = now_local().isoformat()
                            updated_count = 0
                            manifest = list(
                                st.session_state.get("current_test_manifest") or []
                            )
                            selected_set = set(selected_send_ids)
                            for row in manifest:
                                row_id = str(row.get("id") or row.get("file_id") or "")
                                if row_id in selected_set:
                                    row["status"] = "ENVIADO"
                                    row["enviado_em"] = now_sent
                                    row["operador"] = st.session_state.operator
                                    updated_count += 1
                            st.session_state.current_test_manifest = manifest

                        st.success(
                            f"{updated_count} documento(s) confirmado(s) como enviado(s). "
                            "Eles já estão disponíveis no Dashboard de finalizados."
                        )
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Falha ao confirmar envio: {exc}")

    with pend_process_tab:
        render_file_processing()


elif page == "Configurações":
    tab_personalizacao, tab_usuarios = st.tabs(["Personalização", "Usuários"])

    with tab_personalizacao:
        st.markdown("### Personalização do aplicativo")
        cur = st.session_state.cfg.copy()
        with st.form("cfg_form"):
            title = st.text_input("Título principal", cur["title"])
            sub = st.text_input("Subtítulo", cur["subtitle"])
            side = st.text_input("Título do menu lateral", cur["sidebar_title"])
            side_sub = st.text_input("Subtítulo do menu lateral", cur["sidebar_subtitle"])
            control_docs_label = st.text_input(
                "Nome da aba Controle de documentos",
                str(cur.get("control_docs_label") or DEFAULT["control_docs_label"]),
                help="Altera o nome exibido no menu lateral e no título da página que reúne pré-notas, MRP e processamento de arquivos.",
            )
            intro = st.text_area("Texto da tela principal", cur["intro"])
            footer = st.text_input("Rodapé", cur["footer"])
            button_color = st.color_picker("Cor principal dos botões", cur["button_color"])
            save = st.form_submit_button("Salvar textos e cor", type="primary", use_container_width=True)
        if save:
            cur.update(
                title=title or DEFAULT["title"],
                subtitle=sub or DEFAULT["subtitle"],
                sidebar_title=side or DEFAULT["sidebar_title"],
                sidebar_subtitle=side_sub or DEFAULT["sidebar_subtitle"],
                control_docs_label=control_docs_label or DEFAULT["control_docs_label"],
                intro=intro or DEFAULT["intro"],
                footer=footer or DEFAULT["footer"],
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
