"""Prazo de lançamento NF-e: 24 h de relógio, excluindo sábados e domingos.

A janela operacional (seg-qui 07–18 h; sex 07–16 h) determina apenas
o INÍCIO válido. Durante os dias úteis o relógio não pausa à noite.
Feriados não estão excluídos; esta regra considera somente o fim de semana.
"""

from __future__ import annotations

from datetime import datetime, time, timedelta
from math import ceil
from zoneinfo import ZoneInfo
import re
import unicodedata

LOCAL_TZ = ZoneInfo("America/Sao_Paulo")
INICIO = time(7, 0)
FECHAMENTO_SEMANA = time(18, 0)
FECHAMENTO_SEXTA = time(16, 0)


def _normalize(value: object) -> str:
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return " ".join(re.findall(r"[A-Z0-9]+", text.upper()))


def acompanha_lancamento(tipo_documento: object, natureza: object) -> bool:
    """Somente NF-e com natureza de COMPRA DE MATERIA PRIMA."""
    tipo = _normalize(tipo_documento)
    natureza_normal = _normalize(natureza)
    return (
        tipo in {"NF E", "NFE", "NOTA FISCAL ELETRONICA"}
        and "COMPRA DE MATERIA PRIMA" in natureza_normal
    )


def _localize(when: datetime) -> datetime:
    # Timestamps do banco podem vir com tz UTC ou como horário local já
    # convertido no Dashboard; não transformar um horário local em UTC.
    if when.tzinfo is None:
        return when.replace(tzinfo=LOCAL_TZ)
    return when.astimezone(LOCAL_TZ)


def inicio_valido_envio(enviado_em: datetime) -> datetime:
    """Move somente envios fora da janela para 07 h do próximo dia útil."""
    if not isinstance(enviado_em, datetime):
        raise TypeError("É necessária uma data/hora de envio válida.")
    atual = _localize(enviado_em)
    while True:
        dia = atual.weekday()  # seg=0, sex=4, sáb=5, dom=6
        if dia >= 5:
            atual = (atual + timedelta(days=1)).replace(
                hour=7, minute=0, second=0, microsecond=0,
            )
            continue
        if atual.time() < INICIO:
            return atual.replace(hour=7, minute=0, second=0, microsecond=0)
        limite = FECHAMENTO_SEXTA if dia == 4 else FECHAMENTO_SEMANA
        if atual.time() <= limite:
            return atual
        atual = (atual + timedelta(days=1)).replace(
            hour=7, minute=0, second=0, microsecond=0,
        )


def prazo_lancamento(enviado_em: datetime) -> datetime:
    """Acumula 24 horas sem contar qualquer segundo de sábado/domingo."""
    atual = inicio_valido_envio(enviado_em)
    restante = timedelta(hours=24)
    while restante > timedelta(0):
        if atual.weekday() >= 5:
            # Volta a contar à meia-noite de segunda. O horário de abertura
            # limita apenas novos inícios, não a continuação de prazos.
            atual = (atual + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0,
            )
            continue
        proxima_meia_noite = (atual + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
        disponivel = proxima_meia_noite - atual
        if restante < disponivel:
            return atual + restante
        atual = proxima_meia_noite
        restante -= disponivel
    # Se terminou exatamente no começo do sábado, vence segunda 00 h.
    while atual.weekday() >= 5:
        atual = (atual + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
    return atual


def dias_atraso_uteis(vencimento: datetime, referencia: datetime | None = None) -> int:
    """Dias equivalentes de 24h após o vencimento, sem sábados e domingos.

    Contagem iniciada somente após as 24h da regra de lançamento.
    Frações positivas arredondam para cima (primeiro dia = 1).
    O relógio continua à noite de seg-sex, assim como o prazo existente.
    Feriados não são excluídos, pois a regra institucional atual não os trata.
    """
    if not isinstance(vencimento, datetime):
        return 0
    atual = _localize(referencia or datetime.now(LOCAL_TZ))
    inicio = _localize(vencimento)
    if atual <= inicio:
        return 0
    segundos = 0.0
    cursor = inicio
    while cursor < atual:
        proxima = (cursor + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        fim = min(proxima, atual)
        if cursor.weekday() < 5:
            segundos += (fim - cursor).total_seconds()
        cursor = fim
    return int(ceil(segundos / 86400)) if segundos > 0 else 0
