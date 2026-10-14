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
unavailable = aplicar_historico_na_consulta(rows, {}, tz, False)
assert unavailable["historico_atraso_24h"].tolist() == ["INDISPONÍVEL"] * 3

html = cartoes_prazo_html(1, 2)
assert "NFs VENCIDAS AGORA" in html
assert "NFs QUE JÁ ATRASARAM" in html
assert "PENDÊNCIAS ATUAIS" in html
assert "HISTÓRICO PERMANENTE" in html
assert '<div class="nf-kpi-grid">' in html
assert html.count('class="kpi-card"') == 2

app = (ROOT / "streamlit_app.py").read_text("utf-8")
db = (ROOT / "db.py").read_text("utf-8")
sql = (ROOT / "supabase/migrations/20261014_nf_prazo_atrasos_historico.sql").read_text("utf-8")
assert "db.list_nf_prazo_atrasos()" in app
assert "aplicar_historico_na_consulta(" in app
assert "cartoes_prazo_html(" in app
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
