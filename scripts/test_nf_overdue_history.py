"""Regressão dos cartões e da marca histórica de prazo contábil 24h."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pandas as pd

from nf_prazo_dashboard import (
    aplicar_historico_na_consulta,
    cartoes_prazo_html,
    indexar_historico_ocorrencias,
    indexar_dias_atraso_comprovados,
)

ROOT = Path(__file__).resolve().parent.parent
history = indexar_historico_ocorrencias([
    {"nf_id": "NF-1", "registrado_em": "2026-10-14T15:00:00Z"},
    {"nf_id": "NF-1", "registrado_em": "2026-10-14T15:00:00Z"},
    {"nf_id": "NF-3", "registrado_em": "2026-10-14T15:01:00Z"},
])
assert len(history) == 2
tz = ZoneInfo("America/Sao_Paulo")
rows = pd.DataFrame([
    {
        "id": "NF-1", "numero_nf": "101",
        "acompanhamento_lancamento": "LANÇAMENTO CONFIRMADO",
    },
    {
        "id": "NF-2", "numero_nf": "102",
        "acompanhamento_lancamento": "DENTRO DO PRAZO",
    },
    {
        "id": "NF-3", "numero_nf": "103",
        "acompanhamento_lancamento": "ATRASADO - COBRAR LANÇAMENTO",
    },
])
view = aplicar_historico_na_consulta(rows, history, tz)
assert view["historico_atraso_24h"].tolist() == ["SIM", "NÃO", "SIM"]
assert view.iloc[0]["primeiro_atraso_em"] == "14/10/2026 12:00"
assert view.iloc[1]["primeiro_atraso_em"] == ""
assert view.iloc[2]["primeiro_atraso_em"] == "14/10/2026 12:01"
assert rows.columns.tolist() == ["id", "numero_nf", "acompanhamento_lancamento"]
hist_data = [
    {"nf_id": "NF-1", "prazo_em": "2026-10-13T10:00:00Z",
     "verificado_em": "2026-10-14T10:55:00Z"},
    {"nf_id": "NF-3", "prazo_em": "2026-10-13T10:00:00Z",
     "verificado_em": "2026-10-14T10:55:00Z"},
]
dias = indexar_dias_atraso_comprovados(hist_data)
assert dias == {"NF-1": 2, "NF-3": 2}
hist_rows = rows.copy()
hist_rows["dias_atraso_lancamento"] = [0, 0, 5]
hist_result = aplicar_historico_na_consulta(hist_rows, history, tz, dias_comprovados=dias)
assert hist_result["dias_atraso_lancamento"].tolist() == [2, 0, 5]
assert hist_rows["dias_atraso_lancamento"].tolist() == [0, 0, 5]
unavailable = aplicar_historico_na_consulta(rows, {}, tz, False)
assert unavailable["historico_atraso_24h"].tolist() == ["INDISPONÍVEL"] * 3

html = cartoes_prazo_html(1, 2)
assert "NFs VENCIDAS AGORA" in html
assert "NFs QUE JÁ ATRASARAM" in html
assert "PENDÊNCIAS ATUAIS" in html
assert "HISTÓRICO PERMANENTE" in html
assert '<div class="nf-kpi-grid">' in html
assert html.count('class="kpi-card"') == 2
inner_html = cartoes_prazo_html(1, 2, apenas_cartoes=True)
assert inner_html.count('class="kpi-card"') == 2
assert '<div class="nf-kpi-grid">' not in inner_html

app = (ROOT / "streamlit_app.py").read_text("utf-8")
db = (ROOT / "db.py").read_text("utf-8")
sql = (ROOT / "supabase/migrations/20261014_nf_prazo_atrasos_historico.sql").read_text("utf-8")
assert "db.list_nf_prazo_atrasos()" in app
assert "indexar_dias_atraso_comprovados(" in app
assert 'select="nf_id,registrado_em,prazo_em,verificado_em"' in db
assert "aplicar_historico_na_consulta(" in app
assert "cartoes_prazo_html(" in app
# Layout: ambos os indicadores ficam com os seis existentes ANTES da
# faixa DOCUMENTOS FINALIZADOS, sem repetir os cartões abaixo da faixa.
dashboard = app[app.index('if page == "Dashboard":'):]
section_documents = dashboard.index('    section_band(\n        "02 · DOCUMENTOS"')
sla_position = dashboard.index('        + cartoes_prazo_html(')
assert sla_position < section_documents
assert dashboard.count('cartoes_prazo_html(') == 1
assert 'apenas_cartoes=True' in dashboard[:section_documents]
assert dashboard.count('nf-kpi-grid nf-kpi-sent') == 1
assert '.nf-kpi-grid.nf-kpi-sent{grid-template-columns:repeat(4,minmax(0,1fr))!important}' in app
assert 'launch_tracking_frame(_tracking_source)' in dashboard[:section_documents]
assert '.dt.tz_localize(TZ)' in dashboard[:section_documents]
assert 'finalized_records = aplicar_historico_na_consulta(' in dashboard[section_documents:]
assert '"historico_atraso_24h",' in app
assert '"primeiro_atraso_em",' in app
assert '"historico_atraso_24h": "JÁ TEVE ATRASO 24H"' in app
assert '"primeiro_atraso_em": "PRIMEIRO ATRASO EM"' in app
assert "if _overdue_count:\n            st.error(" not in app
assert "len(overdue)} NF(s) ultrapassaram 24 horas" not in app
assert "def list_nf_prazo_atrasos(" in db
assert "trigger trg_nf_primeiro_atraso" in sql
assert "on conflict (nf_id) do nothing" in sql
assert "nf_id uuid primary key" in sql
assert "lancado_em is not null" in sql
assert "lancamento_verificado_em <= v_prazo" in sql
assert "not public.nf_prazo_natureza_elegivel" in sql
assert "grant select on public.nf_prazo_atrasos to anon, authenticated" in sql
assert "IMPLANTACAO" in sql
print("NF_DASHBOARD_HISTORICO_ATRASOS_OK")
