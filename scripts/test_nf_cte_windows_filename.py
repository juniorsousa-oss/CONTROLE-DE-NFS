"""Regressão do erro 0x80010135 (Windows: caminho longo) com ZIPs de DACTE.

Não usa documentos fiscais reais. Testa nomes, associação por chave fiscal e
conservação da carga documental dentro do ZIP.
"""
import io
import re
import zipfile
from pathlib import Path
from types import SimpleNamespace

from cte_generator import (
    MAX_CTE_PDF_FILENAME_BYTES,
    cte_output_name,
    cte_zip_safe_name,
    cte_supplier_from_rows,
    dacte_file_name,
)

assert MAX_CTE_PDF_FILENAME_BYTES <= 100


def meta(key_tail="1234567890", *, issuer=None):
    key = "0" * 20 + "57" + "0" * 12 + key_tail
    assert len(key) == 44
    return SimpleNamespace(
        numero="13273734",
        chave=key,
        emitente=issuer or
          "ALFA TRANSPORTES LTDA / TRANSPORTES TECNOLOGIA EM TRATAMENTO TERMICO E REVESTIMENTOS",
    )


links = ["297219", "297338", "297342", "297343", "297390", "297399"]
supplier = "REVESTIMENTOS SUPERFICIAIS E TRATAMENTO TERMICO LTDA"
a = meta()
filename = cte_output_name(a, links, supplier)
assert filename.startswith("CTE-13273734"), filename
assert "ALFA TRANSPOR" in filename, filename
assert "NF-" in filename and "MAIS" not in filename, filename
assert all(nf in filename for nf in links), filename
assert "REVESTIMENTOS" in filename, filename
assert "TRANSPORTES" in filename, filename
assert filename.endswith(".pdf") and "K1234567890" not in filename
assert len(filename.encode("utf-8")) <= 95, filename
assert not re.search(r'[\\/:*?"<>|]', filename), filename
assert cte_output_name(a, links, supplier) == filename
try:
    dacte_file_name(a)
except ValueError:
    pass
else:
    raise AssertionError("CT-e sem NF ou fornecedor deve bloquear nome")

# Nenhuma identidade fiscal de CT-e pode desaparecer numa colisão de numeração.
second = cte_output_name(meta("1234567891"), links, supplier)
assert filename == second, "Chaves diferentes não aparecem no nome aprovado"
assert cte_output_name(meta(), ["297219"], supplier) != cte_output_name(meta(), links, supplier)
assert cte_output_name(meta(), links, "OUTRO FORNECEDOR") != filename

# Arquivos já gerados pela versão anterior (nome de até 240 bytes) devem
# ser compactados no ZIP sem precisar reabrir/alterar o XML ou o PDF.
legacy = (
    "13273734 - ALFA TRANSPORTES LTDA - "
    + " + ".join(links)
    + " - REVESTIMENTOS SUPERFICIAIS E TRATAMENTO TERMICO LTDA.pdf"
)
assert len(legacy.encode("utf-8")) > 95
safe = cte_zip_safe_name(legacy, a.numero, a.emitente, links, a.chave, supplier)
assert safe == filename, (safe, filename)
assert cte_zip_safe_name("CTE-13273734.pdf", a.numero, a.emitente, links, a.chave, supplier) == filename
# Mesmo um arquivo antigo curto (com NF ou MAIS) recebe a nomenclatura simplificada.
assert cte_zip_safe_name("13273734 - NF-297219-MAIS5.pdf", a.numero, a.emitente, links, a.chave, supplier) == filename
assert cte_zip_safe_name("../caminho/indevido.pdf", a.numero, a.emitente, links, a.chave, supplier) == safe

# O fornecedor é obtido por chave fiscal e não é inferido por NF homônima.
nf_cnpj = "12345678000195"
nf_key = "31" + "2610" + nf_cnpj + "55" + "001" + "000297219" + "1" + "12345678" + "0"
cte_ref = {"refs_nfe":[nf_key], "linked_file_ids":["antigo"], "linked_nf_numbers":["297219"]}
nf_rows = [{"file_id":"novo", "chave_nfe":nf_key, "cnpj_fornecedor":nf_cnpj,
            "numero_nf":"297219", "fornecedor_padrao":supplier}]
assert cte_supplier_from_rows(cte_ref, nf_rows) == supplier
assert cte_supplier_from_rows({"linked_file_ids":["novo"]}, nf_rows) == supplier
assert cte_supplier_from_rows({"linked_nf_numbers":["297219"]}, nf_rows) == supplier
other_cnpj = "98765432000190"
other_key = "31" + "2610" + other_cnpj + "55" + "001" + "000297219" + "1" + "87654321" + "0"
nf_rows.append({"file_id":"outro", "chave_nfe":other_key,
                "cnpj_fornecedor":other_cnpj,
                "numero_nf":"297219", "fornecedor_padrao":"OUTRA EMPRESA"})
assert not cte_supplier_from_rows({"linked_nf_numbers":["297219"]}, nf_rows)
assert cte_supplier_from_rows(cte_ref, nf_rows) == supplier
assert cte_supplier_from_rows(
    {"refs_nfe":[nf_key, other_key]}, nf_rows
) == "MULTIPLOS FORNECEDORES"

# O caminho representativo deve caber no limite convencional de 260 caracteres.
target_directory = (
    r"C:\Users\COLABORADORA\Downloads\26-10-2026 - ARQUIVOS PRONTOS - NOTAS FISCAIS"
    r"\CTEs - 26.10 - SEN"
)
assert len(target_directory + "\\" + safe) < 260

pdf = b"%PDF-1.4\nTeste sem dados fiscais reais"
memory = io.BytesIO()
with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as z:
    z.writestr(safe, pdf)
with zipfile.ZipFile(io.BytesIO(memory.getvalue())) as z:
    assert z.namelist() == [safe]
    assert z.read(safe) == pdf

app = Path("streamlit_app.py").read_text(encoding="utf-8")
assert app.count("cte_zip_safe_name(") >= 3, "ZIP final e ZIP de conferência precisam sanitizar nomes"
avulsa = Path("nf_avulsa.py").read_text(encoding="utf-8")
assert "cte_output_name(" in avulsa, "Geração avulsa também deve compartilhar a regra"
assert '"linked_nf_numbers"' in app, "Referências completas das NFs precisam continuar no manifesto"
print("NFS_CTE_WINDOWS_PATH_0X80010135_OK")
