"""Teste funcional do índice MRP × pré-notas: resultado igual e menos varreduras.

Executa a função real isolada por AST sem acessar Supabase ou Streamlit Cloud.
"""
import ast
from pathlib import Path

import pandas as pd

source = Path("streamlit_app.py").read_text(encoding="utf-8")
tree = ast.parse(source)
matches = [
    node for node in tree.body
    if isinstance(node, ast.FunctionDef)
    and node.name == "_refresh_missing_mrp_analysis"
]
assert len(matches) == 1
source_func = ast.get_source_segment(source, matches[0])
assert "pre_index = {}" in source_func
assert "match_mrp_to_pre_note(" in source_func

class State(dict):
    def __getattr__(self, key):
        return self[key]
    def __setattr__(self, key, value):
        self[key] = value

state = State()
state.pre_notes = pd.DataFrame([
    {
        "numero_nf": f"{number:06d}",
        "fornecedor": "FORNECEDOR A",
        "cnpj": "11222333000181",
    }
    for number in range(1, 301)
])
state.mrp_priority_summary = pd.DataFrame([
    {
        "numero_nf": str(number),
        "fornecedor": "FORNECEDOR A",
        "fornecedor_codigo": "000123",
        "cnpj": "11222333000181",
    }
    for number in range(1, 331)
])
state.mrp_impact_detail = pd.DataFrame()
state.excluded_flow_keys = {"4|FORNECEDOR A"}

def number(value):
    digits = "".join(c for c in str(value or "") if c.isdigit())
    return digits.lstrip("0") or ("0" if digits else "")
def supplier_code(value):
    return number(value)
def doc_digits(value):
    return "".join(c for c in str(value or "") if c.isdigit())

scanned = [0]
def mock_match(mrp_row, candidates):
    scanned[0] += len(candidates)
    exact = candidates["numero_nf"].map(number).eq(number(mrp_row["numero_nf"]))
    is_found = bool(exact.any())
    return {
        "matched": is_found,
        "situacao": "OK" if is_found else "AUSENTE NAS PRÉ-NOTAS",
        "score_fornecedor": 100 if is_found else 0,
    }
def lookup(frame):
    return pd.Series([""] * len(frame), index=frame.index), len(frame)

scope = {
    "pd": pd,
    "st": type("FakeStreamlit", (), {"session_state": state})(),
    "normalized_nf": number,
    "_supplier_code_norm": supplier_code,
    "digits_only": doc_digits,
    "valid_cnpj": lambda v: len(doc_digits(v)) == 14,
    "_supplier_cnpj_lookup": lookup,
    "flow_nf_key": lambda r: f"{number(r.get('numero_nf'))}|{r.get('fornecedor', '')}",
    "match_mrp_to_pre_note": mock_match,
}
code = ast.Module(body=matches, type_ignores=[])
ast.fix_missing_locations(code)
exec(compile(code, "<mrp-index-test>", "exec"), scope)

actual = scope["_refresh_missing_mrp_analysis"]()
# Apenas as NFs 301..330 estão ausentes; NF 4 foi explicitamente excluída.
assert len(actual) == 30, actual.to_dict("records")
assert list(actual["numero_nf"]) == [str(x) for x in range(301, 331)]
assert scanned[0] <= 330, scanned
assert state.base_analysis_missing_mrp.equals(actual)

# Comportamento de referência anterior (cada NF examinava todas as pré-notas).
old_scanned = 0
old_missing = []
for _, mrp_row in state.mrp_priority_summary.iterrows():
    if scope["flow_nf_key"](mrp_row) in state.excluded_flow_keys:
        continue
    candidates = state.pre_notes
    old_scanned += len(candidates)
    found = candidates["numero_nf"].map(number).eq(number(mrp_row["numero_nf"])).any()
    if not found:
        old_missing.append(number(mrp_row["numero_nf"]))
assert old_missing == [number(x) for x in actual["numero_nf"]]
assert old_scanned >= scanned[0] * 100, (old_scanned, scanned[0])
print(f"NFS_MRP_INDEX_OK: {scanned[0]} candidatos vs {old_scanned} no algoritmo anterior")
