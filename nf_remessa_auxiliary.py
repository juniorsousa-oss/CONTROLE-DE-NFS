"""Documentos de remessa auxiliares, enviados sem pré-nota.

Somente referência fiscal explícita do CT-e, XML autorizado e natureza
fiscal de REMESSA podem autorizar a inclusão no lote. Não cria pré-nota nem
altera o fluxo de conferência/lançamento de matéria-prima.
"""
from __future__ import annotations
import base64
import re
import unicodedata

import nf_xml_library
from nf_avulsa import safe_nfe_record
from danfe_generator import generate_danfe_pdf


def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _number(value: object) -> str:
    return _digits(value).lstrip("0") or "0"


def _plain(value: object) -> str:
    result = unicodedata.normalize("NFKD", str(value or ""))
    return "".join(ch for ch in result if not unicodedata.combining(ch)).upper()


def validate_auxiliary_remessa(record: dict, raw: bytes, cte_refs: set[str],
                                expected_suppliers: set[str]) -> dict:
    """Validação fiscal obrigatória antes de transformar a remessa em anexo."""
    key = _digits(record.get("chave"))
    if key not in cte_refs or len(key) != 44 or key[20:22] != "55":
        raise ValueError("A NF-e auxiliar não pertence às referências do CT-e.")
    meta, info = safe_nfe_record(record, raw)
    issuer = _digits(info.get("cnpj_fornecedor"))
    if issuer != key[6:20] or issuer not in expected_suppliers:
        raise ValueError("O CNPJ da remessa não corresponde ao fornecedor do lote.")
    nature = str(info.get("natureza_fiscal") or "")
    if "REMESSA" not in _plain(nature):
        raise ValueError(
            f"NF {info.get('numero_nf')}: natureza fiscal '{nature}' não confirma "
            "remessa. É necessária conferência fora deste fluxo."
        )
    return {
        "chave": key,
        "numero": _number(info["numero_nf"]),
        "cnpj": issuer,
        "fornecedor": str(info.get("fornecedor_lido") or meta.emitente),
        "natureza_fiscal": nature,
        "arquivo_final": f"NF-{_number(info['numero_nf'])} - REMESSA SEM PRE-NOTA.pdf",
        "bytes": generate_danfe_pdf(raw),
    }


def load_auxiliary_remessa(key: str, cte_refs: set[str],
                           expected_suppliers: set[str]) -> dict:
    key = _digits(key)
    if key not in cte_refs or len(key) != 44 or key[20:22] != "55":
        raise ValueError("Chave de remessa não autorizada neste CT-e.")
    number, issuer = _number(key[25:34]), key[6:20]
    result = nf_xml_library.library_api(
        "match", {"nfs": [{
            "numero": number, "cnpj": issuer, "chave": key, "fornecedor": ""
        }]}, timeout=25
    )
    matches = [row for row in result.get("nfe") or []
               if _digits(row.get("chave")) == key
               and _digits(row.get("cnpj_emitente")) == issuer]
    if len(matches) != 1:
        raise ValueError(
            f"NF {number}: XML exato não localizado de forma inequívoca "
            "na Biblioteca XML."
        )
    record = matches[0]
    data = nf_xml_library.library_api(
        "download", {"id": record["id"]}, timeout=35
    )
    raw = base64.b64decode(data.get("raw_base64") or "", validate=True)
    return validate_auxiliary_remessa(
        record, raw, cte_refs, expected_suppliers
    )
