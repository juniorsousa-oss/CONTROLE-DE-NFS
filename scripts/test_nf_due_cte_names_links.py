"""Regressões: vencimento BR/ISO, CTe multi-NF, e visualização do lote."""
from __future__ import annotations

import ast
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace

import pandas as pd
from nf_processor import build_final_name, parse_operational_due_date
from cte_generator import cte_output_name
from nf_batch_display import add_cte_links_to_batch_view

assert parse_operational_due_date("02/11/2026") == date(2026, 11, 2)
assert parse_operational_due_date("02.11.2026") == date(2026, 11, 2)
assert parse_operational_due_date("2026-11-02") == date(2026, 11, 2)
assert parse_operational_due_date("2026-11-02T00:00:00") == date(2026, 11, 2)
assert parse_operational_due_date(pd.Timestamp("2026-11-02")) == date(2026, 11, 2)
assert parse_operational_due_date(datetime(2026, 11, 2, 8)) == date(2026, 11, 2)
assert parse_operational_due_date("11/02/2026") == date(2026, 2, 11)
assert parse_operational_due_date("2026-11-32") is None
assert parse_operational_due_date("02/11") is None

for due in ("02/11/2026", "2026-11-02", pd.Timestamp("2026-11-02")):
    assert build_final_name(parse_operational_due_date(due), "76515", "ARTECHE") == (
        "VENC. 02.11 - 76515 - ARTECHE.pdf"
    )

meta = SimpleNamespace(numero="8618029", emitente="ALFA TRANSPORTES EIRELI")
ctename = cte_output_name(meta, ["76516", "76515"], "ARTECHE EDC")
assert "76516 + 76515" in ctename, ctename
assert " +1" not in ctename, ctename
assert "76516 + 76516" not in cte_output_name(meta, ["76516", "76516"], "ARTECHE")
assert "SEM_NF" in cte_output_name(meta, [], "ARTECHE")

# O vínculo é válido por lote, não apenas pelo mesmo número da NF em outros lotes.
records = pd.DataFrame([
    {"lote_id": "L1", "tipo_documento": "NF-e", "numero_nf": "76515"},
    {"lote_id": "L1", "tipo_documento": "NF-e", "numero_nf": "76516"},
    {"lote_id": "L1", "tipo_documento": "CT-e", "numero_cte": "8618029",
     "nfs_vinculadas": "76516, 76515"},
    {"lote_id": "L2", "tipo_documento": "NF-e", "numero_nf": "76515"},
])
output = add_cte_links_to_batch_view(records)
assert output.iloc[0]["ctes_vinculados"] == "8618029"
assert output.iloc[1]["ctes_vinculados"] == "8618029"
assert output.iloc[2]["nfs_vinculadas"] == "76516, 76515"
assert output.iloc[3]["ctes_vinculados"] == ""

# Teste do recálculo real via AST para não iniciar a UI Streamlit no runner.
source = (Path(__file__).resolve().parents[1] / "streamlit_app.py").read_text(encoding="utf-8")
tree = ast.parse(source)
matches = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "recalc"]
assert len(matches) == 1
recalc_def = matches[0]
recalc_def.decorator_list = []
scope = {
    "pd": pd,
    "date": date,
    "datetime": datetime,
    "parse_operational_due_date": parse_operational_due_date,
    "build_final_name": build_final_name,
    "digits_only": lambda value: "".join(x for x in str(value or "") if x.isdigit()),
    "valid_cnpj": lambda value: len(value) == 14,
}
exec(compile(ast.Module(body=[recalc_def], type_ignores=[]), "<recalc>", "exec"), scope)
row = pd.DataFrame([{
    "numero_nf": "76515", "vencimento": "2026-11-02", "fornecedor_padrao": "ARTECHE EDC",
    "cnpj_fornecedor": "11222333000144", "natureza": "COMPRA DE MATERIA PRIMA",
    "empresa_sigla": "SEN", "pre_nota_recebedor": "RECEBIMENTO",
    "status": "APROVADO", "origem_dados": "PDF",
}])
result = scope["recalc"](row)
assert result.iloc[0]["vencimento"] == date(2026, 11, 2)
assert result.iloc[0]["nome_sugerido"] == "VENC. 02.11 - 76515 - ARTECHE EDC.pdf"
assert result.iloc[0]["status"] == "APROVADO"

# O manifest só pode receber a data normalizada, nunca uma string bruta.
assert '"vencimento": parsed_due.isoformat()' in source
assert "vencimento divergente do nome do arquivo" in source
print("NF_CTE_DUE_DATE_LINKS_OK")
