"""Regressão do carimbo SETTA com múltiplos CRs (NF 139459).

Usa PDF sintético, sem alterar nenhuma NF real.
"""
from __future__ import annotations

import re
import fitz

from danfe_generator import apply_operational_stamp
from operational_stamp import draw_operational_stamp_block, operational_stamp_default_size


CRS = "601202, 600103, 600402, 600113, 601401"
DESCRIPTIONS = (
    "CONTROLE DE QUALIDADE, CONFORMACAO, ALMOXARIFADO, "
    "PROCESSOS, SEGURANCA TRABALHO FABRICA"
)


def _base_pdf() -> bytes:
    document = fitz.open()
    page = document.new_page(width=595, height=842)
    page.insert_text((335, 690), "RESERVADO AO FISCO", fontsize=8, fontname="Times-Bold")
    content = document.tobytes()
    document.close()
    return content


def _text(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def test_nf139459() -> None:
    pdf = apply_operational_stamp(
        _base_pdf(),
        data_chegada="30/10/2026",
        cr=CRS,
        desc_cr=DESCRIPTIONS,
        natureza="MATERIAL DE ESCRITORIO",
        recebido_por="MOISES GONCALVES",
    )
    document = fitz.open(stream=pdf, filetype="pdf")
    try:
        assert document.page_count == 1
        text = document[0].get_text("text")
        assert _text(DESCRIPTIONS) in _text(text), f"DESC. CR ausente ou cortado: {text}"
        assert _text(CRS) in _text(text), f"CRs incompletos: {text}"
        assert "CONTROLE INTERNO - SETTA" in text
        assert _text("MOISES GONCALVES") in _text(text)
        assert operational_stamp_default_size() == (250.0, 104.0)
    finally:
        document.close()


def test_simple_cr() -> None:
    pdf = apply_operational_stamp(
        _base_pdf(),
        data_chegada="30/10/2026",
        cr="600402",
        desc_cr="ALMOXARIFADO",
        natureza="MATERIAL DE ESCRITORIO",
        recebido_por="RESPONSAVEL",
    )
    doc = fitz.open(stream=pdf, filetype="pdf")
    try:
        text = doc[0].get_text()
        assert "ALMOXARIFADO" in text
        assert "600402" in text
    finally:
        doc.close()


def test_missing_description_blocks_stamp() -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    try:
        try:
            draw_operational_stamp_block(
                page, fitz.Rect(320, 700, 570, 804),
                data_chegada="30/10/2026",
                cr=CRS,
                desc_cr="",
                natureza="MATERIAL DE ESCRITORIO",
                recebido_por="MOISES GONCALVES",
            )
        except ValueError as exc:
            assert "DESC. CR" in str(exc)
        else:
            raise AssertionError("Permitiu carimbo com CR e descrição vazia")
        assert "CONTROLE INTERNO - SETTA" not in page.get_text()
    finally:
        doc.close()


def test_extreme_description_raises_not_silent() -> None:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    try:
        try:
            draw_operational_stamp_block(
                page, fitz.Rect(320, 700, 570, 804),
                data_chegada="30/10/2026",
                cr=CRS,
                desc_cr="DESCRICAO " * 150,
                natureza="MATERIAL DE ESCRITORIO",
                recebido_por="MOISES GONCALVES",
            )
        except ValueError as exc:
            assert "excede" in str(exc)
        else:
            raise AssertionError("Texto excessivo foi ocultado silenciosamente")
        assert "CONTROLE INTERNO - SETTA" not in page.get_text()
    finally:
        doc.close()


def run() -> None:
    test_nf139459()
    test_simple_cr()
    test_missing_description_blocks_stamp()
    test_extreme_description_raises_not_silent()
    print("STAMP_MULTI_CR_OK")


if __name__ == "__main__":
    run()
