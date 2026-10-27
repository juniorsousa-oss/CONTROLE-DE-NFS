"""Falhas reais simuladas: ZIP contém NF/CT-e de outra seleção.

Executa sem Streamlit, Supabase, dados fiscais reais ou envios.
"""
import io
import zipfile
from copy import deepcopy
from pathlib import Path

from nf_batch_integrity import validate_batch_selection, validate_zip_manifest


def fiscal_key(number, cnpj, model="55"):
    # Chave sintética: testa o formato/posição das informações, sem documento real.
    result = "31" + "2610" + cnpj + model + "001" + number.zfill(9) + "1" + "12345678" + "0"
    assert len(result) == 44
    return result


k1 = fiscal_key("101", "12345678000195")
k2 = fiscal_key("102", "98765432000190")
ct = fiscal_key("999", "55555555000100", "57")
selected = {"101|ALFA"}
snapshot = [
    {"_selection_key": "101|ALFA", "numero_nf": "101", "cnpj": "12345678000195"}
]
work = [
    {"_selection_key": "101|ALFA", "numero_nf": "101",
     "cnpj_fornecedor": "12345678000195",
     "chave_nfe": k1, "file_id": "pdf-a", "arquivo_final": "ALFA.pdf"}
]
pdfs = {"pdf-a": {"bytes": b"%PDF-1.4"}}
cte = [{
    "chave_cte": ct, "numero_cte": "999",
    "refs_nfe": [k1], "linked_file_ids": ["pdf-a"],
    "linked_nf_numbers": ["101"],
}]
validate_batch_selection(selected, snapshot, work, pdfs, cte)

def rejected(title, selected_keys=selected, expected=snapshot, actual=work,
             files=pdfs, transports=cte):
    try:
        validate_batch_selection(
            set(selected_keys), deepcopy(expected), deepcopy(actual),
            deepcopy(files), deepcopy(transports)
        )
    except ValueError as exc:
        assert "LOTE BLOQUEADO" in str(exc), (title, exc)
    else:
        raise AssertionError("Lote incorreto foi aceito: " + title)


rejected("seleção vazia", selected_keys=set())
rejected("sem snapshot", expected=[])
rejected("NF extra com mesma quantidade", actual=[
    {**work[0], "_selection_key": "102|OUTRA", "numero_nf": "102", "chave_nfe": k2}
])
rejected("NF adicional", actual=work+[{
    "_selection_key": "102|OUTRA", "numero_nf": "102",
    "cnpj_fornecedor": "98765432000190", "chave_nfe": k2,
    "file_id": "pdf-b",
}])
rejected("NF com CNPJ de outra empresa", actual=[
    {**work[0], "cnpj_fornecedor": "98765432000190"}
])
rejected("NF com chave fiscal de outra nota", actual=[
    {**work[0], "chave_nfe": k2}
])
rejected("PDF de outro lote", actual=[{**work[0], "file_id": "pdf-b"}])
rejected("CT-e antigo de outra NF", transports=[
    {**cte[0], "refs_nfe": [k2], "linked_nf_numbers": ["102"]}
])
rejected("CT-e incluindo NF fora do lote", transports=[
    {**cte[0], "refs_nfe": [k1, k2], "linked_nf_numbers": ["101", "102"]}
])
rejected("CT-e sem vínculo fiscal/ID", transports=[
    {**cte[0], "refs_nfe": [], "linked_file_ids": [], "linked_nf_numbers": ["101"]}
])
rejected("CT-e com ID de sessão anterior", transports=[
    {**cte[0], "refs_nfe": [], "linked_file_ids": ["old-id"]}
])
rejected("CT-e duplicado", transports=cte + cte)

# Associação por ID é permitida quando o CT-e PDF não contém chaves, mas deve
# apontar exclusivamente para IDs de NFs já autorizadas.
validate_batch_selection(selected, snapshot, work, pdfs, [{
    "cte_id": "pdf-cte-1", "numero_cte": "999",
    "linked_file_ids": ["pdf-a"], "linked_nf_numbers": ["101"],
}])

def zips(paths):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as z:
        for name in paths:
            z.writestr(name, b"%PDF-1.4")
    return buf.getvalue()


manifest = [
    {"arquivo_final": "ALFA.pdf", "tipo_documento": "NF-e"},
    {"arquivo_final": "CTE.pdf", "tipo_documento": "CT-e"},
]
correct = {
    "NFs - SEN.zip": zips(["NORMAIS/ALFA.pdf"]),
    "CTE - SEN.zip": zips(["CTE.pdf"]),
}
validate_zip_manifest(correct, manifest)
for label, wrong in [
    ("NF trocada", {"NFs - SEN.zip": zips(["NORMAIS/OUTRA.pdf"]),
                    "CTE - SEN.zip": zips(["CTE.pdf"])}),
    ("CT-e trocado", {"NFs - SEN.zip": zips(["NORMAIS/ALFA.pdf"]),
                     "CTE - SEN.zip": zips(["OUTRO_CTE.pdf"])}),
    ("NF extra", {"NFs - SEN.zip": zips(["NORMAIS/ALFA.pdf","NORMAIS/EXTRA.pdf"]),
                 "CTE - SEN.zip": zips(["CTE.pdf"])}),
    ("pacote misto", {"NFs - SEN.zip": zips(["NORMAIS/ALFA.pdf","NORMAIS/CTE.pdf"])}),
]:
    try:
        validate_zip_manifest(wrong, manifest)
    except ValueError as exc:
        assert "LOTE BLOQUEADO" in str(exc)
    else:
        raise AssertionError(label + " não foi bloqueado")

source = Path("streamlit_app.py").read_text(encoding="utf-8")
for excerpt in (
    "validate_batch_selection(",
    "validate_zip_manifest(outputs, manifest)",
    "if active != frozen_keys",
    "_expire_stale_nf_zip()",
    "batch_signature",
    "if len(companies) != 1:",
):
    assert excerpt in source, excerpt

print("NFS_BATCH_INTEGRITY_STRICT_OK")
