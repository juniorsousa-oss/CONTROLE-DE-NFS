"""Conferência fiscal CT-e completo: transportadora vs fornecedor e NF faltante.

Fatos reproduzidos com chaves sintéticas: CT-e 94 referindo duas NFs e
CT-e 96 referindo uma NF, ambas da mesma fornecedora. Sem produção.
"""
from pathlib import Path

from nf_batch_integrity import cte_reference_coverage
from cte_generator import cte_supplier_from_rows


def key(number, cnpj):
    value = ("31" + "2610" + cnpj + "55" + "001"
             + str(number).zfill(9) + "1" + "12345678" + "0")
    assert len(value) == 44
    return value


cnpj_tasco = "43071109000122"
supplier = "TASCO LIMITADA"
ref_344293 = key(344293, cnpj_tasco)
ref_344501 = key(344501, cnpj_tasco)

ctes = [
    {
        "numero_cte": "13287494", "transportadora": "ALFA TRANSPORTES LTDA",
        "cnpj_transportadora": "82110818000393",
        "refs_nfe": [ref_344293, ref_344501],
    },
    {
        "numero_cte": "13287596", "transportadora": "ALFA TRANSPORTES LTDA",
        "cnpj_transportadora": "82110818000393",
        "refs_nfe": [ref_344501],
    },
]

selected = [{
    "numero_nf": "344501", "file_id": "nf344501", "chave_nfe": ref_344501,
    "cnpj_fornecedor": cnpj_tasco, "fornecedor_padrao": supplier
}]

report_94 = cte_reference_coverage(ctes[0], selected)
report_96 = cte_reference_coverage(ctes[1], selected)
assert report_94["cited"] == ["344293", "344501"], report_94
assert report_94["covered"] == ["344501"], report_94
assert report_94["missing"] == ["344293"], report_94
assert report_94["complete"] is False, report_94
assert report_96["complete"] and report_96["missing"] == [], report_96

# A transportadora é emitente do CT-e, TASCO é fornecedor das NFs.
assert cte_supplier_from_rows(ctes[0], selected) == supplier
assert cte_supplier_from_rows(ctes[1], selected) == supplier
assert ctes[0]["transportadora"] != supplier

# Após incluir a NF faltante, o CT-e completo fica conferível.
selected.append({
    "numero_nf": "344293", "file_id": "nf344293", "chave_nfe": ref_344293,
    "cnpj_fornecedor": cnpj_tasco, "fornecedor_padrao": supplier
})
assert cte_reference_coverage(ctes[0], selected)["complete"]
# Sem pré-nota, uma remessa validada no XML cobre só a referência fiscal,
# permanecendo fora das NFs selecionadas.
auxiliary = {ref_344293: {
    "chave": ref_344293, "numero": "344293", "cnpj": cnpj_tasco,
    "bytes": b"%PDF-1.4", "natureza_fiscal": "REMESSA"
}}
aux_coverage = cte_reference_coverage(ctes[0], selected[:1], auxiliary)
assert aux_coverage["complete"] and aux_coverage["auxiliary"] == ["344293"]
assert aux_coverage["covered"] == ["344501"]
assert not cte_reference_coverage(
    ctes[0], selected[:1], {ref_344293: {**auxiliary[ref_344293], "cnpj": "00000000000000"}}
)["complete"]

# Nenhum emissor homônimo ou CNPJ divergente pode dar falso positivo.
wrong = [{**selected[0], "cnpj_fornecedor": "82110818000393"}]
assert not cte_reference_coverage(ctes[1], wrong)["complete"]
assert cte_supplier_from_rows(ctes[1], wrong) == ""
double = selected + [dict(selected[0], file_id="nf344501_dup")]
assert not cte_reference_coverage(ctes[1], double)["complete"]

# PDF da NF sem chave pode ser aceito, mas somente por NF + CNPJ únicos.
pdf_only = [{**selected[0], "chave_nfe": ""}]
assert cte_reference_coverage(ctes[1], pdf_only)["complete"]
assert not cte_reference_coverage(ctes[1], pdf_only + pdf_only)["complete"]

app = Path("streamlit_app.py").read_text("utf-8")
assert "cte_reference_coverage(" in app
assert "cte, selected_rows, verified_remessas" in app
assert "TODAS AS NFs DO CT-e" in app
assert "NFs FORA DO LOTE" in app
assert "TRANSPORTADORA (EMITENTE CT-e)" in app
assert "FORNECEDOR DAS NFs" in app
assert "if cte_outside_selection:" in app
assert "ZIP BLOQUEADO" in app
print("NFS_CTE_FISCAL_REFERENCE_COVERAGE_OK")
