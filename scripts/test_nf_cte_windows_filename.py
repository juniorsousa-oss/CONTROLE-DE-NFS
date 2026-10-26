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
assert "ALFA TRANSPORTES" in filename, filename
assert "NF-" not in filename and "MAIS" not in filename, filename
assert all(nf not in filename for nf in links), filename
assert supplier not in filename, filename
assert filename.endswith(".pdf") and "K1234567890" in filename
assert len(filename.encode("utf-8")) <= 95, filename
assert not re.search(r'[\\/:*?"<>|]', filename), filename
assert cte_output_name(a, links, supplier) == filename
assert len(dacte_file_name(a).encode("utf-8")) <= 95

# Nenhuma identidade fiscal de CT-e pode desaparecer numa colisão de numeração.
second = cte_output_name(meta("1234567891"), links, supplier)
assert filename != second
assert cte_output_name(meta(), ["297219"], supplier) == cte_output_name(meta(), links, supplier)
assert cte_output_name(meta(), links, "OUTRO FORNECEDOR") == filename

# Arquivos já gerados pela versão anterior (nome de até 240 bytes) devem
# ser compactados no ZIP sem precisar reabrir/alterar o XML ou o PDF.
legacy = (
    "13273734 - ALFA TRANSPORTES LTDA - "
    + " + ".join(links)
    + " - REVESTIMENTOS SUPERFICIAIS E TRATAMENTO TERMICO LTDA.pdf"
)
assert len(legacy.encode("utf-8")) > 95
safe = cte_zip_safe_name(legacy, a.numero, a.emitente, links, a.chave)
assert safe == cte_output_name(a, links), (safe, filename)
assert cte_zip_safe_name("CTE-13273734.pdf", a.numero, a.emitente, links, a.chave) == filename
# Mesmo um arquivo antigo curto (com NF ou MAIS) recebe a nomenclatura simplificada.
assert cte_zip_safe_name("13273734 - NF-297219-MAIS5.pdf", a.numero, a.emitente, links, a.chave) == filename
assert cte_zip_safe_name("../caminho/indevido.pdf", a.numero, a.emitente, links, a.chave) == safe

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
