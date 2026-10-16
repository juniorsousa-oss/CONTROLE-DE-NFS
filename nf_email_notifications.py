"""Prévia de cobrança contábil: exclusivamente notas vencidas após STSUP01 válido.

Este módulo NÃO envia e-mail nem contém destinatários. O envio automático
fica desabilitado até integrar provedor autorizado, agendamento independente
do Streamlit e idempotência persistente para no máximo dois disparos/dia.
"""
from __future__ import annotations

from datetime import datetime
from html import escape
from nf_launch_deadline import dias_atraso_uteis

import pandas as pd

COLUNAS_EMAIL = (
    ("numero_nf", "NF"),
    ("fornecedor_padrao", "FORNECEDOR"),
    ("natureza", "NATUREZA"),
    ("enviado_em_local", "DATA DE ENVIO"),
    ("dias_atraso_lancamento", "DIAS DE ATRASO"),
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
            "DIAS DE ATRASO": int(record.get("dias_atraso_lancamento") or 0),
            "NOME DO ARQUIVO": name,
        })
    result = pd.DataFrame(rows, columns=cols)
    result = result.drop_duplicates(ignore_index=True)
    return result.sort_values(by=["NF", "FORNECEDOR"], kind="stable").reset_index(drop=True)


def montar_email_html(rows: pd.DataFrame, date_ref: datetime, *, homologacao: bool = False) -> str:
    """Modelo enxuto para prévia local, sem mudar o envio nem as regras fiscais."""
    if rows is None or rows.empty:
        raise ValueError("Nenhuma NF vencida apta à cobrança.")
    if list(rows.columns) != [label for _, label in COLUNAS_EMAIL]:
        raise ValueError("Colunas inesperadas na prévia da cobrança.")

    headers = "".join(
        '<th scope="col" bgcolor="#efeded" style="border:1px solid #d9d9d9;'
        'padding:10px 12px;background:#efeded;color:#252a30;'
        'font:700 13px/1.4 Arial,Helvetica,sans-serif;text-align:left;">'
        f'{escape(col)}</th>' for col in rows.columns
    )
    lines = []
    for i, (_, row) in enumerate(rows.iterrows()):
        bg = "#ffffff" if i % 2 == 0 else "#faf7f6"
        cells = "".join(
            f'<td bgcolor="{bg}" style="border:1px solid #d9d9d9;'
            f'padding:10px 12px;background:{bg};color:#2b2d33;'
            'font:14px/1.5 Arial,Helvetica,sans-serif;vertical-align:top;'
            f'overflow-wrap:anywhere;word-break:break-word;">'
            f'{escape(_texto(value))}</td>'
            for value in row.tolist()
        )
        lines.append(f'<tr bgcolor="{bg}">{cells}</tr>')

    aviso = (
        '<p style="margin:0 0 24px;padding:14px;border:1px solid #e6b7b7;'
        'color:#a82929;background:#ffffff;'
        'font:700 14px/1.5 Arial,Helvetica,sans-serif;">'
        '[HOMOLOGAÇÃO / DADOS FICTÍCIOS] EXEMPLO DO E-MAIL REAL. '
        'NÃO REALIZAR COBRANÇA OU LANÇAMENTO.</p>'
    ) if homologacao else ""
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '</head><body bgcolor="#ffffff" style="margin:0;padding:0;'
        'background:#ffffff;color:#292d32;'
        'font:14px/1.6 Arial,Helvetica,sans-serif;">'
        '<div style="padding:24px 16px;max-width:100%;box-sizing:border-box;'
        'color:#292d32;background:#ffffff;">'
        f'{aviso}'
        '<p style="margin:0 0 20px;color:#292d32;'
        'font:14px/1.6 Arial,Helvetica,sans-serif;">Prezados,</p>'
        '<p style="margin:0 0 22px;color:#292d32;'
        'font:14px/1.6 Arial,Helvetica,sans-serif;">'
        f'Segue a relação de <strong>{len(rows)} NF(s)</strong> de compra de '
        'matéria-prima com prazo de lançamento vencido, '
        'sem confirmação de lançamento.</p>'
        '<table role="table" width="100%" cellspacing="0" cellpadding="0" '
        'style="width:100%;border-collapse:collapse;margin:0 0 22px;'
        'font:14px Arial,Helvetica,sans-serif;">'
        f'<thead><tr>{headers}</tr></thead><tbody>{"".join(lines)}</tbody></table>'
        '<p style="margin:0 0 24px;color:#292d32;'
        'font:14px/1.6 Arial,Helvetica,sans-serif;">'
        'Solicitamos verificar os lançamentos pendentes e '
        'providenciar a regularização.</p>'
        '<p style="margin:0;color:#292d32;'
        'font:14px/1.6 Arial,Helvetica,sans-serif;">'
        'Atenciosamente,<br>Controle de NFs Almoxarifado | SETTA</p>'
        '</div></body></html>'
    )


def gerar_previa_visual_ficticia(date_ref: datetime) -> str:
    """Prévia local do design, sem API, PIN, banco fiscal ou envio de e-mail."""
    from pandas.tseries.offsets import BDay

    data = pd.Timestamp(date_ref)
    rows = pd.DataFrame([
        {
            "NF": "EXEMPLO-001234",
            "FORNECEDOR": "FORNECEDOR MODELO A LTDA (FICTÍCIO)",
            "NATUREZA": "COMPRA DE MATERIA PRIMA",
            "DATA DE ENVIO": (data - BDay(3)).strftime("%d/%m/%Y %H:%M"),
            "DIAS DE ATRASO": 2,
            "NOME DO ARQUIVO": "NF_EXEMPLO_001234_FORNECEDOR_MODELO_A.pdf",
        },
        {
            "NF": "EXEMPLO-005678",
            "FORNECEDOR": "FORNECEDOR MODELO B LTDA (FICTÍCIO)",
            "NATUREZA": "COMPRA DE MATERIA PRIMA",
            "DATA DE ENVIO": (data - BDay(2)).strftime("%d/%m/%Y %H:%M"),
            "DIAS DE ATRASO": 1,
            "NOME DO ARQUIVO": "NF_EXEMPLO_005678_FORNECEDOR_MODELO_B.pdf",
        },
    ])
    return montar_email_html(rows, date_ref, homologacao=True)


def assunto_cobranca(date_ref: datetime) -> str:
    return "SETTA | Acompanhamento de lançamento de NFs vencidas — " + date_ref.strftime("%d/%m/%Y")
