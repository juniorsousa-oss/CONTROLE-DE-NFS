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


def montar_email_html(rows: pd.DataFrame, date_ref: datetime) -> str:
    """Prévia com identidade visual equivalente ao e-mail gerado pela Edge Function."""
    if rows is None or rows.empty:
        raise ValueError("Nenhuma NF vencida apta à cobrança.")
    if list(rows.columns) != [label for _, label in COLUNAS_EMAIL]:
        raise ValueError("Colunas inesperadas na prévia da cobrança.")

    headers = "".join(
        '<th bgcolor="#263f60" scope="col" style="padding:12px 10px;'
        'border-bottom:2px solid #5a7798;background:#263f60;color:#ffffff;'
        'font:700 11px Arial,sans-serif;text-align:left;">'
        f'{escape(col)}</th>' for col in rows.columns
    )
    lines = []
    for i, (_, record) in enumerate(rows.iterrows()):
        bg = "#1c314e" if i % 2 else "#152943"
        values = record.tolist()
        cells = []
        for col, value in zip(rows.columns, values):
            content = escape(_texto(value))
            if col == "NF":
                content = f'<strong style="color:#ffffff;">{content}</strong>'
            if col == "DIAS DE ATRASO":
                content = ('<span style="display:inline-block;padding:4px 9px;'
                           'border-radius:10px;background:#8c3d1a;color:#ffffff;'
                           f'font-weight:700;">{content}</span>')
            cells.append(
                f'<td bgcolor="{bg}" style="padding:13px 10px;background:{bg};'
                'border-bottom:1px solid #425875;color:#ffffff;'
                'font:12px/1.55 Arial,sans-serif;vertical-align:top;'
                f'overflow-wrap:anywhere;word-break:break-word;">{content}</td>'
            )
        lines.append(f'<tr bgcolor="{bg}">{"".join(cells)}</tr>')

    total = len(rows)
    referencia = escape(date_ref.strftime("%d/%m/%Y"))
    return (
        '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta name="color-scheme" content="dark">'
        '<style>@media screen and (max-width:640px){'
        '.shell-pad{padding:10px!important}.pad-main{padding:20px 14px!important}'
        '.head-pad{padding:22px 16px!important}'
        '.email-title{font-size:21px!important}'
        '.records-table th,.records-table td{padding:8px 6px!important;'
        'font-size:11px!important}}</style></head>'
        '<body bgcolor="#0d192b" style="margin:0;padding:0;background:#0d192b;'
        'color:#ffffff;font-family:Arial,Helvetica,sans-serif;">'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0"'
        ' bgcolor="#0d192b" style="width:100%;background:#0d192b;'
        'border-collapse:collapse;"><tr><td class="shell-pad" align="center"'
        ' style="padding:26px 18px;">'
        '<table role="presentation" width="920" cellpadding="0" cellspacing="0"'
        ' bgcolor="#162a45" style="width:100%;max-width:920px;'
        'border-collapse:collapse;border:1px solid #3a5171;">'
        '<tr><td class="head-pad" bgcolor="#1c3553" style="padding:27px 32px 25px;'
        'border-top:5px solid #e54545;background:#1c3553;color:#ffffff;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0">'
        '<tr><td style="color:#ffffff;font:800 22px Arial,sans-serif;'
        'letter-spacing:1.5px;">SETTA</td>'
        '<td align="right" style="color:#ffffff;font:700 11px Arial,sans-serif;">'
        'ALMOXARIFADO · CONTROLE DE NFs</td></tr></table>'
        '<h1 class="email-title" style="margin:23px 0 8px;color:#ffffff;'
        'font:700 24px/1.3 Arial,sans-serif;">'
        'Acompanhamento de lançamento de NFs</h1>'
        '<p style="margin:0;color:#dce8f6;font:13px/1.5 Arial,sans-serif;">'
        f'Referência: {referencia}</p></td></tr>'
        '<tr><td class="pad-main" bgcolor="#162a45"'
        ' style="padding:28px 32px 30px;background:#162a45;color:#ffffff;">'
        '<p style="margin:0 0 15px;color:#ffffff;'
        'font:14px/1.6 Arial,sans-serif;">Prezados,</p>'
        '<p style="margin:0 0 23px;color:#ffffff;font:14px/1.75 Arial,sans-serif;">'
        f'Segue a relação de <strong>{total} NF(s)</strong> de compra de '
        'matéria-prima com prazo de lançamento vencido, '
        'sem confirmação de lançamento.</p>'
        '<table role="presentation" width="100%" cellspacing="0" cellpadding="0"'
        ' style="margin:0 0 22px;border-collapse:collapse;">'
        '<tr><td bgcolor="#233d5c" style="padding:15px 19px;'
        'border-left:4px solid #e54545;background:#233d5c;color:#ffffff;">'
        '<span style="color:#ffffff;font:700 12px Arial,sans-serif;">'
        'NOTAS FISCAIS EM ACOMPANHAMENTO&nbsp;&nbsp;</span>'
        f'<span style="color:#ffffff;font:700 22px Arial,sans-serif;">{total}</span>'
        '</td></tr></table>'
        '<table class="records-table" role="table" width="100%" cellpadding="0"'
        ' cellspacing="0" style="width:100%;border-collapse:collapse;'
        'border:1px solid #425875;">'
        f'<thead><tr>{headers}</tr></thead><tbody>{"".join(lines)}</tbody></table>'
        '<p style="margin:26px 0 24px;color:#ffffff;font:14px/1.7 Arial,sans-serif;">'
        'Solicitamos verificar os lançamentos pendentes e providenciar '
        'a regularização.</p>'
        '<p style="margin:0;color:#ffffff;font:14px/1.7 Arial,sans-serif;">'
        'Atenciosamente,<br><strong style="color:#ffffff;">'
        'Controle de NFs Almoxarifado | SETTA</strong></p>'
        '</td></tr><tr><td bgcolor="#0f2035" style="padding:16px 32px;'
        'background:#0f2035;border-top:1px solid #3a5171;'
        'color:#ffffff;font:12px/1.5 Arial,sans-serif;">'
        'SETTA · Acompanhamento operacional de notas fiscais'
        '</td></tr></table></td></tr></table></body></html>'
    )


def assunto_cobranca(date_ref: datetime) -> str:
    return "SETTA | Acompanhamento de lançamento de NFs vencidas — " + date_ref.strftime("%d/%m/%Y")
