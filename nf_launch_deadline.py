"""Prazo de lançamento NF-e: 24 horas nos dias úteis de Patos de Minas/MG.

Exclui sábados, domingos, feriados nacionais e municipais de Patos de Minas.
A janela operacional (seg-qui 07-18h; sex 07-16h) define apenas o início.
Nos dias úteis, a contagem continua durante a noite.
Pontos facultativos não são feriados automaticamente.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
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
    """NF-e de matéria-prima ou EPI GERA ESTOQUE, conforme regra SETTA."""
    tipo = _normalize(tipo_documento)
    natureza_normal = _normalize(natureza)
    return (
        tipo in {"NF E", "NFE", "NOTA FISCAL ELETRONICA"}
        and (
            "COMPRA DE MATERIA PRIMA" in natureza_normal
            or natureza_normal == "MATERIA PRIMA"
            or "EPI GERA ESTOQUE" in natureza_normal
        )
    )


def _localize(when: datetime) -> datetime:
    # Timestamps do banco podem vir com tz UTC ou como horário local já
    # convertido no Dashboard; não transformar um horário local em UTC.
    if when.tzinfo is None:
        return when.replace(tzinfo=LOCAL_TZ)
    return when.astimezone(LOCAL_TZ)


_FERIADOS_FIXOS = {
    (1, 1), (4, 21), (5, 1), (9, 7), (10, 12),
    (11, 2), (11, 15), (11, 20), (12, 25),
    (5, 24), (6, 13), (8, 15),
}


def _data_pascoa(ano: int) -> date:
    """Algoritmo gregoriano, alinhado ao calendário de feriados do banco."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    base = h + l - 7 * m + 114
    mes, resto = divmod(base, 31)
    return date(ano, mes, resto + 1)


def eh_dia_util(valor: date | datetime) -> bool:
    """Dias úteis SETTA (nacionais + Patos de Minas, sem pontos facultativos)."""
    dia = valor.date() if isinstance(valor, datetime) else valor
    if not isinstance(dia, date):
        raise TypeError("É necessária uma data válida.")
    if dia.weekday() >= 5 or (dia.month, dia.day) in _FERIADOS_FIXOS:
        return False
    pascoa = _data_pascoa(dia.year)
    return dia not in {pascoa - timedelta(days=2), pascoa + timedelta(days=60)}


def inicio_valido_envio(enviado_em: datetime) -> datetime:
    """Move somente envios fora da janela para 07 h do próximo dia útil."""
    if not isinstance(enviado_em, datetime):
        raise TypeError("É necessária uma data/hora de envio válida.")
    atual = _localize(enviado_em)
    while True:
        dia = atual.weekday()  # seg=0, sex=4, sáb=5, dom=6
        if not eh_dia_util(atual.date()):
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
    """Acumula 24 horas sem contar finais de semana nem feriados."""
    atual = inicio_valido_envio(enviado_em)
    restante = timedelta(hours=24)
    while restante > timedelta(0):
        if not eh_dia_util(atual.date()):
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
    while not eh_dia_util(atual.date()):
        atual = (atual + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0,
        )
    return atual


def dias_atraso_uteis(vencimento: datetime, referencia: datetime | None = None) -> int:
    """Dias de atraso após o prazo, sem finais de semana ou feriados.

    Frações positivas são arredondadas para cima. Nos dias úteis o relógio
    continua à noite, em alinhamento com a regra do banco.
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
        if eh_dia_util(cursor.date()):
            segundos += (fim - cursor).total_seconds()
        cursor = fim
    return int(ceil(segundos / 86400)) if segundos > 0 else 0
