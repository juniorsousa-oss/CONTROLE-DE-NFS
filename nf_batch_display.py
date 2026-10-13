"""Visão de vínculos fiscais por lote — sem alterar registros ou XMLs."""
from __future__ import annotations

import re
import pandas as pd


def _nf(value: object) -> str:
    text = re.sub(r"\D", "", str(value or ""))
    return text.lstrip("0") or ("0" if text else "")


def _cte(value: object) -> bool:
    return str(value or "").strip().upper().replace(" ", "").replace("-", "") == "CTE"


def add_cte_links_to_batch_view(records: pd.DataFrame) -> pd.DataFrame:
    """Mostra CT-e em cada NF e a lista integral de NFs em cada CT-e.

    Usa só os dados persistidos do próprio lote; a grade não altera o banco.
    """
    if not isinstance(records, pd.DataFrame) or records.empty:
        return records.copy() if isinstance(records, pd.DataFrame) else pd.DataFrame()
    view = records.copy()
    if not {"tipo_documento", "numero_nf", "lote_id"}.issubset(view.columns):
        return view

    linked: dict[tuple[str, str], list[str]] = {}
    for _, row in view.iterrows():
        if not _cte(row.get("tipo_documento")):
            continue
        cte_number = _nf(row.get("numero_cte"))
        if not cte_number:
            continue
        lot = str(row.get("lote_id") or "")
        refs = {
            _nf(x)
            for x in re.split(r"[,;|]+", str(row.get("nfs_vinculadas") or ""))
            if _nf(x)
        }
        for number in refs:
            key = (lot, number)
            related = linked.setdefault(key, [])
            if cte_number not in related:
                related.append(cte_number)

    def related_cte(row):
        if _cte(row.get("tipo_documento")):
            return ""
        return ", ".join(
            linked.get((str(row.get("lote_id") or ""), _nf(row.get("numero_nf"))), [])
        )

    view["ctes_vinculados"] = view.apply(related_cte, axis=1)
    return view
