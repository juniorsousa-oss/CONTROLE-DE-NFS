"""Regressão: o DACTE não pode omitir a razão social ou título.

Usa exclusivamente CT-e sintético (sem XML nem documentos fiscais reais).
"""
from __future__ import annotations

import fitz

from cte_generator import (
    _parse_cte,
    _status_exibicao,
    generate_dacte_pdf,
)


NAMESPACE = "http://www.portalfiscal.inf.br/cte"
KEY = "35261144914992000138570010646971461123456789"
assert len(KEY) == 44


def sample_xml(
    name: str = "RODONAVES TRANSPORTES E ENCOMENDAS LTDA",
    status: str = "Autorizado o uso do $APP_NAME_FORMATED$",
    qr: bool = True,
    obs: str = "FRETE NORMAL",
    cstat: str = "100",
) -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<cteProc xmlns="{NAMESPACE}">
  <CTe><infCte Id="CTe{KEY}">
    <ide>
      <mod>57</mod><nCT>64697146</nCT><serie>1</serie>
      <CFOP>6352</CFOP><natOp>PRESTACAO SERVICO TRANSPORTE</natOp>
      <modal>01</modal><tpAmb>1</tpAmb>
      <xMunIni>ITUPEVA</xMunIni><UFIni>SP</UFIni>
      <xMunFim>PATOS DE MINAS</xMunFim><UFFim>MG</UFFim>
    </ide>
    <emit><CNPJ>44914992000138</CNPJ><IE>582249216111</IE>
      <xNome>{name}</xNome>
      <enderEmit>
        <xLgr>RUA GENERAL AUGUSTO SOARES DOS SANTOS</xLgr>
        <nro>550</nro><xBairro>PARQUE INDUSTRIAL</xBairro>
        <xMun>RIBEIRAO PRETO</xMun><UF>SP</UF><CEP>14095240</CEP>
      </enderEmit>
    </emit>
    <rem><CNPJ>56990468000125</CNPJ><xNome>ELETRISOL INDUSTRIA E COMERCIO LTDA</xNome></rem>
    <dest><CNPJ>11935893000183</CNPJ><xNome>SETTA ENERGY PAINEIS LTDA</xNome></dest>
    <compl><xObs>{obs}</xObs></compl>
    <vPrest><vTPrest>940.22</vTPrest><vRec>940.22</vRec>
      <Comp><xNome>FRETE PESO</xNome><vComp>279.17</vComp></Comp>
    </vPrest>
    <imp><ICMS><ICMS00><CST>00</CST><vBC>940.22</vBC><pICMS>12</pICMS><vICMS>112.82</vICMS></ICMS00></ICMS></imp>
    <infCTeNorm><infCarga><proPred>OUTRAS</proPred><vCarga>27953.33</vCarga>
      <infQ><cUnid>01</cUnid><tpMed>PESO DECLARADO</tpMed><qCarga>198.6</qCarga></infQ>
    </infCarga><infDoc><infNFe><chave>35261156990468000125550010000914831158546785</chave></infNFe></infDoc>
    </infCTeNorm>
  </infCte>
  {"<infCTeSupl><qrCodCTe>https://example.invalid/qrcode</qrCodCTe></infCTeSupl>" if qr else ""}
  </CTe>
  <protCTe><infProt><nProt>135265946394719</nProt><cStat>{cstat}</cStat>
    <xMotivo>{status}</xMotivo><dhRecbto>2026-11-13T11:45:00-03:00</dhRecbto>
  </infProt></protCTe>
</cteProc>""".encode("utf-8")


def assert_pdf_integrity(raw: bytes, *, name: str, qr: bool) -> None:
    pdf = generate_dacte_pdf(raw)
    assert pdf.startswith(b"%PDF-"), "O resultado não é um PDF"
    with fitz.open(stream=pdf, filetype="pdf") as document:
        assert len(document) == 1
        page = document[0]
        text = " ".join(page.get_text().split())
        for field in (
            "DACTE", name, "CT-e Nº 64697146", "SÉRIE 1",
            "135265946394719", "RODOVIÁRIO", "SETTA ENERGY PAINEIS LTDA",
        ):
            assert field in text, (field, text[:700])
        assert "Autorizado o uso do CT-e" in text, text
        assert "$APP_NAME_FORMATED$" not in text
        assert page.get_images() if qr else True
        if qr:
            rect = fitz.Rect(530, 88, 568, 126)
            blocks = page.get_text("dict")["blocks"]
            for block in blocks:
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        if span.get("text", "").strip():
                            bbox = fitz.Rect(span["bbox"])
                            assert not bbox.intersects(rect), (
                                "Texto sobreposto ao QR:", span["text"], bbox
                            )


def run_tests() -> None:
    full_name = "RODONAVES TRANSPORTES E ENCOMENDAS LTDA"
    raw = sample_xml()
    parsed = _parse_cte(raw)
    assert parsed["emit"]["nome"] == full_name
    assert parsed["status_motivo"] == "Autorizado o uso do $APP_NAME_FORMATED$"
    assert _status_exibicao(parsed["status_codigo"], parsed["status_motivo"]) == (
        "Autorizado o uso do CT-e"
    )
    assert_pdf_integrity(raw, name=full_name, qr=True)
    assert_pdf_integrity(sample_xml(qr=False), name=full_name, qr=False)
    assert_pdf_integrity(
        sample_xml(name="TRANSPORTADORA TESTE LTDA"),
        name="TRANSPORTADORA TESTE LTDA", qr=True,
    )
    assert_pdf_integrity(
        sample_xml(status="Autorizado o uso do CT-e"),
        name=full_name, qr=True,
    )
    # Não inventar transportadora: emissão sem xNome é bloqueada.
    try:
        generate_dacte_pdf(sample_xml(name=""))
    except ValueError as exc:
        assert "sem razão social" in str(exc), str(exc)
    else:
        raise AssertionError("PDF sem transportadora foi gerado")

    # Marcador desconhecido não deve ser publicado como texto fiscal.
    try:
        generate_dacte_pdf(sample_xml(status="Autorizado o uso do $TOKEN_NOVO$"))
    except ValueError as exc:
        assert "marcador não resolvido" in str(exc), str(exc)
    else:
        raise AssertionError("PDF com token desconhecido foi gerado")

    # Texto absurdamente extenso deve gerar erro explícito, nunca PDF mutilado.
    try:
        generate_dacte_pdf(sample_xml(obs="OBSER" * 2000))
    except ValueError as exc:
        assert "não cabe" in str(exc), str(exc)
    else:
        raise AssertionError("Observação que não cabe foi omitida silenciosamente")
    print("NFS_DACTE_VISUAL_INTEGRITY_OK")


if __name__ == "__main__":
    run_tests()
