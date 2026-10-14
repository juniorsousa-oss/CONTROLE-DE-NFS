"""Prévia de cobrança contábil: exclusivamente notas vencidas após STSUP01 válido.

Este módulo NÃO envia e-mail nem contém destinatários. O envio automático
fica desabilitado até integrar provedor autorizado, agendamento independente
do Streamlit e idempotência persistente para no máximo dois disparos/dia.
"""
from __future__ import annotations

from datetime import datetime
from html import escape

import pandas as pd

COLUNAS_EMAIL = (
    ("numero_nf", "NF"),
    ("fornecedor_padrao", "FORNECEDOR"),
    ("natureza", "NATUREZA"),
    ("enviado_em_local", "DATA DE ENVIO"),
    ("arquivo_final", "NOME DO ARQUIVO"),
)
STATUS_COBRANCA = "ATRASADO - COBRAR LANÇAMENTO"
LIMITE_DIARIO_PREVISTO = 2
COLUNAS_INTERNAS = [
    "numero_nf", "fornecedor_padrao", "natureza",
    "enviado_em_local", "arquivo_final", "prazo_lancamento",
    "situacao_lancamento",
]


def _texto(value: object) -> str:
    if value is None or pd.isna(value):
        return ""
    return str(value).strip()


def _data_envio(value: object) -> str:
    data = pd.to_datetime(value, errors="coerce")
    if pd.isna(data):
        return ""
    return data.strftime("%d/%m/%Y %H:%M")


def preparar_cobrancas(tracking: pd.DataFrame | None) -> pd.DataFrame:
    """Filtra atrasos confirmados no último STSUP01; não inclui base desatualizada.

    tracking deve ser gerado por launch_tracking_frame, que já aplica as
    regras de tipo, natureza, envio, deadline e lançamento (TES).
    """
    cols = [label for _, label in COLUNAS_EMAIL]
    if not isinstance(tracking, pd.DataFrame) or tracking.empty:
        return pd.DataFrame(columns=cols)
    required = {"situacao_lancamento", "numero_nf", "natureza", "prazo_lancamento"}
    if not required.issubset(tracking.columns):
        raise ValueError("Relatório de acompanhamento sem colunas obrigatórias.")
    chosen = tracking.loc[
        tracking["situacao_lancamento"].eq(STATUS_COBRANCA)
    ].copy()
    if chosen.empty:
        return pd.DataFrame(columns=cols)
    # Proteção adicional: não permitir confirmação de lançamento na cobrança,
    # mesmo com linhas de teste que tenham status inconsistente.
    if "lancado_em_local" in chosen:
        launched = pd.to_datetime(chosen["lancado_em_local"], errors="coerce")
        chosen = chosen.loc[launched.isna()].copy()
    rows = []
    for _, record in chosen.iterrows():
        name = _texto(record.get("arquivo_final"))
        if not name:
            name = _texto(record.get("arquivo_original"))
        rows.append({
            "NF": _texto(record.get("numero_nf")),
            "FORNECEDOR": _texto(record.get("fornecedor_padrao")),
            "NATUREZA": _texto(record.get("natureza")),
            "DATA DE ENVIO": _data_envio(record.get("enviado_em_local")),
            "NOME DO ARQUIVO": name,
        })
    result = pd.DataFrame(rows, columns=cols)
    result = result.drop_duplicates(ignore_index=True)
    return result.sort_values(by=["NF", "FORNECEDOR"], kind="stable").reset_index(drop=True)


def montar_email_html(rows: pd.DataFrame, date_ref: datetime) -> str:
    if rows is None or rows.empty:
        raise ValueError("Nenhuma NF vencida apta à cobrança.")
    if list(rows.columns) != [label for _, label in COLUNAS_EMAIL]:
        raise ValueError("Colunas inesperadas na prévia da cobrança.")

    headers = "".join(
        f'<th style="padding:10px;border:1px solid #ccd4df;text-align:left;background:#e7effa;">'
        f"{escape(col)}</th>" for col in rows.columns
    )
    trs = []
    for i, row in rows.iterrows():
        bgcolor = "#fff" if i % 2 == 0 else "#f5f8fc"
        cells = "".join(
            f'<td style="padding:10px;border:1px solid #ccd4df;vertical-align:top;">'
            f"{escape(_texto(value))}</td>" for value in row.tolist()
        )
        trs.append(f'<tr style="background:{bgcolor};">{cells}</tr>')
    table = (
        '<table role="table" style="border-collapse:collapse;width:100%;'
        'font:13px Arial,sans-serif;color:#1e293b;">'
        f"<thead><tr>{headers}</tr></thead><tbody>{''.join(trs)}</tbody></table>"
    )
    total = len(rows)
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"></head>'
        '<body style="font:14px Arial,sans-serif;color:#1e293b;line-height:1.6;">'
        '<p>Prezados,</p>'
        f'<p>Segue a relação de <strong>{total} NF(s)</strong> de compra de matéria-prima '
        'com prazo de lançamento vencido, sem confirmação no STSUP01 atualizado.</p>'
        f'{table}'
        '<p>Solicitamos verificar os lançamentos pendentes e providenciar a regularização.</p>'
        '<p>Atenciosamente,<br>Controle de NFs | SETTA</p>'
        '</body></html>'
    )


def assunto_cobranca(date_ref: datetime) -> str:
    return "SETTA | Cobrança de lançamento de NFs vencidas — " + date_ref.strftime("%d/%m/%Y")
