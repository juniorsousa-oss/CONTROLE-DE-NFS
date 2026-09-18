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
from danfe_generator import (
    apply_operational_stamp,
    danfe_file_name,
    extract_danfe_metadata,
    extract_nfe_processing_data,
    generate_danfe_pdf,
)
from nf_processor import (
    build_final_name,
    digits_only,
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

# MODO DE TESTES — reativar quando o fluxo estiver homologado.
SAVE_NF_HISTORY = False
ENABLE_PENDING_REPORT = True

FAVICON_FILE = ROOT / "config" / "favicon_setta.b64"

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
        "prefilter_rejected": [],
        "prefilter_stats": {},
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
                    st.session_state.pre_notes = pd.DataFrame(remote_pre_notes)
            st.session_state.db_synced = True
        except Exception as exc:
            st.session_state.db_sync_error = str(exc)


init()
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


def parse_natures() -> list[str]:
    raw = str(st.session_state.cfg.get("naturezas") or "MP,MC")
    values = [re.sub(r"\s+", " ", x.strip().upper()) for x in re.split(r"[,;|\n]", raw) if x.strip()]
    return list(dict.fromkeys(values)) or ["MP", "MC"]


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
        ("Prioridade MRP", int(df.get("prioridade_mrp", pd.Series(False, index=df.index)).fillna(False).astype(bool).sum()), "ZIP separado"),
    ]
    for col, (title, number, desc) in zip(st.columns(4), values):
        col.markdown(
            f'<div class="metric"><small>{title}</small><strong>{number}</strong><span>{desc}</span></div>',
            unsafe_allow_html=True,
        )


def excel_bytes(frame: pd.DataFrame, sheet: str = "Dados") -> bytes:
    buffer = io.BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        frame.to_excel(writer, index=False, sheet_name=sheet[:31])
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
            "cr": str(values[4] or "").strip(),
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

                st.session_state.mrp_import_preview_detail = pd.DataFrame()
                st.session_state.mrp_import_preview_summary = pd.DataFrame()
                set_flash(
                    "_flash_mrp",
                    "success",
                    (
                        f"Carga aplicada: {len(summary)} NF(s) avaliadas, "
                        f"{len(high)} em prioridade ALTA. "
                        "A correlação com pré-notas usa Data + NF, com validação pelo nome do fornecedor."
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
                "Alimente em Configurações → Alimentação → Prioridade MRP."
            )
            return

        st.caption(
            "Acompanhamento da carga aplicada em Configurações → Alimentação → Prioridade MRP."
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

                        set_flash(
                            "_flash_mrp",
                            "success",
                            (
                                f"{len(additions)} NF(s) adicionada(s) "
                                "à lista de Pré-notas pendentes."
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

                            set_flash(
                                "_flash_mrp",
                                "success",
                                (
                                    f"{len(ignored_rows)} NF(s) "
                                    "desconsiderada(s) da carga atual "
                                    "de Impacto MRP."
                                ),
                            )
                            st.rerun()


def match_document_to_pre_note(
    document_row: pd.Series | dict,
    min_supplier_score: int = 82,
    pre_notes: pd.DataFrame | None = None,
) -> dict:
    frame = pre_notes if isinstance(pre_notes, pd.DataFrame) else st.session_state.pre_notes
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

    supplier_names = [
        str(document_row.get("fornecedor_padrao") or "").strip(),
        str(document_row.get("fornecedor_lido") or "").strip(),
    ]
    supplier_names = [name for name in supplier_names if name]
    if not supplier_names:
        result["situacao"] = "FORNECEDOR DO DOCUMENTO NÃO LOCALIZADO"
        return result

    candidates["_supplier_pre"] = candidates.apply(pre_supplier_name, axis=1)
    candidates["_score_supplier"] = candidates["_supplier_pre"].map(
        lambda pre_name: max(
            [supplier_similarity(pre_name, doc_name) for doc_name in supplier_names]
            or [0]
        )
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



def apply_cross_checks(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df

    out = df.copy()
    mrp_summary = st.session_state.get("mrp_priority_summary")
    if not isinstance(mrp_summary, pd.DataFrame):
        mrp_summary = pd.DataFrame()

    priority_flags = []
    pre_status = []
    pre_dates = []
    pre_link_status = []
    pre_supplier_scores = []
    resolved_natures = []
    nature_sources = []

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
        priority = bool(
            mrp_row
            and str(mrp_row.get("prioridade") or "").upper() == "ALTA"
        )

        current_nature = str(row.get("natureza") or "").strip().upper()
        nature_source = str(row.get("natureza_origem") or "").strip()

        if not current_nature:
            loaded_nature, loaded_source = nature_from_nf_load(
                pre_row,
                row,
            )
            if loaded_nature:
                current_nature = loaded_nature
                nature_source = loaded_source

        priority_flags.append(priority)
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

    out["prioridade_mrp"] = priority_flags
    out["pre_nota_status"] = pre_status
    out["pre_nota_em"] = pre_dates
    out["vinculo_mrp_status"] = pre_link_status
    out["vinculo_fornecedor_score"] = pre_supplier_scores
    out["natureza"] = resolved_natures
    out["natureza_origem"] = nature_sources
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


def current_process_records_for_tests() -> pd.DataFrame:
    """Em testes, considera somente a carga atual; em produção, usa o histórico oficial."""
    if not SAVE_NF_HISTORY:
        return pd.DataFrame(st.session_state.get("current_test_manifest") or [])
    if db.configured():
        try:
            return pd.DataFrame(db.list_process_records())
        except Exception:
            return pd.DataFrame(st.session_state.history)
    return pd.DataFrame(st.session_state.history)


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
            allowed_natures=parse_natures(),
        )

    if pdf_result is not None:
        row = pdf_result.to_dict()
        output_bytes = pdf_item["raw"]
        source_name = pdf_item["name"]
    else:
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
        output_bytes = generate_danfe_pdf(xml_item["raw"])
        source_name = xml_item["name"]

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

    row["origem_dados"] = source_mode
    row["pre_nota_data"] = normalized_business_date(pre_row.get("data_pre_nota"))
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


def render_file_processing():
    st.markdown('<div class="section-title">Processamento de arquivos</div>', unsafe_allow_html=True)
    tab_nf, tab_danfe, tab_cte = st.tabs(["NFs", "XML → DANFE", "CTEs"])

    with tab_nf:
        st.markdown(
            '<div class="intro">'
            "Envie vários <b>XMLs e/ou PDFs</b>. Antes do processamento completo, o sistema confronta "
            "cada documento com a lista que está atualmente em <b>Pré-notas pendentes</b>. "
            "Somente correspondências seguras seguem para análise; os demais arquivos são descartados do lote."
            "</div>",
            unsafe_allow_html=True,
        )

        pending_base = current_pending_pre_notes()
        if pending_base.empty:
            st.warning(
                "Não há pré-notas pendentes disponíveis para o pré-filtro. "
                "Carregue a base em Configurações → Alimentação → Validação Pré-notas "
                "ou verifique se a lista já foi concluída."
            )
        else:
            st.caption(
                f"Pré-filtro ativo com {len(pending_base)} pré-nota(s) atualmente pendente(s). "
                "A identificação usa NF + fornecedor para localizar a pré-nota; depois a prioridade MRP "
                "continua seguindo Data + NF com validação do fornecedor."
            )

        files = st.file_uploader(
            "Selecione ou arraste XMLs e/ou PDFs das notas fiscais",
            type=["xml", "pdf"],
            accept_multiple_files=True,
            key="nf_hybrid_uploads",
        )

        a, b = st.columns([4, 1])
        analyze = a.button(
            "PRÉ-FILTRAR E ANALISAR DOCUMENTOS",
            type="primary",
            use_container_width=True,
            disabled=(not files or pending_base.empty),
            key="analyze_hybrid_nf",
        )
        if b.button(
            "Limpar lote atual",
            use_container_width=True,
            key="clear_hybrid_nf",
        ):
            st.session_state.analysis = pd.DataFrame()
            st.session_state.pdfs = {}
            st.session_state.zip_outputs = {}
            st.session_state.prefilter_rejected = []
            st.session_state.prefilter_stats = {}
            st.session_state.current_test_manifest = []
            st.rerun()

        if analyze:
            st.session_state.current_test_manifest = []
            st.session_state.zip_outputs = {}

            groups: dict[str, dict] = {}
            rejected: list[dict] = []
            uploaded = []

            for file in files:
                ext = Path(file.name).suffix.lower()
                uploaded.append(
                    {
                        "name": file.name,
                        "ext": ext,
                        "raw": file.getvalue(),
                    }
                )

            # 1) XML primeiro: identificação é estruturada e muito mais barata/confiável.
            xml_entries = [item for item in uploaded if item["ext"] == ".xml"]
            pdf_entries = [item for item in uploaded if item["ext"] == ".pdf"]

            prefilter_progress = st.progress(0, text="Pré-filtrando documentos...")
            total_prefilter = max(1, len(uploaded))
            done_prefilter = 0

            for item in xml_entries:
                try:
                    xml_data = extract_nfe_processing_data(item["raw"])
                    identity = _xml_prefilter_identity(xml_data)
                    match = match_document_to_pre_note(
                        identity,
                        pre_notes=pending_base,
                    )

                    if not match.get("matched"):
                        rejected.append({
                            "arquivo": item["name"],
                            "tipo": "XML",
                            "nf": normalized_nf(xml_data.get("numero_nf")),
                            "fornecedor": str(xml_data.get("fornecedor_lido") or ""),
                            "motivo": str(match.get("situacao") or "SEM CORRESPONDÊNCIA"),
                            "aderencia_fornecedor": int(match.get("score_fornecedor") or 0),
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
                            "name": item["name"],
                            "raw": item["raw"],
                            "data": xml_data,
                            "score": int(match.get("score_fornecedor") or 0),
                        })
                except Exception as exc:
                    rejected.append({
                        "arquivo": item["name"],
                        "tipo": "XML",
                        "nf": "",
                        "fornecedor": "",
                        "motivo": f"XML inválido/não processável: {exc}",
                        "aderencia_fornecedor": 0,
                    })

                done_prefilter += 1
                prefilter_progress.progress(
                    done_prefilter / total_prefilter,
                    text=f"Pré-filtro {done_prefilter}/{len(uploaded)} — {item['name']}",
                )

            # 2) PDF: leitura leve, sem OCR completo. O OCR só roda se o PDF sobreviver ao filtro.
            for item in pdf_entries:
                identity = inspect_nf_pdf_identity(
                    item["name"],
                    item["raw"],
                    st.session_state.suppliers,
                )
                match = match_document_to_pre_note(
                    identity,
                    pre_notes=pending_base,
                )

                group_key = ""
                pre_row = None

                if match.get("matched"):
                    pre_row = match["row"]
                    group_key = pending_document_group_key(pre_row)
                else:
                    # Se o PDF não trouxer fornecedor legível, mas houver um XML já validado
                    # para a mesma NF e somente uma pré-nota possível, ele pode complementar
                    # aquele XML sem ampliar o conjunto de notas aceitas.
                    pdf_nf = normalized_nf(identity.get("numero_nf"))
                    possible = [
                        (key, group)
                        for key, group in groups.items()
                        if normalized_nf(group["pre"].get("numero_nf")) == pdf_nf
                    ]
                    if pdf_nf and len(possible) == 1:
                        group_key, existing_group = possible[0]
                        pre_row = existing_group["pre"]

                if not group_key or pre_row is None:
                    rejected.append({
                        "arquivo": item["name"],
                        "tipo": "PDF",
                        "nf": normalized_nf(identity.get("numero_nf")),
                        "fornecedor": str(
                            identity.get("fornecedor_padrao")
                            or identity.get("fornecedor_lido")
                            or ""
                        ),
                        "motivo": str(
                            match.get("situacao")
                            or identity.get("erro")
                            or "SEM CORRESPONDÊNCIA"
                        ),
                        "aderencia_fornecedor": int(match.get("score_fornecedor") or 0),
                    })
                else:
                    group = groups.setdefault(
                        group_key,
                        {
                            "pre": pre_row,
                            "xmls": [],
                            "pdfs": [],
                        },
                    )
                    group["pdfs"].append({
                        "name": item["name"],
                        "raw": item["raw"],
                        "identity": identity,
                        "score": int(match.get("score_fornecedor") or 0),
                    })

                done_prefilter += 1
                prefilter_progress.progress(
                    done_prefilter / total_prefilter,
                    text=f"Pré-filtro {done_prefilter}/{len(uploaded)} — {item['name']}",
                )

            prefilter_progress.empty()

            # Mantém apenas um XML e um PDF por pré-nota. Repetições não entram no lote.
            for group in groups.values():
                if len(group["xmls"]) > 1:
                    group["xmls"].sort(
                        key=lambda item: item.get("score", 0),
                        reverse=True,
                    )
                    for duplicate in group["xmls"][1:]:
                        rejected.append({
                            "arquivo": duplicate["name"],
                            "tipo": "XML",
                            "nf": normalized_nf(group["pre"].get("numero_nf")),
                            "fornecedor": pre_supplier_name(group["pre"]),
                            "motivo": "XML DUPLICADO PARA A MESMA PRÉ-NOTA",
                            "aderencia_fornecedor": duplicate.get("score", 0),
                        })
                    group["xmls"] = group["xmls"][:1]

                if len(group["pdfs"]) > 1:
                    group["pdfs"].sort(
                        key=lambda item: item.get("score", 0),
                        reverse=True,
                    )
                    for duplicate in group["pdfs"][1:]:
                        rejected.append({
                            "arquivo": duplicate["name"],
                            "tipo": "PDF",
                            "nf": normalized_nf(group["pre"].get("numero_nf")),
                            "fornecedor": pre_supplier_name(group["pre"]),
                            "motivo": "PDF DUPLICADO PARA A MESMA PRÉ-NOTA",
                            "aderencia_fornecedor": duplicate.get("score", 0),
                        })
                    group["pdfs"] = group["pdfs"][:1]

            rows, store = [], {}
            process_groups = [
                group
                for group in groups.values()
                if group.get("xmls") or group.get("pdfs")
            ]

            process_progress = st.progress(0, text="Processando documentos correspondentes...")
            for idx, group in enumerate(process_groups, start=1):
                try:
                    row, stored = _build_hybrid_nf_document(group)
                    rows.append(row)
                    store[row["file_id"]] = stored
                except Exception as exc:
                    source_files = [
                        item["name"]
                        for item in (group.get("pdfs") or []) + (group.get("xmls") or [])
                    ]
                    rejected.append({
                        "arquivo": " + ".join(source_files) or "Documento",
                        "tipo": "PROCESSAMENTO",
                        "nf": normalized_nf(group["pre"].get("numero_nf")),
                        "fornecedor": pre_supplier_name(group["pre"]),
                        "motivo": f"Falha após o pré-filtro: {exc}",
                        "aderencia_fornecedor": 0,
                    })

                process_progress.progress(
                    idx / max(1, len(process_groups)),
                    text=f"Processando {idx}/{len(process_groups)}",
                )
            process_progress.empty()

            frame = pd.DataFrame(rows)
            if not frame.empty:
                frame["vencimento"] = pd.to_datetime(
                    frame["vencimento"],
                    errors="coerce",
                ).dt.date
                frame = apply_cross_checks(frame)
                frame = recalc(frame)

            used_xml = sum(bool(group.get("xmls")) for group in process_groups)
            used_pdf = sum(bool(group.get("pdfs")) for group in process_groups)

            st.session_state.analysis = frame
            st.session_state.pdfs = store
            st.session_state.prefilter_rejected = rejected
            st.session_state.prefilter_stats = {
                "enviados": len(uploaded),
                "xml_enviados": len(xml_entries),
                "pdf_enviados": len(pdf_entries),
                "notas_correspondentes": len(frame),
                "xml_utilizados": used_xml,
                "pdf_utilizados": used_pdf,
                "excluidos": len(rejected),
            }

            if frame.empty:
                st.warning(
                    "Nenhum documento enviado correspondeu com segurança às pré-notas pendentes."
                )
            else:
                st.success(
                    f"Pré-filtro concluído: {len(frame)} nota(s) seguiram para validação. "
                    f"{len(rejected)} arquivo(s) foram excluídos do lote."
                )

        prefilter_stats = st.session_state.get("prefilter_stats") or {}
        prefilter_rejected = st.session_state.get("prefilter_rejected") or []

        if prefilter_stats:
            pf1, pf2, pf3, pf4 = st.columns(4)
            pf1.metric("Arquivos enviados", prefilter_stats.get("enviados", 0))
            pf2.metric("Notas correspondentes", prefilter_stats.get("notas_correspondentes", 0))
            pf3.metric("XMLs utilizados", prefilter_stats.get("xml_utilizados", 0))
            pf4.metric("Arquivos excluídos", prefilter_stats.get("excluidos", 0))

        if prefilter_rejected:
            with st.expander(
                f"Arquivos eliminados pelo pré-filtro ({len(prefilter_rejected)})",
                expanded=False,
            ):
                st.dataframe(
                    pd.DataFrame(prefilter_rejected),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "arquivo": st.column_config.TextColumn("Arquivo", width="large"),
                        "tipo": "Tipo",
                        "nf": "NF",
                        "fornecedor": st.column_config.TextColumn("Fornecedor", width="large"),
                        "motivo": st.column_config.TextColumn("Motivo da exclusão", width="large"),
                        "aderencia_fornecedor": st.column_config.NumberColumn(
                            "Aderência fornecedor",
                            format="%d%%",
                        ),
                    },
                )

        frame = st.session_state.analysis.copy()
        if not frame.empty and "origem_dados" not in frame.columns:
            frame["origem_dados"] = "PDF"
        if frame.empty:
            st.info("Nenhum lote analisado nesta sessão.")
        else:
            frame = apply_cross_checks(frame)
            frame = recalc(frame)
            st.markdown("### Conferência das correspondências")
            metrics(frame)
            st.caption("Vencimento, número da NF, fornecedor, natureza interna e status podem ser corrigidos antes da geração definitiva.")
            st.info(
                "Tratamento de exceções: quando uma linha ficar em REVISAR, corrija o campo pendente diretamente na tabela "
                "(por exemplo, Vencimento), confira o fornecedor/natureza e então altere o Status para APROVADO. "
                "O nome final é recalculado automaticamente."
            )

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

            merged = frame.copy()
            pending_mask = treatment_mask(merged)
            pending = merged.loc[pending_mask].copy()

            with st.expander(
                f"Documentos sem tratativa ({int((~pending_mask).sum())})",
                expanded=False,
            ):
                ready_cols = [
                    "arquivo_original",
                    "origem_dados",
                    "numero_nf",
                    "fornecedor_padrao",
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
                        "vencimento": st.column_config.DateColumn("Vencimento", format="DD/MM/YYYY"),
                        "natureza": "Natureza",
                        "nome_sugerido": "Nome final",
                        "prioridade_mrp": st.column_config.CheckboxColumn("Prioridade MRP"),
                    },
                )

            st.markdown("### Tratativas necessárias")
            if pending.empty:
                st.success("Nenhum documento precisa de correção. O lote está pronto para geração dos arquivos.")
            else:
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
                        "natureza": st.column_config.TextColumn(
                            "Natureza",
                            width="large",
                            help="Natureza buscada primeiro na carga de NFs (STSUP01, coluna Natureza). Pode ser ajustada manualmente se necessário.",
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
                        "natureza",
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

            if duplicate.any():
                st.error("Há nomes finais duplicados no lote. Os arquivos duplicados precisam ser tratados antes do ZIP.")
            elif not invalid.empty:
                st.info("O botão de geração ficará liberado quando todas as tratativas forem concluídas.")
            else:
                normal = int((~merged["prioridade_mrp"].fillna(False).astype(bool)).sum())
                priority = int(merged["prioridade_mrp"].fillna(False).astype(bool).sum())
                st.success(
                    f"Lote aprovado: {normal} documento(s) no fluxo normal e "
                    f"{priority} em prioridade MRP."
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

            if st.button("GERAR ARQUIVOS RENOMEADOS E COMPACTADOS", type="primary", use_container_width=True, disabled=(not invalid.empty or duplicate.any())):
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
                except Exception as exc:
                    st.error(f"Falha ao gerar ZIP: {exc}")

            for zip_name, zip_bytes in st.session_state.zip_outputs.items():
                st.download_button(f"Baixar {zip_name}", zip_bytes, file_name=zip_name, mime="application/zip", type="primary", use_container_width=True, key=f"download_{zip_name}")


    with tab_danfe:
        st.markdown("### XML → DANFE")
        st.caption(
            "Geração do DANFE diretamente do XML da NF-e modelo 55 no padrão visual fixo validado: "
            "A4 retrato, canhoto superior, traços finos e proporções fixas. O layout não muda conforme "
            "o tpImp do XML. Os XMLs e PDFs gerados ficam somente nesta sessão e não são gravados no Supabase."
        )

        xml_files = st.file_uploader(
            "Selecione ou arraste os XMLs das NF-e",
            type=["xml"],
            accept_multiple_files=True,
            key="danfe_xml_uploads",
        )

        d1, d2 = st.columns([4, 1])
        generate_danfe = d1.button(
            "GERAR DANFEs",
            type="primary",
            use_container_width=True,
            disabled=not xml_files,
            key="generate_danfe_batch",
        )
        clear_danfe = d2.button(
            "Limpar",
            use_container_width=True,
            key="clear_danfe_batch",
        )

        if clear_danfe:
            st.session_state.danfe_outputs = {}
            st.session_state.danfe_results = []
            st.session_state.danfe_errors = []
            st.rerun()

        if generate_danfe:
            outputs = {}
            results = []
            errors = []

            progress = st.progress(0, text="Gerando DANFEs...")
            total_files = len(xml_files)

            for idx, xml_file in enumerate(xml_files, start=1):
                try:
                    raw_xml = xml_file.getvalue()
                    meta = extract_danfe_metadata(raw_xml)

                    pdf_bytes = generate_danfe_pdf(raw_xml)
                    pdf_name = danfe_file_name(meta)

                    outputs[pdf_name] = {
                        "bytes": pdf_bytes,
                        "xml_name": xml_file.name,
                        "numero_nf": meta.numero_nf,
                        "serie": meta.serie,
                        "emitente": meta.emitente,
                        "cnpj": meta.cnpj_emitente,
                        "chave": meta.chave,
                        "protocolo": meta.protocolo,
                        "status_codigo": meta.status_codigo,
                        "status_motivo": meta.status_motivo,
                    }

                    status_label = (
                        f"{meta.status_codigo} - {meta.status_motivo}"
                        if meta.status_codigo
                        else "SEM PROTOCOLO NO XML"
                    )

                    results.append({
                        "XML": xml_file.name,
                        "NF": meta.numero_nf,
                        "Série": meta.serie,
                        "Emitente": meta.emitente,
                        "CNPJ": meta.cnpj_emitente,
                        "Protocolo": meta.protocolo,
                        "Status": status_label,
                        "PDF": pdf_name,
                    })
                except Exception as exc:
                    errors.append({
                        "arquivo": xml_file.name,
                        "erro": str(exc),
                    })

                progress.progress(
                    idx / total_files,
                    text=f"{idx}/{total_files} — {xml_file.name}",
                )

            progress.empty()
            st.session_state.danfe_outputs = outputs
            st.session_state.danfe_results = results
            st.session_state.danfe_errors = errors

            if outputs:
                st.success(
                    f"{len(outputs)} DANFE(s) gerado(s) com sucesso. "
                    "Os arquivos estão prontos para conferência e download."
                )
            if errors:
                st.warning(
                    f"{len(errors)} XML(s) não puderam ser convertidos. "
                    "Veja os detalhes abaixo."
                )

        danfe_results = st.session_state.get("danfe_results") or []
        danfe_errors = st.session_state.get("danfe_errors") or []
        danfe_outputs = st.session_state.get("danfe_outputs") or {}

        if danfe_results:
            st.markdown("#### Conferência dos DANFEs gerados")
            st.dataframe(
                pd.DataFrame(danfe_results),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "XML": st.column_config.TextColumn("XML de origem", width="medium"),
                    "NF": "NF",
                    "Série": "Série",
                    "Emitente": st.column_config.TextColumn("Emitente", width="large"),
                    "CNPJ": "CNPJ",
                    "Protocolo": "Protocolo",
                    "Status": st.column_config.TextColumn("Autorização", width="large"),
                    "PDF": st.column_config.TextColumn("Arquivo gerado", width="large"),
                },
            )

        if danfe_errors:
            with st.expander(
                f"XMLs com erro ({len(danfe_errors)})",
                expanded=True,
            ):
                st.dataframe(
                    pd.DataFrame(danfe_errors),
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "arquivo": "Arquivo",
                        "erro": st.column_config.TextColumn("Erro", width="large"),
                    },
                )

        if danfe_outputs:
            st.markdown("#### Arquivos para download")

            if len(danfe_outputs) > 1:
                batch_buffer = io.BytesIO()
                with zipfile.ZipFile(
                    batch_buffer,
                    "w",
                    zipfile.ZIP_DEFLATED,
                ) as archive:
                    for pdf_name, item in danfe_outputs.items():
                        archive.writestr(pdf_name, item["bytes"])

                st.download_button(
                    "BAIXAR TODOS OS DANFEs (.ZIP)",
                    batch_buffer.getvalue(),
                    file_name=f"DANFEs_{now_local():%Y%m%d_%H%M%S}.zip",
                    mime="application/zip",
                    type="primary",
                    use_container_width=True,
                    key="download_all_danfes",
                )

            for pos, (pdf_name, item) in enumerate(danfe_outputs.items(), start=1):
                label = (
                    f"Baixar NF {item.get('numero_nf') or '-'} — "
                    f"{item.get('emitente') or pdf_name}"
                )
                st.download_button(
                    label,
                    item["bytes"],
                    file_name=pdf_name,
                    mime="application/pdf",
                    use_container_width=True,
                    key=f"download_danfe_{pos}_{pdf_name}",
                )


    with tab_cte:
        st.markdown("### CT-e")
        st.info("Módulo reservado. O fluxo seguirá a mesma arquitetura validada para NF-e, mas só será ativado após recebermos exemplos reais de CT-e e fecharmos as regras de extração e nomenclatura.")
        st.code("NUMERO CTE - TRANSPORTADORA - NUMERO NF - FORNECEDOR NF.pdf", language=None)


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
        f'<div class="sidebar-info-card"><b>Data operacional</b><br>{now_local():%d/%m/%Y}<br><br><b>Banco de dados</b><br>{db_text}<br><br><b>Fluxo</b><br>NF-e → conferência → ZIP<br><br><b>Modo</b><br>{_mode_text}<br><br><b>Versão</b><br>Protótipo 0.2</div>',
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



elif page == "Pendências":
    _control_docs_title = str(cfg.get("control_docs_label") or DEFAULT["control_docs_label"]).strip()
    st.markdown(
        f'<div class="section-title">{_control_docs_title}</div>',
        unsafe_allow_html=True,
    )
    st.caption(
        "Centraliza a conferência de pré-notas, o impacto no MRP e o processamento de XMLs/PDFs em um único fluxo operacional."
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

    pend_pre_tab, pend_mrp_tab, pend_process_tab = st.tabs(["Pré-notas pendentes", "Impacto MRP", "Processamento de arquivos"])

    with pend_pre_tab:
        if pre_base.empty:
            st.info(
                "A base de pré-notas ainda não foi carregada. "
                "Use Configurações > Alimentação > Validação Pré-notas."
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
            pending_view["validacao_documento"] = "PENDENTE DE DOCUMENTO"
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
                "prioridade",
                "situacao_mrp",
                "aderencia_fornecedor",
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
                    "validacao_documento": st.column_config.TextColumn(
                        "Validação documento",
                        width="medium",
                    ),
                },
            )
            st.caption(
                f"Exibindo {len(filtered)} de {len(pending_view)} pré-nota(s) pendente(s)."
            )

    with pend_mrp_tab:
        render_mrp_priority_feed("pendencias_mrp", allow_feed=False)

    with pend_process_tab:
        render_file_processing()


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
            control_docs_label = st.text_input(
                "Nome da aba Controle de documentos",
                str(cur.get("control_docs_label") or DEFAULT["control_docs_label"]),
                help="Altera o nome exibido no menu lateral e no título da página que reúne pré-notas, MRP e processamento de arquivos.",
            )
            intro = st.text_area("Texto da tela principal", cur["intro"])
            footer = st.text_input("Rodapé", cur["footer"])
            natures = st.text_input("Naturezas para atribuição rápida (separadas por vírgula)", str(cur.get("naturezas") or "MP,MC"))
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
            show_flash("_flash_pre")
            st.markdown("### Validação de pré-notas")
            st.write(
                "Formato validado: A = Data, C = Número da NF, D = Fornecedor, E = CNPJ e F = Status. "
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
                    "A conferência operacional fica em Controle de Doc."
                )
            else:
                st.info("Nenhuma carga de pré-notas confirmada nesta sessão.")


        with feed_mrp:
            render_mrp_priority_feed("config_mrp")


        with feed_sup:
            show_flash("_flash_supplier")
            st.markdown("### Base de fornecedores")
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
