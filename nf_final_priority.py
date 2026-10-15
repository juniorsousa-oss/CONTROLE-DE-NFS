"""Atualização exclusiva da prioridade manual antes da geração final.
A classificação MRP permanece calculada pelo motor existente; esta rotina
apenas aplica flags manuais usando o file_id estável do lote.
"""
from __future__ import annotations

import pandas as pd


def apply_final_manual_priorities(frame: pd.DataFrame,
                                  edited: pd.DataFrame) -> pd.DataFrame:
    if frame.empty or "file_id" not in frame or "file_id" not in edited:
        raise ValueError("A seleção não possui os identificadores do lote.")
    ids = frame["file_id"].fillna("").astype(str).tolist()
    selected = edited["file_id"].fillna("").astype(str).tolist()
    if (not all(ids) or len(ids) != len(set(ids))
            or len(ids) != len(selected) or set(ids) != set(selected)
            or len(selected) != len(set(selected))):
        raise ValueError("A conferência foi alterada. Reabra o lote e confira as NFs.")
    if "prioridade_manual" not in edited:
        raise ValueError("Coluna de prioridade manual indisponível.")
    if not edited["prioridade_manual"].map(lambda v: isinstance(v, (bool, int))).all():
        raise ValueError("Marque ou desmarque somente os checkboxes de prioridade.")
    selected_flags = dict(zip(
        selected, edited["prioridade_manual"].fillna(False).astype(bool).tolist()
    ))
    out = frame.copy()
    out["prioridade_manual"] = [selected_flags[key] for key in ids]
    base = out.get("prioridade_mrp_base", pd.Series(False, index=out.index))
    out["prioridade_mrp"] = (
        base.fillna(False).astype(bool)
        | out["prioridade_manual"].fillna(False).astype(bool)
    )
    return out
