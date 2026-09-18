from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass


NFE_NS = "{http://www.portalfiscal.inf.br/nfe}"


@dataclass(frozen=True)
class DanfeMetadata:
    numero_nf: str
    serie: str
    chave: str
    emitente: str
    cnpj_emitente: str
    destinatario: str
    data_emissao: str
    protocolo: str
    status_codigo: str
    status_motivo: str


def _text(root: ET.Element, path: str) -> str:
    node = root.find(path)
    return (node.text or "").strip() if node is not None else ""


def _digits(value: str) -> str:
    return re.sub(r"\D+", "", value or "")


def _safe_name(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]+', " ", value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value[:90] or "EMITENTE"


def extract_danfe_metadata(raw_xml: bytes) -> DanfeMetadata:
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as exc:
        raise ValueError("XML inválido ou corrompido.") from exc

    root_name = root.tag.split("}")[-1]
    if root_name not in {"nfeProc", "NFe"}:
        raise ValueError(
            f"XML não reconhecido como NF-e. Tag raiz encontrada: {root_name or 'desconhecida'}."
        )

    ide = root.find(f".//{NFE_NS}ide")
    emit = root.find(f".//{NFE_NS}emit")
    dest = root.find(f".//{NFE_NS}dest")
    inf_nfe = root.find(f".//{NFE_NS}infNFe")
    prot = root.find(f".//{NFE_NS}protNFe/{NFE_NS}infProt")

    if ide is None or emit is None or inf_nfe is None:
        raise ValueError("O XML não contém a estrutura mínima de uma NF-e.")

    modelo = _text(ide, f"{NFE_NS}mod")
    if modelo != "55":
        raise ValueError(
            f"O XML é modelo {modelo or '?'}; esta ferramenta gera DANFE de NF-e modelo 55."
        )

    numero = _text(ide, f"{NFE_NS}nNF")
    serie = _text(ide, f"{NFE_NS}serie")
    emitente = _text(emit, f"{NFE_NS}xNome")
    cnpj = _text(emit, f"{NFE_NS}CNPJ") or _text(emit, f"{NFE_NS}CPF")
    destinatario = _text(dest, f"{NFE_NS}xNome") if dest is not None else ""
    data_emissao = _text(ide, f"{NFE_NS}dhEmi") or _text(ide, f"{NFE_NS}dEmi")

    chave = (inf_nfe.attrib.get("Id") or "").strip()
    if chave.upper().startswith("NFE"):
        chave = chave[3:]
    chave = _digits(chave)

    protocolo = ""
    status_codigo = ""
    status_motivo = ""
    if prot is not None:
        protocolo = _text(prot, f"{NFE_NS}nProt")
        status_codigo = _text(prot, f"{NFE_NS}cStat")
        status_motivo = _text(prot, f"{NFE_NS}xMotivo")

    return DanfeMetadata(
        numero_nf=numero,
        serie=serie,
        chave=chave,
        emitente=emitente,
        cnpj_emitente=_digits(cnpj),
        destinatario=destinatario,
        data_emissao=data_emissao,
        protocolo=protocolo,
        status_codigo=status_codigo,
        status_motivo=status_motivo,
    )


def generate_danfe_pdf(raw_xml: bytes) -> bytes:
    extract_danfe_metadata(raw_xml)

    try:
        from brazilfiscalreport.danfe import (
            Danfe,
            DanfeConfig,
            DecimalConfig,
            FontSize,
            FontType,
            InvoiceDisplay,
            Margins,
            ProductDescriptionConfig,
            ReceiptPosition,
        )
    except Exception as exc:
        raise RuntimeError(
            "O gerador de DANFE não está disponível no ambiente. "
            "Verifique a instalação da dependência brazilfiscalreport."
        ) from exc

    config = DanfeConfig(
        margins=Margins(top=5, right=5, bottom=5, left=5),
        receipt_pos=ReceiptPosition.TOP,
        carrier_receipt=False,
        decimal_config=DecimalConfig(
            price_precision=4,
            quantity_precision=4,
        ),
        invoice_display=InvoiceDisplay.FULL_DETAILS,
        font_type=FontType.TIMES,
        font_size=FontSize.SMALL,
        display_pis_cofins=False,
        infcpl_semicolon_newline=False,
        product_description_config=ProductDescriptionConfig(
            display_branch=False,
            display_anp=False,
            display_anvisa=False,
            branch_info_prefix="",
            display_additional_info=True,
        ),
    )

    try:
        document = Danfe(xml=raw_xml, config=config)
        return bytes(document.output())
    except Exception as exc:
        raise ValueError(f"Não foi possível gerar o DANFE deste XML: {exc}") from exc


def danfe_file_name(meta: DanfeMetadata) -> str:
    numero = re.sub(r"\D+", "", meta.numero_nf or "") or "SEM_NUMERO"
    emitente = _safe_name(meta.emitente)
    return f"DANFE_NF_{numero}_{emitente}.pdf"
