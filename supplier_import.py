"""Importação segura do cadastro TOTVS de fornecedores.

Descobre as colunas por cabeçalho (em vez de assumir CNPJ na coluna O),
preservando as lojas para desambiguação posterior por documento fiscal.
"""
from __future__ import annotations

import re
from collections import Counter

import pandas as pd

from nf_processor import digits_only, normalize_text, valid_cnpj


HEADER_ALIASES = {
    "codigo": {"CODIGO", "CODFORNECEDOR", "COD"},
    "loja": {"LOJA", "LOJAFORNECEDOR"},
    "nome_padrao": {"RAZAOSOCIAL", "RAZAO", "NOMEFORNECEDOR"},
    "nome_fantasia": {"NFANTASIA", "NOMEFANTASIA", "FANTASIA"},
    "tipo": {"TPOCONTRATO", "TIPOCONTRATO", "TIPO"},
    "cnpj": {"CNPJCPF", "CNPJ", "CGCCPF", "CGC"},
}
REQUIRED = {"codigo", "loja", "nome_padrao", "cnpj"}


def _header_key(value: object) -> str:
    return re.sub(r"[^A-Z0-9]", "", normalize_text(value))


def _excel_col(index: int) -> str:
    index += 1
    label = ""
    while index:
        index, digit = divmod(index - 1, 26)
        label = chr(65 + digit) + label
    return label


def parse_supplier_report(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, str]]:
    """Localiza a linha do cabeçalho e identifica a coluna CNPJ/CPF real."""
    if not isinstance(raw, pd.DataFrame) or raw.empty:
        raise ValueError("O relatório FORNECEDORES está vazio.")

    positions = None
    header_row = None
    for row_idx in range(min(15, len(raw))):
        values = raw.iloc[row_idx].tolist()
        found = {}
        for col_idx, value in enumerate(values):
            normalized = _header_key(value)
            for field, choices in HEADER_ALIASES.items():
                if normalized in choices and field not in found:
                    found[field] = col_idx
        if REQUIRED.issubset(found):
            positions = found
            header_row = row_idx
            break

    if positions is None:
        raise ValueError(
            "Não foi possível reconhecer Código, Loja, Razão Social e CNPJ/CPF "
            "no cabeçalho do relatório FORNECEDORES. Nenhum cadastro foi alterado."
        )

    body = raw.iloc[header_row + 1 :].copy()
    incoming = pd.DataFrame(index=body.index)
    for field in ("codigo", "loja", "nome_padrao", "nome_fantasia", "tipo", "cnpj"):
        if field in positions:
            incoming[field] = body.iloc[:, positions[field]].fillna("").astype(str).str.strip()
        else:
            incoming[field] = ""
    incoming["cnpj"] = incoming["cnpj"].map(digits_only)
    incoming = incoming.loc[
        incoming[["codigo", "loja", "nome_padrao", "cnpj"]].ne("").any(axis=1)
    ].copy()
    incoming["aliases"] = incoming["nome_fantasia"]
    incoming["ativo"] = True
    columns = {key: _excel_col(idx) for key, idx in positions.items()}
    return incoming.reset_index(drop=True), columns


def validate_supplier_report(raw: pd.DataFrame) -> dict:
    incoming, columns = parse_supplier_report(raw)
    if incoming.empty:
        raise ValueError("O relatório não contém fornecedores após o cabeçalho.")

    valid_mask = incoming["cnpj"].map(valid_cnpj) & incoming["nome_padrao"].ne("")
    valid = incoming.loc[valid_mask].copy()
    invalid = incoming.loc[~valid_mask].copy()
    if valid.empty:
        raise ValueError(
            "Nenhum CNPJ válido foi encontrado na coluna de CNPJ/CPF identificada "
            f"({columns['cnpj']}). A base original foi preservada."
        )

    # Duplicação por código/loja não pode produzir diferentes identidades fiscais.
    conflicting_shops = valid.groupby(["codigo", "loja"])["cnpj"].nunique()
    if (conflicting_shops > 1).any():
        raise ValueError(
            f"{int((conflicting_shops > 1).sum())} código(s)/loja(s) têm CNPJs distintos. "
            "A base original foi preservada; confira o cadastro."
        )

    # Um mesmo CNPJ pode estar cadastrado em códigos/lojas distintos; todos os
    # vínculos devem permanecer disponíveis, sem colapsar em apenas uma linha.
    variants_by_doc = valid.groupby("cnpj")["nome_padrao"].apply(list)
    conflicting_documents = []
    for doc, names in variants_by_doc.items():
        compact = [
            re.sub(r"[^A-Z0-9]", "", normalize_text(name))
            for name in names
        ]
        root = min(compact, key=len)
        if not all(
            name == root or name.startswith(root) or root.startswith(name)
            for name in compact
        ):
            conflicting_documents.append(doc)

    conflicting_set = set(conflicting_documents)
    conflicts = valid.loc[valid["cnpj"].isin(conflicting_set)].copy()
    clean = valid.loc[~valid["cnpj"].isin(conflicting_set)].copy()
    repeated_links = int(clean.duplicated(["codigo", "loja", "cnpj"]).sum())
    clean = clean.drop_duplicates(["codigo", "loja", "cnpj"], keep="first")

    stats = {
        "total": len(incoming),
        "validos": len(clean),
        "invalidos": len(invalid),
        "cpfs": int(incoming["cnpj"].str.len().eq(11).sum()),
        "duplicados": repeated_links,
        "conflitos": len(conflicting_documents),
        "cnpjs_distintos": clean["cnpj"].nunique(),
        "colunas": columns,
    }
    return {
        "clean": clean.reset_index(drop=True),
        "conflicts": conflicts.reset_index(drop=True),
        "stats": stats,
        "columns": columns,
    }
