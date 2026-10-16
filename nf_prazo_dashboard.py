"""Indicadores e auditoria visual de NF-e com prazo de lançamento vencido.

A ocorrência é persistida pelo trigger trg_nf_primeiro_atraso no Supabase,
inclusive quando a NF posteriormente é confirmada como lançada.
"""
from __future__ import annotations

from html import escape

import pandas as pd

from nf_launch_deadline import dias_atraso_uteis


def indexar_historico_ocorrencias(rows: list[dict]) -> dict[str, str]:
    """Identifica cada NF pela chave estável do registro, sem contar repetição."""
    return {
        str(row["nf_id"]): str(row.get("registrado_em") or "")
        for row in rows if row.get("nf_id")
    }


def indexar_dias_atraso_comprovados(rows: list[dict]) -> dict[str, int]:
    """Mínimo comprovado entre o vencimento e a primeira conferência vencida.

    A coluna histórica não estima uma data de lançamento retroativa; depois
    da regularização, o cálculo usa a evidência persistida no banco.
    """
    calculados = {}
    for row in rows:
        nf_id = str(row.get("nf_id") or "").strip()
        prazo = pd.to_datetime(row.get("prazo_em"), errors="coerce", utc=True)
        conferido = pd.to_datetime(row.get("verificado_em"), errors="coerce", utc=True)
        if nf_id and pd.notna(prazo) and pd.notna(conferido) and conferido > prazo:
            dias = dias_atraso_uteis(prazo.to_pydatetime(), conferido.to_pydatetime())
            if dias:
                calculados[nf_id] = dias
    return calculados


def aplicar_historico_na_consulta(
    frame: pd.DataFrame,
    historico: dict[str, str],
    timezone: object,
    disponivel: bool = True,
    dias_comprovados: dict[str, int] | None = None,
) -> pd.DataFrame:
    """Adiciona marca de auditoria e data do primeiro atraso ao relatório."""
    view = frame.copy()
    ids = view.get("id", pd.Series("", index=view.index)).fillna("").astype(str)
    if not disponivel:
        view["historico_atraso_24h"] = "INDISPONÍVEL"
        view["primeiro_atraso_em"] = ""
        return view
    view["historico_atraso_24h"] = ids.map(
        lambda record_id: "SIM" if record_id in historico else "NÃO"
    )
    dts = pd.to_datetime(ids.map(historico), errors="coerce", utc=True)
    view["primeiro_atraso_em"] = (
        dts.dt.tz_convert(timezone).dt.strftime("%d/%m/%Y %H:%M").fillna("")
    )
    if "dias_atraso_lancamento" in view.columns and dias_comprovados is not None:
        # NFs concluídas NÃO podem mostrar 0 se o atraso foi comprovado.
        # Documentos ainda abertos continuam com o cálculo atual.
        status = view.get(
            "acompanhamento_lancamento",
            pd.Series("", index=view.index),
        ).fillna("")
        encerradas_com_atraso = (
            status.eq("LANÇAMENTO CONFIRMADO")
            & ids.isin(dias_comprovados)
        )
        if encerradas_com_atraso.any():
            view.loc[encerradas_com_atraso, "dias_atraso_lancamento"] = (
                ids.loc[encerradas_com_atraso].map(dias_comprovados)
            )
    return view


def cartoes_prazo_html(
    atual: int, historico: int | str, *, apenas_cartoes: bool = False,
) -> str:
    """Mesmo componente visual de cartões já utilizado no Dashboard SETTA."""
    cards = (
        ("NFs VENCIDAS AGORA", int(atual), "PENDÊNCIAS ATUAIS", "#b45309", "#fef3c7"),
        ("NFs QUE JÁ ATRASARAM", historico, "HISTÓRICO PERMANENTE", "#475569", "#e2e8f0"),
    )
    pieces = []
    for label, value, info, accent, soft in cards:
        pieces.append(
            f'<div class="kpi-card" style="--accent:{accent};--accent-soft:{soft}">'
            f'<div class="kpi-header"><span class="kpi-dot"></span>'
            f'<span class="kpi-label">{escape(label)}</span></div>'
            f'<div class="kpi-value">{escape(str(value))}</div>'
            f'<div class="kpi-delta">{escape(info)}</div></div>'
        )
    conteudo = "".join(pieces)
    return conteudo if apenas_cartoes else '<div class="nf-kpi-grid">' + conteudo + '</div>'
