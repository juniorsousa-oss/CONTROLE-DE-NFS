"""Liberação de exclusões manuais somente após confirmação fiscal segura.

Ausência no MES PRÉ NOTAS não prova lançamento. Uma mesma NF pode existir
para vários fornecedores: todas as identidades conhecidas precisam ser
confirmadas pelo STSUP01, com TES preenchida, usando a regra principal.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Callable

import pandas as pd

from nf_launch_validation import validar_lancamento_nf


def excluded_nfs_with_confirmed_launch(
    active_numbers: set[str],
    pre_notes: pd.DataFrame,
    launch_report: pd.DataFrame,
    *,
    normalize_nf: Callable,
    normalize_name: Callable,
    supplier_similarity: Callable,
    normalize_supplier_code: Callable,
    digits_only: Callable,
) -> list[str]:
    if not active_numbers or not isinstance(pre_notes, pd.DataFrame):
        return []
    if pre_notes.empty or not isinstance(launch_report, pd.DataFrame) or launch_report.empty:
        return []
    if not {"numero_nf", "fornecedor", "cnpj"}.issubset(pre_notes.columns):
        return []
    if not {"numero_nf", "fornecedor_codigo", "fornecedor", "tes"}.issubset(launch_report.columns):
        return []

    active = {normalize_nf(n) for n in active_numbers if normalize_nf(n)}
    pre_by_number = defaultdict(list)
    for item in pre_notes.to_dict(orient="records"):
        number = normalize_nf(item.get("numero_nf"))
        if number not in active:
            continue
        company = digits_only(item.get("cnpj"))
        name = str(item.get("fornecedor") or "").strip()
        # Sem identidade de origem não existe confirmação segura.
        if len(company) != 14 and not normalize_name(name):
            continue
        pre_by_number[number].append({
            "numero_nf": number,
            "cnpj_fornecedor": company,
            "fornecedor_padrao": name,
        })

    # O relatório deve ter o CNPJ já resolvido pelo cadastro SETTA;
    # se não existir, a validação usa apenas igualdade exata de nome.
    report_by_number = defaultdict(list)
    for item in launch_report.to_dict(orient="records"):
        number = normalize_nf(item.get("numero_nf"))
        if number in active:
            report_by_number[number].append(item)

    confirmed = []
    for number in sorted(active):
        source_rows = pre_by_number.get(number, [])
        report_rows = report_by_number.get(number, [])
        if not source_rows or not report_rows:
            # Jamais limpar exclusão apenas porque o número desapareceu.
            continue
        if all(
            validar_lancamento_nf(
                row, report_rows,
                normalizar_nome=normalize_name,
                similaridade=supplier_similarity,
                normalizar_codigo=normalize_supplier_code,
                somente_digitos=digits_only,
            ) == "CONFIRMADO"
            for row in source_rows
        ):
            confirmed.append(number)
    return confirmed
