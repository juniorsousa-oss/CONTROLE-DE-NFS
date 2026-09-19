from __future__ import annotations

import hashlib
import io
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date
from typing import Iterable

import fitz  # PyMuPDF
import pandas as pd
from rapidfuzz import fuzz, process

try:
    import pytesseract
    from PIL import Image
except Exception:
    pytesseract = None
    Image = None

DATE_RE = re.compile(r"\b([0-3]\d)/([01]\d)/(20\d{2})\b")
KEY_GROUPED_RE = re.compile(r"\b(?:\d{4}\s+){10}\d{4}\b")
KEY_COMPACT_RE = re.compile(r"\b\d{44}\b")
CNPJ_RE = re.compile(r"\b\d{2}[. ]?\d{3}[. ]?\d{3}[/ ]?\d{4}[- ]?\d{2}\b")


def digits_only(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def strip_accents_upper(value: object) -> str:
    raw = unicodedata.normalize("NFKD", str(value or ""))
    raw = "".join(ch for ch in raw if not unicodedata.combining(ch))
    return raw.upper()


def normalize_text(value: object) -> str:
    return re.sub(r"\s+", " ", strip_accents_upper(value)).strip()


def sanitize_filename_part(value: object) -> str:
    text = str(value or "").strip()
    text = re.sub(r'[<>:"/\\|?*]', " ", text)
    return re.sub(r"\s+", " ", text).strip(" .-")


def format_cnpj(cnpj: str) -> str:
    cnpj = digits_only(cnpj)
    if len(cnpj) != 14:
        return cnpj
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"


def valid_cnpj(value: object) -> bool:
    cnpj = digits_only(value)
    if len(cnpj) != 14 or len(set(cnpj)) == 1:
        return False

    def check(base: str, weights: list[int]) -> str:
        total = sum(int(d) * w for d, w in zip(base, weights))
        remainder = total % 11
        digit = 0 if remainder < 2 else 11 - remainder
        return str(digit)

    d1 = check(cnpj[:12], [5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    d2 = check(cnpj[:12] + d1, [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2])
    return cnpj[-2:] == d1 + d2


def extract_pdf_text(pdf_bytes: bytes, ocr_fallback: bool = True) -> tuple[str, str]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    texts = [(page.get_text("text") or "") for page in doc]
    text = "\n".join(texts).strip()
    if len(re.sub(r"\s+", "", text)) >= 160:
        return text, "TEXTO PDF"
    if not ocr_fallback or pytesseract is None or Image is None:
        return text, "SEM TEXTO / OCR INDISPONÍVEL"
    ocr_pages: list[str] = []
    for page in doc:
        pix = page.get_pixmap(matrix=fitz.Matrix(2.0, 2.0), alpha=False)
        image = Image.open(io.BytesIO(pix.tobytes("png")))
        try:
            ocr_pages.append(pytesseract.image_to_string(image, lang="por"))
        except Exception:
            ocr_pages.append(pytesseract.image_to_string(image))
    ocr_text = "\n".join(ocr_pages).strip()
    return (ocr_text, "OCR") if len(ocr_text) > len(text) else (text, "SEM TEXTO / OCR SEM RESULTADO")


def find_access_key(text: str) -> str:
    scope = text[:12000]
    for pattern in (KEY_GROUPED_RE, KEY_COMPACT_RE):
        for match in pattern.finditer(scope):
            candidate = digits_only(match.group(0))
            if len(candidate) == 44 and candidate[20:22] in {"55", "57"}:
                return candidate
    normalized = strip_accents_upper(scope)
    anchor = normalized.find("CHAVE DE ACESSO")
    if anchor >= 0:
        raw_window = scope[max(0, anchor - 700): anchor + 250]
        grouped = KEY_GROUPED_RE.search(raw_window)
        if grouped:
            candidate = digits_only(grouped.group(0))
            if len(candidate) == 44:
                return candidate
    return ""


def parse_access_key(key: str) -> dict[str, str]:
    key = digits_only(key)
    if len(key) != 44:
        return {}
    return {
        "uf": key[0:2],
        "aamm": key[2:6],
        "cnpj": key[6:20],
        "modelo": key[20:22],
        "serie": str(int(key[22:25] or "0")),
        "numero": str(int(key[25:34] or "0")),
    }


def _first_valid_cnpj(text: str) -> str:
    for match in CNPJ_RE.finditer(text):
        cnpj = digits_only(match.group(0))
        if len(cnpj) == 14:
            return cnpj
    return ""


def extract_emitter_cnpj(text: str) -> str:
    normalized = strip_accents_upper(text)
    emit_pos = normalized.find("IDENTIFICACAO DO EMITENTE")
    dest_pos = normalized.find("DESTINATARIO/REMETENTE")
    if emit_pos >= 0:
        end = dest_pos if dest_pos > emit_pos else min(len(text), emit_pos + 5000)
        candidate = _first_valid_cnpj(text[emit_pos:end])
        if candidate:
            return candidate
    if dest_pos > 0:
        candidate = _first_valid_cnpj(text[:dest_pos])
        if candidate:
            return candidate
    return ""


def extract_nf_number(text: str) -> str:
    patterns = [r"NF-e\s*\n?\s*N\.?\s*0*(\d{1,9})", r"\bN\.?\s*0*(\d{1,9})\s*\n?\s*S[ÉE]RIE"]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            return str(int(match.group(1)))
    return ""


def extract_series(text: str) -> str:
    match = re.search(r"S[ÉE]RIE\s*0*(\d{1,3})", text, flags=re.IGNORECASE)
    return str(int(match.group(1))) if match else ""


def extract_emitter_name(text: str) -> str:
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    lines = [line for line in lines if line]
    for idx, line in enumerate(lines):
        if normalize_text(line) == "IDENTIFICACAO DO EMITENTE":
            candidates = []
            for next_line in lines[idx + 1: idx + 7]:
                n = normalize_text(next_line)
                if any(token in n for token in ["DANFE", "DOCUMENTO AUXILIAR", "AV ", "AV.", "RUA ", "ROD ", "FONE", "CEP"]):
                    break
                if not re.fullmatch(r"[\d .,/:-]+", next_line):
                    candidates.append(next_line)
            if candidates:
                return " ".join(candidates[:2]).strip()
    return ""


def extract_due_dates(text: str, reference_aamm: str = "") -> list[date]:
    normalized = strip_accents_upper(text)
    start = next(
        (
            normalized.find(a)
            for a in ["FATURA", "DUPLICATA", "DUPLICATAS"]
            if normalized.find(a) >= 0
        ),
        -1,
    )

    scopes: list[str] = []
    if start >= 0:
        end_positions = [
            normalized.find(m, start + 5)
            for m in [
                "CALCULO DO IMPOSTO",
                "CALCULO DO ICMS",
                "TRANSPORTADOR/VOLUMES",
            ]
        ]
        end_positions = [pos for pos in end_positions if pos >= 0]
        end = min(end_positions) if end_positions else min(len(text), start + 3200)
        scopes.append(text[start:end])

    dates: list[date] = []
    for scope in scopes:
        for d, m, y in DATE_RE.findall(scope):
            try:
                dates.append(date(int(y), int(m), int(d)))
            except ValueError:
                pass

    if dates:
        return sorted(set(dates))

    # Alguns DANFEs recebem o vencimento pelo carimbo operacional.
    # Nesse caso pode vir apenas como "VENC. 09/10", sem o ano.
    labeled = re.compile(
        r"(?:VENCIMENTO|VENCTO|VCTO|VENC\.?)\s*[:\-]?\s*"
        r"([0-3]?\d)[/\.\-]([01]?\d)(?:[/\.\-](\d{2,4}))?",
        flags=re.IGNORECASE,
    )

    ref_year = None
    ref_month = None
    aamm = digits_only(reference_aamm)
    if len(aamm) == 4:
        try:
            ref_year = 2000 + int(aamm[:2])
            ref_month = int(aamm[2:4])
        except ValueError:
            ref_year = None
            ref_month = None

    for d, m, y in labeled.findall(normalized):
        try:
            day = int(d)
            month = int(m)

            if y:
                year = int(y)
                if year < 100:
                    year += 2000
            elif ref_year is not None:
                year = ref_year
                # Se a NF for do fim do ano e o vencimento cair em mês anterior,
                # trata como virada para o ano seguinte.
                if ref_month is not None and month < ref_month:
                    year += 1
            else:
                # Sem ano explícito e sem referência segura, não inventa a data.
                continue

            dates.append(date(year, month, day))
        except ValueError:
            pass

    return sorted(set(dates))


def extract_internal_nature(
    text: str,
    allowed_natures: Iterable[str] | None = None,
) -> str:
    """Extrai qualquer natureza registrada no carimbo operacional.

    allowed_natures é mantido apenas por compatibilidade com chamadas antigas.
    Ele NÃO funciona mais como lista restritiva: o valor encontrado na NF deve
    prevalecer, inclusive quando for uma descrição longa e quebrada em linhas.
    """
    if not text:
        return ""

    raw_lines = [
        re.sub(r"\s+", " ", str(line or "")).strip()
        for line in text.splitlines()
    ]
    raw_lines = [line for line in raw_lines if line]

    stop_re = re.compile(
        r"^(?:DATA\s+(?:DA\s+)?CHEGADA|CR|DESC\s*CR|RECEBIDO\s+POR|"
        r"RECEBEDOR|USUARIO|USUÁRIO|DATA\s+RECEBIMENTO)\s*[:\-]?",
        flags=re.IGNORECASE,
    )

    for idx, line in enumerate(raw_lines):
        normalized_line = strip_accents_upper(line)

        if re.search(r"\bNATUREZA\s+DA\s+OPERACAO\b", normalized_line):
            continue

        match = re.search(
            r"\b(?:NATUREZA(?:\s+INTERNA)?|NAT\.?\s+INTERNA)\s*[:\-]\s*(.*)$",
            line,
            flags=re.IGNORECASE,
        )
        if not match:
            continue

        parts: list[str] = []
        first = re.sub(r"\s+", " ", match.group(1) or "").strip(" :-")
        if first:
            parts.append(first)

        for next_line in raw_lines[idx + 1 : idx + 4]:
            if stop_re.search(next_line):
                break
            next_norm = strip_accents_upper(next_line)
            if re.search(r"\bNATUREZA\s+DA\s+OPERACAO\b", next_norm):
                break
            if re.match(r"^[A-ZÁÀÃÂÉÊÍÓÔÕÚÇ ]+\s*:", next_line, flags=re.IGNORECASE):
                break
            parts.append(next_line)

        value = " ".join(parts)
        value = re.sub(r"\s+", " ", value).strip(" .:-")
        value = sanitize_filename_part(value).upper()

        if value:
            return value

    return ""


def extract_stamp_text(pdf_bytes: bytes) -> str:
    """OCR leve somente na faixa inferior das páginas, onde fica o carimbo operacional."""
    if pytesseract is None or Image is None:
        return ""

    pieces: list[str] = []
    try:
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        for page in doc:
            rect = page.rect
            # Carimbo costuma estar na metade inferior do DANFE. Recortar reduz muito
            # o custo em comparação a OCR da página inteira.
            clip = fitz.Rect(
                rect.x0,
                rect.y0 + rect.height * 0.48,
                rect.x1,
                rect.y1,
            )
            pix = page.get_pixmap(
                matrix=fitz.Matrix(1.65, 1.65),
                clip=clip,
                alpha=False,
            )
            image = Image.open(io.BytesIO(pix.tobytes("png")))
            try:
                stamp = pytesseract.image_to_string(
                    image,
                    lang="por",
                    config="--psm 6",
                )
            except Exception:
                stamp = pytesseract.image_to_string(
                    image,
                    config="--psm 6",
                )
            if stamp and stamp.strip():
                pieces.append(stamp.strip())
        doc.close()
    except Exception:
        return ""

    return "\n".join(pieces)


def supplier_dataframe(raw: pd.DataFrame | Iterable[dict] | None) -> pd.DataFrame:
    columns = ["cnpj", "nome_padrao", "aliases", "ativo", "codigo", "loja", "nome_fantasia", "tipo"]
    if raw is None:
        return pd.DataFrame(columns=columns)
    frame = raw.copy() if isinstance(raw, pd.DataFrame) else pd.DataFrame(list(raw))
    for col in columns:
        if col not in frame.columns:
            frame[col] = True if col == "ativo" else ""
    frame["cnpj"] = frame["cnpj"].map(digits_only)
    for col in ["nome_padrao", "aliases", "codigo", "loja", "nome_fantasia", "tipo"]:
        frame[col] = frame[col].fillna("").astype(str).str.strip()
    frame["ativo"] = frame["ativo"].fillna(True).astype(bool)
    return frame[columns]


def match_supplier(cnpj: str, emitter_name: str, suppliers: pd.DataFrame) -> dict[str, object]:
    active = supplier_dataframe(suppliers)
    active = active[active["ativo"]].copy()
    cnpj = digits_only(cnpj)
    if cnpj:
        exact = active[active["cnpj"] == cnpj]
        if not exact.empty:
            return {"nome_padrao": exact.iloc[0]["nome_padrao"], "metodo": "CNPJ exato", "score": 100}
        root = cnpj[:8]
        root_matches = active[active["cnpj"].str[:8] == root]
        if len(root_matches) == 1:
            return {"nome_padrao": root_matches.iloc[0]["nome_padrao"], "metodo": "Raiz do CNPJ", "score": 92}

    emitter_norm = normalize_text(emitter_name)
    if emitter_norm and not active.empty:
        choices: dict[str, int] = {}
        for idx, row in active.iterrows():
            variants = [row["nome_padrao"]] + [x.strip() for x in str(row["aliases"]).split("|") if x.strip()]
            for variant in variants:
                value = normalize_text(variant)
                if value:
                    choices[f"{idx}::{value}"] = idx
        if choices:
            result = process.extractOne(
                emitter_norm,
                list(choices.keys()),
                scorer=lambda a, b, **_: fuzz.token_set_ratio(a.split("::", 1)[-1], b.split("::", 1)[-1]),
            )
            if result:
                selected_key, score, _ = result
                idx = choices[selected_key]
                if score >= 74:
                    return {"nome_padrao": active.loc[idx, "nome_padrao"], "metodo": "Nome aproximado", "score": int(round(score))}
    return {"nome_padrao": emitter_name.strip(), "metodo": "Não vinculado", "score": 0}


def build_final_name(vencimento: date | None, numero_nf: str, fornecedor: str) -> str:
    # NaT/NaN podem chegar aqui depois da montagem do DataFrame.
    try:
        if vencimento is None or pd.isna(vencimento):
            return ""
    except Exception:
        pass

    if not isinstance(vencimento, date):
        return ""

    numero_bruto = digits_only(numero_nf)
    if not numero_bruto:
        return ""
    numero = numero_bruto.lstrip("0") or "0"

    try:
        if fornecedor is None or pd.isna(fornecedor):
            return ""
    except Exception:
        pass

    fornecedor = sanitize_filename_part(fornecedor)
    if not fornecedor:
        return ""

    try:
        vencimento_texto = vencimento.strftime("%d.%m")
    except (ValueError, AttributeError, TypeError):
        return ""

    return f"VENC. {vencimento_texto} - {numero} - {fornecedor}.pdf"


@dataclass
class NFResult:
    file_id: str
    arquivo_original: str
    tipo: str
    chave_nfe: str
    numero_nf: str
    serie: str
    cnpj_fornecedor: str
    fornecedor_lido: str
    fornecedor_padrao: str
    vencimento: date | None
    natureza: str
    metodo_fornecedor: str
    confianca: int
    leitura: str
    status: str
    nome_sugerido: str
    observacao: str

    def to_dict(self) -> dict:
        return asdict(self)


def inspect_nf_pdf_identity(
    file_name: str,
    pdf_bytes: bytes,
    suppliers: pd.DataFrame,
) -> dict:
    """Leitura leve usada somente no pré-filtro do lote.

    Evita OCR de página inteira e não tenta natureza/vencimento. O processamento
    completo só acontece depois que o documento é confirmado contra a lista de
    pré-notas pendentes.
    """
    try:
        text, reading_method = extract_pdf_text(pdf_bytes, ocr_fallback=False)
    except Exception as exc:
        return {
            "arquivo": file_name,
            "numero_nf": "",
            "serie": "",
            "chave_nfe": "",
            "cnpj_fornecedor": "",
            "fornecedor_lido": "",
            "fornecedor_padrao": "",
            "metodo_fornecedor": "",
            "confianca_fornecedor": 0,
            "leitura": "ERRO",
            "erro": str(exc),
        }

    key = find_access_key(text)
    key_info = parse_access_key(key)
    numero = key_info.get("numero") or extract_nf_number(text)
    serie = key_info.get("serie") or extract_series(text)
    cnpj = key_info.get("cnpj") or extract_emitter_cnpj(text)
    emitter = extract_emitter_name(text)

    matched = match_supplier(cnpj, emitter, suppliers)
    supplier = str(matched.get("nome_padrao") or "").strip()
    method = str(matched.get("metodo") or "")
    score = int(matched.get("score") or 0)

    return {
        "arquivo": file_name,
        "numero_nf": numero,
        "serie": serie,
        "chave_nfe": key,
        "cnpj_fornecedor": format_cnpj(cnpj),
        "fornecedor_lido": emitter,
        "fornecedor_padrao": supplier,
        "metodo_fornecedor": method,
        "confianca_fornecedor": score,
        "leitura": reading_method,
        "erro": "",
    }


def process_nf_pdf(
    file_name: str,
    pdf_bytes: bytes,
    suppliers: pd.DataFrame,
    ocr_fallback: bool = True,
    allowed_natures: Iterable[str] | None = None,
) -> NFResult:
    file_id = hashlib.sha256(pdf_bytes).hexdigest()[:16]
    try:
        text, reading_method = extract_pdf_text(pdf_bytes, ocr_fallback=ocr_fallback)
    except Exception as exc:
        return NFResult(file_id, file_name, "NF-e", "", "", "", "", "", "", None, "", "Falha de leitura", 0, "ERRO", "REVISAR", "", f"Falha ao abrir/analisar PDF: {exc}")

    key = find_access_key(text)
    key_info = parse_access_key(key)
    numero = key_info.get("numero") or extract_nf_number(text)
    serie = key_info.get("serie") or extract_series(text)
    cnpj = key_info.get("cnpj") or extract_emitter_cnpj(text)
    emitter = extract_emitter_name(text)
    due_dates = extract_due_dates(text, key_info.get("aamm", ""))
    due = due_dates[0] if due_dates else None

    # Regra operacional SETTA: a natureza interna não é inferida do PDF,
    # do texto fiscal nem de carimbo antigo. A única fonte válida é a carga
    # de Nota Fiscal (STSUP01), aplicada posteriormente no cruzamento do app.
    nature = ""

    matched = match_supplier(cnpj, emitter, suppliers)
    supplier = str(matched.get("nome_padrao") or "").strip()
    supplier_method = str(matched.get("metodo") or "")
    supplier_score = int(matched.get("score") or 0)

    score = 0
    notes: list[str] = []
    if key:
        score += 35
    elif numero and cnpj:
        score += 24
        notes.append("Chave da NF-e não identificada; número/CNPJ lidos por campos do DANFE.")
    else:
        notes.append("Chave da NF-e não identificada.")
    if numero:
        score += 20
    else:
        notes.append("Número da NF não encontrado.")
    if due:
        score += 25
        if len(due_dates) > 1:
            notes.append(f"{len(due_dates)} parcelas localizadas; utilizado o primeiro vencimento.")
    else:
        notes.append("Vencimento não encontrado no bloco de FATURA/DUPLICATAS.")
    if supplier_method == "CNPJ exato":
        score += 20
    elif supplier_method == "Raiz do CNPJ":
        score += 16
        notes.append("Fornecedor vinculado pela raiz do CNPJ; conferir filial.")
    elif supplier_method == "Nome aproximado":
        score += min(15, round(supplier_score * 0.15))
        notes.append(f"Fornecedor vinculado por similaridade de nome ({supplier_score}%).")
    else:
        notes.append("Fornecedor não encontrado na base; necessário validar na conferência.")
    notes.append(
        "Natureza interna aguardando vínculo com a carga de Nota Fiscal (STSUP01)."
    )

    score = min(100, int(score))
    final_name = build_final_name(due, numero, supplier)
    required_ok = bool(numero and due and supplier and nature and valid_cnpj(cnpj))
    high_confidence = supplier_method == "CNPJ exato" and bool(key)
    status = "APROVADO" if required_ok and high_confidence and score >= 90 else "REVISAR"

    return NFResult(
        file_id=file_id,
        arquivo_original=file_name,
        tipo="NF-e",
        chave_nfe=key,
        numero_nf=numero,
        serie=serie,
        cnpj_fornecedor=format_cnpj(cnpj),
        fornecedor_lido=emitter,
        fornecedor_padrao=supplier,
        vencimento=due,
        natureza=nature,
        metodo_fornecedor=supplier_method,
        confianca=score,
        leitura=reading_method,
        status=status,
        nome_sugerido=final_name,
        observacao=" ".join(notes).strip(),
    )
