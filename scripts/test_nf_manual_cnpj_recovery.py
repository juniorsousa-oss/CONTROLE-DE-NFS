"""Regressão da busca manual NF + CNPJ (sem dados fiscais de produção)."""
import ast
import base64
import hashlib
from pathlib import Path
from types import SimpleNamespace

import pandas as pd

import nf_xml_library as lib
from nf_processor import digits_only, valid_cnpj


def make_cnpj(base: str) -> str:
    def digit(raw, weights):
        mod = sum(int(n) * w for n, w in zip(raw, weights)) % 11
        return "0" if mod < 2 else str(11 - mod)
    a = base + digit(base, [5,4,3,2,9,8,7,6,5,4,3,2])
    return a + digit(a, [6,5,4,3,2,9,8,7,6,5,4,3,2])


cnpj = make_cnpj("123456780001")
another = make_cnpj("876543210001")
assert valid_cnpj(cnpj) and valid_cnpj(another)
numero = "220823"


def key_for(number: str, issuer: str) -> str:
    result = "31" + "2610" + issuer + "55" + "001" + number.zfill(9) + "1" + "12345678" + "0"
    assert len(result) == 44
    return result


key = key_for(numero, cnpj)


def xml_for(number=numero, issuer=cnpj, document_key=key):
    return (
        f'<nfeProc><NFe><infNFe Id="NFe{document_key}">'
        f'<ide><nNF>{number}</nNF></ide><emit><CNPJ>{issuer}</CNPJ></emit>'
        '</infNFe></NFe></nfeProc>'
    ).encode()


raw = xml_for()
assert lib._manual_nfe_identity_matches(raw, numero, cnpj, key)
assert not lib._manual_nfe_identity_matches(raw, numero, another, key)
assert not lib._manual_nfe_identity_matches(raw, "220824", cnpj, key)
assert not lib._manual_nfe_identity_matches(raw, numero, cnpj, key_for("220824", cnpj))
assert not lib._manual_nfe_identity_matches(xml_for(issuer=another), numero, cnpj, key)
assert not lib._manual_nfe_identity_matches(b"<!DOCTYPE foo><abc/>", numero, cnpj)
assert not lib._manual_nfe_identity_matches(b"corrompido", numero, cnpj)
assert not lib._manual_nfe_identity_matches(b"", numero, cnpj)

candidate = {
    "id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    "numero": numero,
    "cnpj_emitente": cnpj,
    "chave": key,
    "arquivo_nome": "NF_TESTE.xml",
}

original_api = lib.library_api
original_st = lib.st
calls = []
response = {"nfe": [candidate], "nao_encontradas": []}
xml_bytes = raw


def fake_api(action, values=None, **kwargs):
    calls.append((action, values))
    if action == "match":
        return response
    if action == "download":
        return {"raw_base64": base64.b64encode(xml_bytes).decode(), "filename": "NF_TESTE.xml"}
    raise AssertionError(action)


try:
    state = {}
    lib.library_api = fake_api
    lib.st = SimpleNamespace(session_state=state)
    assert calls == [], "Consulta não pode iniciar sozinha"

    result = lib.recover_nfe_by_manual_cnpj(numero, cnpj)
    assert result["status"] == "encontrado", result
    assert [a for a, _ in calls] == ["match", "download"]
    assert calls[0][1]["nfs"] == [
        {"numero": numero, "cnpj": cnpj, "chave": "", "fornecedor": ""}
    ]
    assert len(state["document_upload_cache"]) == 1
    assert state["document_reprocess_needed"]
    lib.recover_nfe_by_manual_cnpj(numero, cnpj)
    assert len(state["document_upload_cache"]) == 1, "Não duplicar XML ao repetir consulta"

    old_len = len(state["document_upload_cache"])
    response = {"nfe": [], "nao_encontradas": [numero]}
    result = lib.recover_nfe_by_manual_cnpj(numero, cnpj)
    assert result["status"] == "ausente"
    assert len(state["document_upload_cache"]) == old_len

    response = {"nfe": [], "nao_encontradas": [numero+" (AMBÍGUA)"]}
    result = lib.recover_nfe_by_manual_cnpj(numero, cnpj)
    assert result["status"] == "ambiguo"

    response = {"nfe": [candidate], "nao_encontradas": []}
    xml_bytes = xml_for(issuer=another)
    result = lib.recover_nfe_by_manual_cnpj(numero, cnpj)
    assert result["status"] == "divergente", result
    assert len(state["document_upload_cache"]) == old_len

    response = {"nfe": [dict(candidate, cnpj_emitente=another)], "nao_encontradas": []}
    before = len(calls)
    result = lib.recover_nfe_by_manual_cnpj(numero, cnpj)
    assert result["status"] == "ausente"
    assert len(calls) == before+1 and calls[-1][0] == "match"

    try:
        lib.recover_nfe_by_manual_cnpj(numero, "11111111000111")
    except ValueError:
        pass
    else:
        raise AssertionError("CNPJ inválido deve bloquear consulta")
finally:
    lib.library_api = original_api
    lib.st = original_st


# Isola a aplicação do CNPJ manual e garante ausência de alteração na base.
source = Path("streamlit_app.py").read_text(encoding="utf-8")
tree = ast.parse(source)
methods = {
    node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)
}
manual = methods["_apply_stage2_manual_cnpjs"]
module = ast.Module(body=[manual], type_ignores=[])
ast.fix_missing_locations(module)
namespace = {
    "pd": pd, "digits_only": digits_only, "valid_cnpj": valid_cnpj,
    "flow_nf_key": lambda row: str(row.get("numero_nf")) + "|" + str(row.get("fornecedor")),
}
exec(compile(module, "<manual-cnpj-overlay>", "exec"), namespace)
overlay = namespace["_apply_stage2_manual_cnpjs"]
src = pd.DataFrame([
    {"numero_nf": numero, "cnpj": "", "fornecedor": "EXEMPLO"},
    {"numero_nf": "220824", "cnpj": another, "fornecedor": "OUTRO"},
])
got = overlay(src, {numero+"|EXEMPLO": cnpj, "220824|OUTRO": cnpj})
assert got.iloc[0]["cnpj"] == cnpj
assert got.iloc[1]["cnpj"] == another, "CNPJ completo divergente não pode ser sobreposto"
assert src.iloc[0]["cnpj"] == "", "Base original não pode ser mutada"
assert overlay(src, {numero+"|EXEMPLO": "123"})["cnpj"].iloc[0] == ""
assert overlay(src.iloc[:0], {}).empty

render = ast.get_source_segment(source, methods["render_document_linking_stage"])
assert "CONSULTAR XML PELO CNPJ DO EMITENTE" in render
assert "BUSCAR XML POR NF + CNPJ" in render
assert "nf_stage2_manual_cnpjs" in render
assert "recover_nfe_by_manual_cnpj(" in render
assert 'st.rerun()' in render
assert "valid_cnpj(_typed_cnpj)" in render
assert "valid_cnpj(_current_cnpj) and _current_cnpj != _typed_cnpj" in render
assert "with st.form(f\"nf_stage2_manual_cnpj_search_form_{_form_key}\")" in render
assert "st.session_state.nf_stage2_manual_cnpjs = {}" in source

print("NFS_MANUAL_CNPJ_RECOVERY_OK")
