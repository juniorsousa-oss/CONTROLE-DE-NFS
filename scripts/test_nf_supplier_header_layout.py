"""Valida layouts reais de fornecedores TOTVS sem usar dados produtivos."""
import pandas as pd

from supplier_import import parse_supplier_report, validate_supplier_report


def cnpj(base):
    assert len(base) == 12 and base.isdigit()
    def digit(number, weights):
        mod = sum(int(v)*w for v, w in zip(number, weights)) % 11
        return "0" if mod < 2 else str(11-mod)
    first = digit(base, [5,4,3,2,9,8,7,6,5,4,3,2])
    return base + first + digit(base + first, [6,5,4,3,2,9,8,7,6,5,4,3,2])

doc1, doc2, doc3 = cnpj("123456780001"), cnpj("123456780002"), cnpj("345678900001")
header = [
    "Codigo", "Loja", "Razao Social", "N Fantasia", "Endereco",
    "Bairro", "Contrib.Prev", "Tpo Contrato", "Impacto",
    "CNPJ/CPF", "Vinculacao", "E-Mail", "Cod. Abics",
    "Ins. no Munc", "OBSBLQ", "Dt. Inclusao"
]


def row(code, store, name, doc, fantasy="", obs=""):
    cells = [""] * 16
    for pos, value in {
        0: code, 1: store, 2: name, 3: fantasy,
        7: "Fabricante", 9: doc, 14: obs,
    }.items():
        cells[pos] = value
    return cells


raw = pd.DataFrame([
    ["Listagem do Browse"] + [""] * 15,
    header,
    row("000095", "01", "FORNECEDOR EXEMPLO LTDA", doc1, "FORNECEDOR", "BLOQUEADO"),
    row("000095", "03", "FORNECEDOR EXEMPLO LTDA", doc2),
    row("000040", "01", "OUTRO FORNECEDOR LTDA", doc3),
    row("000041", "01", "FORNECEDOR CPF", "12345678901"),
    [""] * 16,
])

report = validate_supplier_report(raw)
assert report["columns"]["cnpj"] == "J", report["columns"]
assert report["columns"]["tipo"] == "H"
assert report["columns"]["loja"] == "B"
assert report["stats"]["validos"] == 3, report["stats"]
assert report["stats"]["cpfs"] == 1
assert report["stats"]["conflitos"] == 0
result = report["clean"]
assert set(result["cnpj"]) == {doc1, doc2, doc3}
assert set(result.loc[result["codigo"] == "000095", "loja"]) == {"01", "03"}
assert result["tipo"].eq("Fabricante").all()
assert not result["cnpj"].eq("BLOQUEADO").any()

# Layout mais antigo: CNPJ/CPF em O, tipo em K. Não pressupor posição fixa.
legacy = raw.copy()
legacy.iloc[1, 9] = "Impacto 2"
legacy.iloc[1, 14] = "CNPJ/CPF"
legacy.iloc[1, 10] = "Tipo"
legacy.iloc[2:, 14] = raw.iloc[2:, 9].to_numpy()
legacy.iloc[2:, 9] = ""
legacy.iloc[2:, 10] = "Comercial"
legacy_result = validate_supplier_report(legacy)
assert legacy_result["columns"]["cnpj"] == "O"
assert legacy_result["columns"]["tipo"] == "K"
assert set(legacy_result["clean"]["cnpj"]) == {doc1, doc2, doc3}

# Se o cabeçalho não existir, não importar por posição presumida.
try:
    parse_supplier_report(pd.DataFrame([row("0001", "01", "TESTE", doc1)]))
except ValueError as exc:
    assert "cabeçalho" in str(exc)
else:
    raise AssertionError("Cabeçalho desconhecido deveria bloquear importação.")

try:
    parse_supplier_report(pd.DataFrame())
except ValueError:
    pass
else:
    raise AssertionError("Planilha vazia não pode substituir o cadastro.")

# Código + loja duplicado com dois documentos diferentes deve bloquear.
collision = raw.copy()
collision.iloc[3, 1] = "01"
try:
    validate_supplier_report(collision)
except ValueError as exc:
    assert "código(s)/loja(s)" in str(exc)
else:
    raise AssertionError("Dois CNPJs para o mesmo código e loja deveriam bloquear.")

# Um mesmo CNPJ pode ter mais de um código cadastral; preservar vínculos.
same_doc = raw.copy()
same_doc.iloc[4, 9] = doc1
same_doc.iloc[4, 2] = "FORNECEDOR EXEMPLO LTDA"
matched = validate_supplier_report(same_doc)
assert matched["stats"]["cnpjs_distintos"] == 2
assert matched["stats"]["validos"] == 3

# Documentos declarados com razões sociais incompatíveis não são descartados
# silenciosamente nem liberados como base integral.
bad_names = raw.copy()
bad_names.iloc[4, 9] = doc1
bad_names.iloc[4, 2] = "EMPRESA ESTRANHA SEM RELACAO"
conflicted = validate_supplier_report(bad_names)
assert conflicted["stats"]["conflitos"] == 1
assert not conflicted["conflicts"].empty

# Não aceitar nome/observação no lugar do documento fiscal.
wrong_column = raw.copy()
wrong_column.iloc[1, 9] = "Outros"
wrong_column.iloc[1, 14] = "CNPJ/CPF"
try:
    validate_supplier_report(wrong_column)
except ValueError as exc:
    assert "Nenhum CNPJ válido" in str(exc)
else:
    raise AssertionError("Cadastro sem CNPJ válido não pode ser aplicado.")

print("NFS_SUPPLIER_HEADER_LAYOUT_OK")
