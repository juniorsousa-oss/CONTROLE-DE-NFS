"""Regression for supplier IDs and dashboard layout; no production data changed."""
import ast
from pathlib import Path
import re
from types import SimpleNamespace

import pandas as pd
from nf_processor import normalize_text, supplier_dataframe
from rapidfuzz import fuzz

app=Path("streamlit_app.py").read_text(encoding="utf-8")
shell=Path("setta_shell.py").read_text(encoding="utf-8")
tree=ast.parse(app)
nodes=[
    node for node in tree.body if isinstance(node,ast.FunctionDef)
    and node.name in {
        "_supplier_code_index_cached", "_supplier_cnpj_lookup",
        "match_mrp_to_pre_note",
    }
]
assert len(nodes)==3

class FakeSt:
    def __init__(self,data):
        self.session_state=SimpleNamespace(suppliers=data)
    def cache_data(self,**kwargs):
        return lambda method:method

def digits(v):
    return re.sub(r"\D","",str(v or ""))
def code(v):
    return digits(v).lstrip("0") or ("0" if digits(v) else "")
def similarity(a,b):
    a,b=normalize_text(a),normalize_text(b)
    if not a or not b:return 0
    if a==b:return 100
    return int(round(fuzz.token_set_ratio(a,b)*.55+
                     fuzz.token_sort_ratio(a,b)*.45))
suppliers=pd.DataFrame([
    {"codigo":"014145","cnpj":"11111111000191",
     "nome_padrao":"M & M FRANCO REFRIGERACAO", "ativo":True},
    {"codigo":"000040","cnpj":"22222222000191",
     "nome_padrao":"COFERMETA SA", "ativo":True},
    {"codigo":"000040","cnpj":"33333333000191",
     "nome_padrao":"COFERMETA S.A.", "ativo":True},
    {"codigo":"000166","cnpj":"44444444000191",
     "nome_padrao":"COPA ENERGIA SA","ativo":True},
])
ns={
    "pd":pd, "st":FakeSt(suppliers), "supplier_dataframe":supplier_dataframe,
    "_supplier_code_norm":code, "digits_only":digits,
    "valid_cnpj":lambda v:len(digits(v))==14,
    "supplier_similarity":similarity, "normalize_text":normalize_text,
}
# Match function is present for source checks, but needs no production input.
exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),
             "<supplier-safety-test>","exec"),ns)
lookup=ns["_supplier_cnpj_lookup"]
entries=pd.DataFrame([
    {"fornecedor_codigo":"014145","fornecedor":"METALURGICA J.S.A. LTDA"},
    {"fornecedor_codigo":"000040","fornecedor":"COFERMETA SA"},
    {"fornecedor_codigo":"000166","fornecedor":"COPA ENERGIA SA"},
])
out, unresolved=lookup(entries)
assert out.iloc[0] == "", "Incorrect CNPJ assigned merely by shared code"
assert out.iloc[1] == "", "Multiple possible company IDs must remain unresolved"
assert out.iloc[2] == "44444444000191",out.tolist()
assert unresolved==2

assert '"score_fornecedor": None' in app
assert 'view["score_fornecedor"] = pd.to_numeric(' in app
assert '"ADERÊNCIA À PRÉ-NOTA"' in app
assert '"CADASTRO FORNECEDOR"' in app
assert '"CNPJ PENDENTE / VALIDAR LOJA"' in app
# The dashboard must not create st.columns(4) on sidebar toggles.
dash=app[app.index("    kpis = ["):app.index("    if not db.configured():",app.index("    kpis = ["))]
assert "st.columns(4)" not in dash and "st.columns(2)" not in dash
assert "nf-kpi-grid" in dash
assert ".nf-kpi-grid{display:grid" in app
assert ".nf-kpi-grid.nf-kpi-sent" in app
assert "grid-template-columns:repeat(4,minmax(0,1fr))" in app
assert "gap:7px!important;row-gap:7px!important" in shell
assert "min-height:24px!important;margin:10px 0 5px" in shell
print("NFS_SUPPLIER_CNPJ_SIDEBAR_UI_OK")
