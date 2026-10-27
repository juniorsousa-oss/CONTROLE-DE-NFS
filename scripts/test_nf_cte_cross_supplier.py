"""Regressão de vínculo CT-e pelo CNPJ do emitente, nunca número isolado."""
import ast
import re
from pathlib import Path
import pandas as pd

source = Path("streamlit_app.py").read_text(encoding="utf-8")
tree = ast.parse(source)
node = next(
    n for n in tree.body
    if isinstance(n, ast.FunctionDef) and n.name == "_analysis_rows_for_nfe_keys"
)
namespace = {
    "pd": pd,
    "digits_only": lambda val: re.sub(r"\D", "", str(val or "")),
    "normalized_nf": lambda val: (re.sub(r"\D", "", str(val or "")).lstrip("0") or "0"),
}
exec(compile(ast.fix_missing_locations(ast.Module(body=[node], type_ignores=[])),
             "<cte-issuer-link>", "exec"), namespace)
find = namespace["_analysis_rows_for_nfe_keys"]

def key(n, cnpj):
    return "31" + "2610" + cnpj + "55" + "001" + n.zfill(9) + "1" + "12345678" + "0"

issuer_a, issuer_b = "12345678000195", "98765432000190"
k_a, k_b = key("101", issuer_a), key("101", issuer_b)
source_pdf = pd.DataFrame([{
    "file_id": "nf-a", "numero_nf": "101", "cnpj_fornecedor": issuer_a,
    "chave_nfe": "",
}])
assert [r["file_id"] for r in find(source_pdf, [k_a])] == ["nf-a"]
assert find(source_pdf, [k_b]) == [], "Mesmo número, outro CNPJ não pode vincular!"
assert find(pd.concat([source_pdf, source_pdf], ignore_index=True), [k_a]) == [], (
    "NF e CNPJ duplicados exigem conferência"
)
source_with_xml = source_pdf.copy()
source_with_xml["chave_nfe"] = key("101", issuer_b)
assert find(source_with_xml, [k_a]) == [], "Chave divergente no documento deve bloquear"
# Chave explícita também deve ser compatível com o CNPJ registrado.
exact = source_pdf.copy()
exact["chave_nfe"] = k_a
assert len(find(exact, [k_a])) == 1
assert find(exact, [k_b]) == []
assert find(pd.DataFrame(), [k_a]) == []
print("NFS_CTE_NO_CROSS_SUPPLIER_MATCH_OK")
