"""Teste funcional do índice de CNPJ por código/loja do fornecedor TOTVS."""
import ast
from pathlib import Path
from types import SimpleNamespace
import re
import pandas as pd
from nf_processor import supplier_dataframe, normalize_text

source = Path("streamlit_app.py").read_text(encoding="utf-8")
tree = ast.parse(source)
nodes = [
    node for node in tree.body
    if isinstance(node, ast.FunctionDef)
    and node.name in {"_supplier_code_index_cached", "_supplier_cnpj_lookup"}
]
assert len(nodes) == 2
assert "@st.cache_data(show_spinner=False, max_entries=3)" in source
assert "by_code = _supplier_code_index_cached(st.session_state.suppliers)" in source

supplier_base = pd.DataFrame([
    {"codigo":"000123", "cnpj":"11111111000191", "nome_padrao":"ALFA COMPONENTES",
     "ativo":True, "aliases":"ALFA", "loja":"01"},
    {"codigo":"000456", "cnpj":"22222222000191", "nome_padrao":"BETA ELETRICA",
     "ativo":True, "aliases":"BETA", "loja":"01"},
    {"codigo":"000456", "cnpj":"33333333000191", "nome_padrao":"GAMA COMERCIO",
     "ativo":True, "aliases":"GAMA", "loja":"02"},
    {"codigo":"000789", "cnpj":"44444444000191", "nome_padrao":"INATIVO",
     "ativo":False},
])

def numbers(value):
    return re.sub(r"\D", "", str(value or ""))
def code(value):
    return numbers(value).lstrip("0") or ("0" if numbers(value) else "")
def similarity(a, b):
    return 100 if normalize_text(a) == normalize_text(b) else 0
st = SimpleNamespace(
    session_state=SimpleNamespace(suppliers=supplier_base),
    cache_data=lambda **kwargs: lambda func: func,
)
env = {
    "pd":pd, "st":st, "supplier_dataframe":supplier_dataframe,
    "_supplier_code_norm":code, "valid_cnpj":lambda v: len(numbers(v))==14,
    "digits_only":numbers, "normalize_text":normalize_text,
    "supplier_similarity":similarity,
}
module = ast.Module(body=nodes, type_ignores=[])
ast.fix_missing_locations(module)
exec(compile(module, "<supplier-index-test>", "exec"), env)
directory = env["_supplier_code_index_cached"](supplier_base)
assert set(directory) == {"123", "456"}, directory
assert len(directory["456"]) == 2
inputs = pd.DataFrame([
    {"fornecedor_codigo":"000123", "fornecedor":"ALFA COMPONENTES"},
    {"fornecedor_codigo":"000456", "fornecedor":"BETA ELETRICA"},
    {"fornecedor_codigo":"456", "fornecedor":"FORNECEDOR AMBIGUO"},
    {"fornecedor_codigo":"789", "fornecedor":"INATIVO"},
    {"fornecedor_codigo":"000123", "fornecedor":"ALFA COMPONENTES"},
])
cnpjs, unresolved=env["_supplier_cnpj_lookup"](inputs)
assert cnpjs.tolist() == [
    "11111111000191", "22222222000191", "", "", "11111111000191"
], cnpjs.tolist()
assert unresolved == 2
empty, missing = env["_supplier_cnpj_lookup"](inputs.iloc[0:0])
assert empty.empty and missing == 0
print("NFS_SUPPLIER_CODE_INDEX_OK")
