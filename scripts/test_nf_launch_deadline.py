"""Regressão do prazo contábil: 24 h sem sábados/domingos.

Janela 07–18 h seg-qui, 07–16 h sexta: usada apenas para
ajustar envios FORA do expediente. Não pausa à noite.
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from nf_launch_deadline import (
    acompanha_lancamento,
    inicio_valido_envio,
    prazo_lancamento,
    dias_atraso_uteis,
)

TZ = ZoneInfo("America/Sao_Paulo")


def d(weekday: int, hour: int, minute: int = 0) -> datetime:
    # 2026-10-12 é segunda-feira.
    return datetime(2026, 10, 12 + weekday, hour, minute)


cases = [
    (d(0, 6), d(0, 7), d(1, 7)),          # Seg cedo
    (d(0, 10), d(0, 10), d(1, 10)),       # Seg no horário
    (d(0, 18), d(0, 18), d(1, 18)),       # Seg às 18 inclusive
    (d(0, 19), d(1, 7), d(2, 7)),         # Seg após 18
    (d(3, 17), d(3, 17), d(4, 17)),       # Qui 17 => sex 17
    (d(3, 19), d(4, 7), d(7, 7)),         # Qui após 18 => sex 07 => seg 07
    (d(4, 6), d(4, 7), d(7, 7)),          # Sex antes das 07
    (d(4, 15), d(4, 15), d(7, 15)),       # Sex 15 => seg 15
    (d(4, 16), d(4, 16), d(7, 16)),       # Sex 16 inclusive
    (d(4, 17), d(7, 7), d(8, 7)),         # Sex após as 16
    (d(5, 10), d(7, 7), d(8, 7)),         # Sábado
    (d(6, 14), d(7, 7), d(8, 7)),         # Domingo
    (d(7, 7), d(7, 7), d(8, 7)),          # Segunda 07
]
for enviado, inicio, prazo in cases:
    actual_start = inicio_valido_envio(enviado)
    actual_end = prazo_lancamento(enviado)
    assert actual_start.replace(tzinfo=None) == inicio, (enviado, actual_start, inicio)
    assert actual_end.replace(tzinfo=None) == prazo, (enviado, actual_end, prazo)
    assert actual_end.weekday() <= 4
    assert actual_end >= actual_start

# Não congelar o contador à noite: quinta 17 -> sexta 17, ainda que
# sexta já esteja fora da janela permitida para INICIAR novos envios.
assert prazo_lancamento(d(3, 17)).replace(tzinfo=None) == d(4, 17)

# Horário UTC do banco precisa produzir o mesmo vencimento no Brasil.
fri_local = d(4, 15).replace(tzinfo=TZ)
fri_utc = fri_local.astimezone(ZoneInfo("UTC"))
assert prazo_lancamento(fri_utc) == prazo_lancamento(fri_local)

# Somente NF-e matéria-prima e EPI com geração de estoque após envio.
for name in ("COMPRA DE MATERIA PRIMA", "COMPRA DE MATÉRIA-PRIMA",
             "compra de materia prima", "EPI GERA ESTOQUE", "EPI GÉRA ESTOQUE"):
    assert acompanha_lancamento("NF-e", name)
for typ, nature in [
    ("CT-e", "COMPRA DE MATERIA PRIMA"),
    ("NF-e", "SIMPLES REMESSA"),
    ("NF-e", "INDUSTRIALIZACAO POR ENCOMENDA"),
    ("NF-e", "CONSERTO MERCADORIA - ENTRADA"),
    ("NF-e", ""),
]:
    assert not acompanha_lancamento(typ, nature), (typ, nature)

sql_epi = (Path(__file__).resolve().parents[1] /
    "supabase/migrations/20261016_nf_epi_prazo_24h.sql").read_text("utf-8")
assert "EPI GERA ESTOQUE" in sql_epi
assert "COMPRA DE MATERIA PRIMA" in sql_epi
assert "on conflict" not in sql_epi
# Teste da função de acompanhamento efetivamente exibida na tela.
source = (Path(__file__).resolve().parents[1] / "streamlit_app.py").read_text("utf-8")
tree = ast.parse(source)
functions = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "launch_tracking_frame"]
assert len(functions) == 1
target = functions[0]
target.decorator_list = []
namespace = {
    "pd": pd, "TZ": TZ,
    "acompanha_lancamento": acompanha_lancamento,
    "inicio_valido_envio": inicio_valido_envio,
    "prazo_lancamento": prazo_lancamento,
    "dias_atraso_uteis": dias_atraso_uteis,
    "now_local": lambda: d(7, 17).replace(tzinfo=TZ),
}
exec(compile(ast.Module(body=[target],type_ignores=[]), "nf_tracking_test", "exec"), namespace)
fn = namespace["launch_tracking_frame"]
records = pd.DataFrame([
    {"tipo_documento":"NF-e","natureza":"COMPRA DE MATERIA PRIMA",
     "numero_nf":"001","enviado_em":fri_utc.isoformat(),
     "lancado_em":None, "lancamento_verificado_em":None},
    {"tipo_documento":"NF-e","natureza":"SIMPLES REMESSA",
     "numero_nf":"002","enviado_em":fri_utc.isoformat()},
    {"tipo_documento":"CT-e","natureza":"COMPRA DE MATERIA PRIMA",
     "numero_nf":"003","enviado_em":fri_utc.isoformat()},
    {"tipo_documento":"NF-e","natureza":"COMPRA DE MATERIA PRIMA",
     "numero_nf":"004","enviado_em":None},
])
view = fn(records)
assert view["numero_nf"].tolist()==["001"], view
assert str(view.iloc[0]["inicio_prazo_lancamento"])=="2026-10-16 15:00:00"
assert str(view.iloc[0]["prazo_lancamento"])=="2026-10-19 15:00:00"
assert view.iloc[0]["situacao_lancamento"]=="AGUARDANDO NOVO RELATÓRIO", view
assert view.iloc[0]["dias_atraso_lancamento"] >= 1
# 24h inteiras e frações, inclusive noite; sábado/domingo não contam.
assert dias_atraso_uteis(d(4, 15), d(4, 15)) == 0
assert dias_atraso_uteis(d(4, 15), d(4, 15, 1)) == 1
assert dias_atraso_uteis(d(4, 15), d(5, 18)) == 1
assert dias_atraso_uteis(d(4, 15), d(6, 18)) == 1
assert dias_atraso_uteis(d(4, 15), d(7, 14)) == 1
assert dias_atraso_uteis(d(4, 15), d(7, 16)) == 2
assert dias_atraso_uteis(d(3, 17), d(4, 17)) == 1
assert dias_atraso_uteis(d(3, 17), d(4, 17, 1)) == 2

# As duas interfaces devem utilizar a mesma regra: nunca apenas sent + 24h.
assert "frame[\"_sent\"] + pd.Timedelta(hours=24)" not in source
assert "_sent + pd.Timedelta(hours=24)" not in source
assert "finalized_records[\"inicio_prazo_lancamento\"] = _start" in source
assert "if not bool(_eligible_final.loc[idx]):" in source
print("NF_LANCAMENTO_PRAZO_SEM_FIM_DE_SEMANA_OK")
