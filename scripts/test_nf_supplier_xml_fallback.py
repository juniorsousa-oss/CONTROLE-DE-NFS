"""Regressões fiscais: fornecedor TOTVS e busca de XML SEM CNPJ."""
from pathlib import Path

import nf_xml_library as library

key = list("3" * 44)
key[6:20] = list("11222333000181")
key[20:22] = list("55")
key = "".join(key)
raw = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<nfeProc><NFe><infNFe Id="NFe' + key + '">'
    '<ide><nNF>4699</nNF></ide>'
    '<emit><CNPJ>11222333000181</CNPJ>'
    '<xNome>ACME COMPONENTES ELETRICOS LTDA</xNome></emit>'
    '</infNFe></NFe></nfeProc>'
).encode()
candidate = {
    "numero": "4699", "chave": key,
    "cnpj_emitente": "11222333000181",
    "fornecedor_referencia": "ACME COMPONENTES ELETRICOS LTDA",
}
assert library._validate_name_fallback(candidate, raw)
assert library._validate_name_fallback(
    {**candidate, "fornecedor_referencia": "ACME COMPONENTES ELETRICOS"}
    , raw
)
for bad in (
    {**candidate, "numero": "4700"},
    {**candidate, "cnpj_emitente": "99999999000199"},
    {**candidate, "fornecedor_referencia": "EMPRESA COMPLETAMENTE DIFERENTE LTDA"},
    {**candidate, "fornecedor_referencia": ""},
):
    assert not library._validate_name_fallback(bad, raw), bad
assert not library._validate_name_fallback(candidate, b"<!DOCTYPE html>"+raw)

app = Path("streamlit_app.py").read_text(encoding="utf-8")
edge = Path("supabase/functions/nf-xml-library-api/index.ts").read_text(encoding="utf-8")
xml = Path("nf_xml_library.py").read_text(encoding="utf-8")
assert '"fornecedor_codigo": group["fornecedor_codigo"].iloc[0]' in app
assert '"fornecedor_codigo": _supplier_code_norm(' in app
assert '_resolved_cnpjs, _ = _supplier_cnpj_lookup(selected)' in app
assert 'if best_score < 88:' in app
assert 'if best_score >= 88:' in app
assert "candidatos_sem_cnpj:candidatosSemCnpj" in edge
assert "numberMatches.length===1" in edge
assert "fornecedor_referencia:item.fornecedor" in edge
assert 'if item.get("_verify_name") and not _validate_name_fallback(item, raw)' in xml
assert 'ThreadPoolExecutor(max_workers=min(4, len(records)))' in xml
print("NFS_TOTVS_SUPPLIER_XML_FALLBACK_OK")
