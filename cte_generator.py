from __future__ import annotations

import io
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

import fitz
import qrcode


CTE_NS = "{http://www.portalfiscal.inf.br/cte}"
BLACK = (0, 0, 0)
GRAY = (0.35, 0.35, 0.35)
LIGHT = (0.94, 0.94, 0.94)


@dataclass
class CteMetadata:
    numero: str
    serie: str
    chave: str
    emitente: str
    cnpj_emitente: str
    protocolo: str
    status_codigo: str
    status_motivo: str
    modalidade: str
    refs_nfe: list[str]
    qr_code: str


def _digits(value: object) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _safe_name(value: object) -> str:
    text = re.sub(r'[\\/:*?"<>|]+', " ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    return text[:90] or "TRANSPORTADORA"


def _local(tag: str) -> str:
    return str(tag or "").split("}")[-1]


def _find(parent: ET.Element | None, path: str) -> ET.Element | None:
    if parent is None:
        return None
    node = parent.find(path)
    if node is not None:
        return node
    wanted = path.split("/")[-1].replace(CTE_NS, "")
    for candidate in parent.iter():
        if _local(candidate.tag) == wanted:
            return candidate
    return None


def _text(parent: ET.Element | None, tag: str) -> str:
    if parent is None:
        return ""
    node = parent.find(f"{CTE_NS}{tag}")
    if node is not None and node.text:
        return str(node.text).strip()
    for child in list(parent):
        if _local(child.tag) == tag and child.text:
            return str(child.text).strip()
    return ""


def _fmt_date(value: str) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d/%m/%Y %H:%M")
    except Exception:
        match = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
        if match:
            return f"{match.group(3)}/{match.group(2)}/{match.group(1)}"
        return value


def _fmt_tax_id(value: str) -> str:
    d = _digits(value)
    if len(d) == 14:
        return f"{d[:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:]}"
    if len(d) == 11:
        return f"{d[:3]}.{d[3:6]}.{d[6:9]}-{d[9:]}"
    return value


def _fmt_money(value: str) -> str:
    try:
        number = float(str(value or "0").replace(",", "."))
    except Exception:
        number = 0.0
    return f"{number:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _format_key(value: str) -> str:
    d = _digits(value)
    if len(d) != 44:
        return d
    return " ".join(d[i:i + 4] for i in range(0, 44, 4))


def _party(node: ET.Element | None) -> dict:
    if node is None:
        return {}
    addr = None
    for child in list(node):
        if _local(child.tag).lower().startswith("ender"):
            addr = child
            break
    return {
        "nome": _text(node, "xNome"),
        "cnpj": _text(node, "CNPJ") or _text(node, "CPF"),
        "ie": _text(node, "IE"),
        "logradouro": _text(addr, "xLgr"),
        "numero": _text(addr, "nro"),
        "bairro": _text(addr, "xBairro"),
        "municipio": _text(addr, "xMun"),
        "uf": _text(addr, "UF"),
        "cep": _text(addr, "CEP"),
        "fone": _text(addr, "fone"),
    }


def _parse_cte(raw_xml: bytes) -> dict:
    try:
        root = ET.fromstring(raw_xml)
    except ET.ParseError as exc:
        raise ValueError("XML de CT-e inválido ou corrompido.") from exc

    root_name = _local(root.tag)
    if root_name not in {"cteProc", "CTe"}:
        raise ValueError(
            f"XML não reconhecido como CT-e. Tag raiz encontrada: {root_name or 'desconhecida'}."
        )

    inf_cte = root.find(f".//{CTE_NS}infCte")
    ide = root.find(f".//{CTE_NS}ide")
    emit = root.find(f".//{CTE_NS}emit")
    if inf_cte is None or ide is None or emit is None:
        raise ValueError("O XML não contém a estrutura mínima de um CT-e.")

    modelo = _text(ide, "mod")
    if modelo and modelo != "57":
        raise ValueError(f"O XML é modelo {modelo}; o gerador aceita CT-e modelo 57.")

    prot = root.find(f".//{CTE_NS}protCTe/{CTE_NS}infProt")
    supl = root.find(f".//{CTE_NS}infCTeSupl")
    inf_norm = root.find(f".//{CTE_NS}infCTeNorm")
    inf_carga = root.find(f".//{CTE_NS}infCarga")
    vprest = root.find(f".//{CTE_NS}vPrest")
    imp = root.find(f".//{CTE_NS}imp")
    icms = root.find(f".//{CTE_NS}ICMS")

    key = str(inf_cte.attrib.get("Id") or "").strip()
    if key.upper().startswith("CTE"):
        key = key[3:]
    key = _digits(key)

    refs = []
    for node in root.findall(f".//{CTE_NS}infNFe/{CTE_NS}chave"):
        value = _digits(node.text)
        if len(value) == 44 and value not in refs:
            refs.append(value)

    components = []
    if vprest is not None:
        for comp in vprest.findall(f"{CTE_NS}Comp"):
            components.append({
                "nome": _text(comp, "xNome"),
                "valor": _text(comp, "vComp"),
            })

    inf_q = []
    if inf_carga is not None:
        for q in inf_carga.findall(f"{CTE_NS}infQ"):
            inf_q.append({
                "unidade": _text(q, "cUnid"),
                "tipo": _text(q, "tpMed"),
                "quantidade": _text(q, "qCarga"),
            })

    obs = []
    compl = root.find(f".//{CTE_NS}compl")
    if compl is not None:
        xcarac = _text(compl, "xCaracAd")
        xcaracser = _text(compl, "xCaracSer")
        xobs = _text(compl, "xObs")
        for value in (xcarac, xcaracser, xobs):
            if value:
                obs.append(value)
        for obs_cont in compl.findall(f"{CTE_NS}ObsCont"):
            campo = str(obs_cont.attrib.get("xCampo") or "").strip()
            texto = _text(obs_cont, "xTexto")
            if texto:
                obs.append(f"{campo}: {texto}" if campo else texto)

    modal_code = _text(ide, "modal")
    modal = {
        "01": "RODOVIÁRIO",
        "02": "AÉREO",
        "03": "AQUAVIÁRIO",
        "04": "FERROVIÁRIO",
        "05": "DUTOVIÁRIO",
        "06": "MULTIMODAL",
    }.get(modal_code, modal_code)

    toma = root.find(f".//{CTE_NS}toma3") or root.find(f".//{CTE_NS}toma4")

    return {
        "numero": _text(ide, "nCT"),
        "serie": _text(ide, "serie"),
        "modelo": modelo,
        "chave": key,
        "cfop": _text(ide, "CFOP"),
        "natureza": _text(ide, "natOp"),
        "data_emissao": _text(ide, "dhEmi"),
        "modal": modal,
        "tp_cte": _text(ide, "tpCTe"),
        "tp_serv": _text(ide, "tpServ"),
        "inicio": f"{_text(ide, 'xMunIni')}/{_text(ide, 'UFIni')}".strip("/"),
        "fim": f"{_text(ide, 'xMunFim')}/{_text(ide, 'UFFim')}".strip("/"),
        "emit": _party(emit),
        "rem": _party(root.find(f".//{CTE_NS}rem")),
        "dest": _party(root.find(f".//{CTE_NS}dest")),
        "exped": _party(root.find(f".//{CTE_NS}exped")),
        "receb": _party(root.find(f".//{CTE_NS}receb")),
        "tomador": _party(toma),
        "vprest": {
            "total": _text(vprest, "vTPrest"),
            "receber": _text(vprest, "vRec"),
            "componentes": components,
        },
        "imposto": {
            "vbc": _text(icms, "vBC"),
            "picms": _text(icms, "pICMS"),
            "vicms": _text(icms, "vICMS"),
            "cst": next(
                (
                    _text(child, "CST")
                    for child in list(icms or [])
                    if _text(child, "CST")
                ),
                _text(icms, "CST"),
            ),
            "vtotaltrib": _text(imp, "vTotTrib"),
        },
        "carga": {
            "produto": _text(inf_carga, "proPred"),
            "valor": _text(inf_carga, "vCarga"),
            "quantidades": inf_q,
        },
        "refs_nfe": refs,
        "obs": obs,
        "qr_code": _text(supl, "qrCodCTe"),
        "protocolo": _text(prot, "nProt"),
        "protocolo_data": _text(prot, "dhRecbto"),
        "status_codigo": _text(prot, "cStat"),
        "status_motivo": _text(prot, "xMotivo"),
    }


def extract_cte_metadata(raw_xml: bytes) -> CteMetadata:
    data = _parse_cte(raw_xml)
    return CteMetadata(
        numero=data["numero"],
        serie=data["serie"],
        chave=data["chave"],
        emitente=data["emit"].get("nome", ""),
        cnpj_emitente=_digits(data["emit"].get("cnpj", "")),
        protocolo=data["protocolo"],
        status_codigo=data["status_codigo"],
        status_motivo=data["status_motivo"],
        modalidade=data["modal"],
        refs_nfe=list(data.get("refs_nfe") or []),
        qr_code=data.get("qr_code") or "",
    )


def referenced_nfe_numbers(raw_xml: bytes) -> list[str]:
    refs = _parse_cte(raw_xml).get("refs_nfe") or []
    numbers = []
    for key in refs:
        d = _digits(key)
        if len(d) == 44:
            number = str(int(d[25:34])) if d[25:34].isdigit() else d[25:34]
            if number not in numbers:
                numbers.append(number)
    return numbers


def _rect(page: fitz.Page, x0: float, y0: float, x1: float, y1: float, fill=None):
    page.draw_rect(
        fitz.Rect(x0, y0, x1, y1),
        color=BLACK,
        fill=fill,
        width=0.6,
        overlay=True,
    )


def _text_box(
    page: fitz.Page,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    value: object,
    size: float = 7.0,
    bold: bool = False,
    align: int = 0,
):
    page.insert_textbox(
        fitz.Rect(x0, y0, x1, y1),
        str(value or ""),
        fontsize=size,
        fontname="Times-Bold" if bold else "Times-Roman",
        color=BLACK,
        align=align,
        lineheight=1.0,
        overlay=True,
    )


def _label_value(page: fitz.Page, rect: fitz.Rect, label: str, value: object):
    _rect(page, rect.x0, rect.y0, rect.x1, rect.y1)
    _text_box(page, rect.x0 + 3, rect.y0 + 2, rect.x1 - 3, rect.y0 + 10, label, 5.0, True)
    _text_box(page, rect.x0 + 3, rect.y0 + 10, rect.x1 - 3, rect.y1 - 2, value, 6.5)


def _party_box(page: fitz.Page, rect: fitz.Rect, title: str, party: dict):
    _rect(page, rect.x0, rect.y0, rect.x1, rect.y1)
    _text_box(page, rect.x0 + 3, rect.y0 + 2, rect.x1 - 3, rect.y0 + 11, title, 5.4, True)
    address = " ".join(
        part for part in [
            party.get("logradouro", ""),
            party.get("numero", ""),
            party.get("bairro", ""),
            f"{party.get('municipio','')}/{party.get('uf','')}".strip("/"),
        ]
        if str(part).strip()
    )
    body = (
        f"{party.get('nome','')}\n"
        f"CNPJ/CPF: {_fmt_tax_id(party.get('cnpj',''))}  IE: {party.get('ie','')}\n"
        f"{address}"
    )
    _text_box(page, rect.x0 + 3, rect.y0 + 12, rect.x1 - 3, rect.y1 - 2, body, 6.0)


def _draw_qr(page: fitz.Page, rect: fitz.Rect, content: str):
    if not content:
        return
    qr = qrcode.QRCode(version=None, box_size=3, border=1)
    qr.add_data(content)
    qr.make(fit=True)
    image = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    bio = io.BytesIO()
    image.save(bio, format="PNG")
    page.insert_image(rect, stream=bio.getvalue(), keep_proportion=True, overlay=True)


def _draw_barcode(page: fitz.Page, x0: float, y0: float, x1: float, y1: float, key: str):
    # Reutiliza o CODE-128C validado no motor DANFE.
    from danfe_generator import _draw_barcode as draw_code128
    draw_code128(page, x0, y0, x1, y1, key)


def _draw_header(page: fitz.Page, data: dict, page_no: int, total_pages: int):
    _rect(page, 20, 20, 575, 138)

    _text_box(page, 26, 25, 255, 45, data["emit"].get("nome", ""), 10, True)
    emit = data["emit"]
    address = " ".join(
        part for part in [
            emit.get("logradouro", ""),
            emit.get("numero", ""),
            emit.get("bairro", ""),
            f"{emit.get('municipio','')}/{emit.get('uf','')}".strip("/"),
            emit.get("cep", ""),
            emit.get("fone", ""),
        ]
        if str(part).strip()
    )
    _text_box(page, 26, 46, 255, 79, address, 6.2)
    _text_box(
        page, 26, 80, 255, 98,
        f"CNPJ: {_fmt_tax_id(emit.get('cnpj',''))}   IE: {emit.get('ie','')}",
        6.2,
    )

    _rect(page, 260, 20, 385, 138)
    _text_box(page, 268, 28, 377, 48, "DACTE", 15, True, 1)
    _text_box(
        page, 266, 50, 379, 73,
        "DOCUMENTO AUXILIAR DO CONHECIMENTO DE TRANSPORTE ELETRÔNICO",
        6.0, False, 1,
    )
    _text_box(page, 268, 82, 377, 102, f"CT-e Nº {data['numero']}", 8.0, True, 1)
    _text_box(page, 268, 102, 377, 120, f"SÉRIE {data['serie']}", 7.0, True, 1)
    _text_box(page, 268, 120, 377, 136, f"FOLHA {page_no}/{total_pages}", 6.5, True, 1)

    _rect(page, 390, 20, 575, 138)
    _draw_barcode(page, 398, 30, 566, 63, data["chave"])
    _text_box(page, 398, 66, 566, 84, _format_key(data["chave"]), 6.0, False, 1)
    _text_box(
        page, 398, 87, 566, 105,
        f"PROTOCOLO: {data['protocolo']} {_fmt_date(data['protocolo_data'])}",
        5.8,
    )
    _text_box(
        page, 398, 107, 566, 123,
        f"STATUS: {data['status_codigo']} {data['status_motivo']}",
        5.4,
    )
    if data.get("qr_code"):
        _draw_qr(page, fitz.Rect(530, 88, 568, 126), data["qr_code"])


def _draw_main_page(page: fitz.Page, data: dict, page_no: int, total_pages: int, refs: list[str]):
    _draw_header(page, data, page_no, total_pages)

    y = 145
    _label_value(page, fitz.Rect(20, y, 190, y + 34), "CFOP - NATUREZA DA PRESTAÇÃO", f"{data['cfop']} - {data['natureza']}")
    _label_value(page, fitz.Rect(190, y, 315, y + 34), "MODAL", data["modal"])
    _label_value(page, fitz.Rect(315, y, 445, y + 34), "INÍCIO DA PRESTAÇÃO", data["inicio"])
    _label_value(page, fitz.Rect(445, y, 575, y + 34), "TÉRMINO DA PRESTAÇÃO", data["fim"])
    y += 38

    _party_box(page, fitz.Rect(20, y, 297, y + 62), "REMETENTE", data["rem"])
    _party_box(page, fitz.Rect(297, y, 575, y + 62), "DESTINATÁRIO", data["dest"])
    y += 66
    _party_box(page, fitz.Rect(20, y, 297, y + 58), "EXPEDIDOR", data["exped"])
    _party_box(page, fitz.Rect(297, y, 575, y + 58), "RECEBEDOR", data["receb"])
    y += 62

    _party_box(page, fitz.Rect(20, y, 575, y + 54), "TOMADOR DO SERVIÇO", data["tomador"])
    y += 58

    _rect(page, 20, y, 575, y + 76)
    _text_box(page, 23, y + 2, 572, y + 12, "COMPONENTES DO VALOR DA PRESTAÇÃO", 5.4, True)
    comps = data["vprest"]["componentes"] or []
    comp_text = " | ".join(
        f"{item.get('nome','')}: R$ {_fmt_money(item.get('valor',''))}"
        for item in comps[:8]
    )
    _text_box(page, 23, y + 14, 430, y + 51, comp_text, 6.0)
    _text_box(
        page, 438, y + 15, 570, y + 35,
        f"VALOR TOTAL: R$ {_fmt_money(data['vprest']['total'])}",
        6.5, True,
    )
    _text_box(
        page, 438, y + 38, 570, y + 57,
        f"VALOR A RECEBER: R$ {_fmt_money(data['vprest']['receber'])}",
        6.5, True,
    )
    y += 80

    _rect(page, 20, y, 575, y + 62)
    _text_box(page, 23, y + 2, 572, y + 12, "INFORMAÇÕES RELATIVAS AO IMPOSTO", 5.4, True)
    tax = data["imposto"]
    tax_text = (
        f"CST: {tax.get('cst','')}   BASE DE CÁLCULO: R$ {_fmt_money(tax.get('vbc',''))}   "
        f"ALÍQUOTA: {tax.get('picms','')}%   ICMS: R$ {_fmt_money(tax.get('vicms',''))}   "
        f"TRIBUTOS: R$ {_fmt_money(tax.get('vtotaltrib',''))}"
    )
    _text_box(page, 23, y + 16, 572, y + 55, tax_text, 6.2)
    y += 66

    _rect(page, 20, y, 575, y + 66)
    _text_box(page, 23, y + 2, 572, y + 12, "INFORMAÇÕES DA CARGA", 5.4, True)
    cargo = data["carga"]
    quantities = " | ".join(
        f"{q.get('tipo','')}: {q.get('quantidade','')}"
        for q in cargo.get("quantidades") or []
    )
    cargo_text = (
        f"PRODUTO PREDOMINANTE: {cargo.get('produto','')}   "
        f"VALOR DA CARGA: R$ {_fmt_money(cargo.get('valor',''))}\n{quantities}"
    )
    _text_box(page, 23, y + 16, 572, y + 60, cargo_text, 6.2)
    y += 70

    _rect(page, 20, y, 575, min(745, y + 112))
    _text_box(page, 23, y + 2, 572, y + 12, "DOCUMENTOS ORIGINÁRIOS - NF-e", 5.4, True)
    ref_lines = []
    for key in refs:
        d = _digits(key)
        nf_num = str(int(d[25:34])) if len(d) == 44 and d[25:34].isdigit() else ""
        ref_lines.append(f"NF {nf_num} - {_format_key(d)}")
    _text_box(page, 23, y + 15, 572, min(742, y + 108), "\n".join(ref_lines), 5.8)
    y = min(749, y + 116)

    _rect(page, 20, y, 575, 804)
    _text_box(page, 23, y + 2, 572, y + 12, "OBSERVAÇÕES", 5.4, True)
    _text_box(page, 23, y + 15, 572, 800, "\n".join(data.get("obs") or []), 5.8)


def generate_dacte_pdf(raw_xml: bytes) -> bytes:
    data = _parse_cte(raw_xml)

    if data.get("status_codigo") and data["status_codigo"] != "100":
        # O DACTE pode ser produzido para conferência, mas deixa a situação explícita.
        data["status_motivo"] = (
            f"{data.get('status_motivo','')} - DOCUMENTO NÃO AUTORIZADO"
        ).strip(" -")

    refs = list(data.get("refs_nfe") or [])
    chunks = [refs[i:i + 8] for i in range(0, len(refs), 8)] or [[]]
    total_pages = len(chunks)

    doc = fitz.open()
    for idx, chunk in enumerate(chunks, start=1):
        page = doc.new_page(width=595.28, height=841.89)
        _draw_main_page(page, data, idx, total_pages, chunk)

    output = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return output


def dacte_file_name(meta: CteMetadata) -> str:
    number = _digits(meta.numero) or "SEM_NUMERO"
    carrier = _safe_name(meta.emitente)
    return f"DACTE_CTE_{number}_{carrier}.pdf"


def cte_output_name(
    meta: CteMetadata,
    linked_nf_numbers: list[str],
    supplier_name: str = "",
) -> str:
    cte_number = _digits(meta.numero) or "SEM_CTE"
    carrier = _safe_name(meta.emitente)
    nfs = [str(x).strip() for x in linked_nf_numbers if str(x).strip()]
    if not nfs:
        nf_label = "SEM_NF"
    elif len(nfs) == 1:
        nf_label = nfs[0]
    else:
        nf_label = f"{nfs[0]} +{len(nfs) - 1}"
    supplier = _safe_name(supplier_name) if supplier_name else "FORNECEDOR"
    return f"{cte_number} - {carrier} - {nf_label} - {supplier}.pdf"
