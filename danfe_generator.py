from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime

import fitz


NFE_NS = "{http://www.portalfiscal.inf.br/nfe}"

PAGE_W = 595.276
PAGE_H = 841.89
LINE_W = 0.185
BLACK = (0, 0, 0)
FONT_REGULAR = "helv"
FONT_BOLD = "hebo"

# Geometria calibrada diretamente pelo DANFE de referência validado pela operação.
# O objetivo é manter o mesmo desenho independentemente do tpImp presente no XML:
# A4 retrato, canhoto superior, traço fino e proporções fixas.
PRODUCT_X = [
    18.43, 65.50, 184.58, 219.66, 237.20, 260.27, 275.04, 310.12,
    362.73, 402.43, 437.50, 467.97, 488.27, 518.73, 539.04, 575.04,
]

CODE128_PATTERNS = [
    "212222","222122","222221","121223","121322","131222","122213","122312","132212","221213",
    "221312","231212","112232","122132","122231","113222","123122","123221","223211","221132",
    "221231","213212","223112","312131","311222","321122","321221","312212","322112","322211",
    "212123","212321","232121","111323","131123","131321","112313","132113","132311","211313",
    "231113","231311","112133","112331","132131","113123","113321","133121","313121","211331",
    "231131","213113","213311","213131","311123","311321","331121","312113","312311","332111",
    "314111","221411","431111","111224","111422","121124","121421","141122","141221","112214",
    "112412","122114","122411","142112","142211","241211","221114","413111","241112","134111",
    "111242","121142","121241","114212","124112","124211","411212","421112","421211","212141",
    "214121","412121","111143","111341","131141","114113","114311","411113","411311","113141",
    "114131","311141","411131","211412","211214","211232","2331112",
]


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


def _node_text(parent: ET.Element | None, tag: str) -> str:
    if parent is None:
        return ""
    node = parent.find(f"{NFE_NS}{tag}")
    return (node.text or "").strip() if node is not None and node.text else ""


def _digits(value: object) -> str:
    return re.sub(r"\D+", "", str(value or ""))


def _safe_name(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]+', " ", value or "")
    value = re.sub(r"\s+", " ", value).strip()
    return value[:90] or "EMITENTE"


def _format_cnpj_cpf(value: str) -> str:
    digits = _digits(value)
    if len(digits) == 14:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}/{digits[8:12]}-{digits[12:]}"
    if len(digits) == 11:
        return f"{digits[:3]}.{digits[3:6]}.{digits[6:9]}-{digits[9:]}"
    return str(value or "")


def _format_cep(value: str) -> str:
    digits = _digits(value)
    if len(digits) == 8:
        return f"{digits[:5]}-{digits[5:]}"
    return str(value or "")


def _format_date(value: str) -> str:
    if not value:
        return ""
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except Exception:
        match = re.match(r"(\d{4})-(\d{2})-(\d{2})", value)
        if match:
            return f"{match.group(3)}/{match.group(2)}/{match.group(1)}"
        return value


def _format_time(value: str) -> str:
    if not value:
        return ""
    match = re.search(r"T(\d{2}:\d{2}:\d{2})", value)
    return match.group(1) if match else ""


def _format_number(value: object, decimals: int = 2) -> str:
    try:
        number = float(str(value or "0").replace(",", "."))
    except Exception:
        number = 0.0
    formatted = f"{number:,.{decimals}f}"
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def _format_nf9(value: str) -> str:
    try:
        return f"{int(value):09d}"
    except Exception:
        return str(value or "")


def _freight_label(value: str) -> str:
    return {
        "0": "0-EMITENTE",
        "1": "1-DESTINATÁRIO",
        "2": "2-TERCEIROS",
        "3": "3-PRÓPRIO REM.",
        "4": "4-PRÓPRIO DEST.",
        "9": "9-SEM FRETE",
    }.get(str(value or ""), str(value or ""))


def _parse_nfe(raw_xml: bytes) -> dict:
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

    if ide is None or emit is None or dest is None or inf_nfe is None:
        raise ValueError("O XML não contém a estrutura mínima de uma NF-e.")

    modelo = _node_text(ide, "mod")
    if modelo != "55":
        raise ValueError(
            f"O XML é modelo {modelo or '?'}; esta ferramenta gera DANFE de NF-e modelo 55."
        )

    emit_addr = emit.find(f"{NFE_NS}enderEmit")
    dest_addr = dest.find(f"{NFE_NS}enderDest")
    total = root.find(f".//{NFE_NS}total/{NFE_NS}ICMSTot")
    issqn = root.find(f".//{NFE_NS}total/{NFE_NS}ISSQNtot")
    prot = root.find(f".//{NFE_NS}protNFe/{NFE_NS}infProt")
    transp = root.find(f".//{NFE_NS}transp")
    carrier = transp.find(f"{NFE_NS}transporta") if transp is not None else None
    volume = transp.find(f"{NFE_NS}vol") if transp is not None else None
    billing = root.find(f".//{NFE_NS}cobr")
    fat = billing.find(f"{NFE_NS}fat") if billing is not None else None
    dups = billing.findall(f"{NFE_NS}dup") if billing is not None else []
    payment = root.find(f".//{NFE_NS}pag/{NFE_NS}detPag")
    inf_adic = root.find(f".//{NFE_NS}infAdic")

    key = (inf_nfe.attrib.get("Id") or "").strip()
    if key.upper().startswith("NFE"):
        key = key[3:]
    key = _digits(key)

    items = []
    for det in root.findall(f".//{NFE_NS}det"):
        prod = det.find(f"{NFE_NS}prod")
        imposto = det.find(f"{NFE_NS}imposto")
        icms = imposto.find(f"{NFE_NS}ICMS") if imposto is not None else None
        icms_node = list(icms)[0] if icms is not None and len(list(icms)) else None
        ipi = imposto.find(f"{NFE_NS}IPI") if imposto is not None else None
        ipi_node = None
        if ipi is not None:
            for child in list(ipi):
                if child.tag.split("}")[-1] in {"IPITrib", "IPINT"}:
                    ipi_node = child
                    break

        origem = _node_text(icms_node, "orig")
        cst = _node_text(icms_node, "CST") or _node_text(icms_node, "CSOSN")
        cst_full = f"{origem}{cst}" if cst else origem

        items.append(
            {
                "code": _node_text(prod, "cProd"),
                "desc": _node_text(prod, "xProd"),
                "inf_ad_prod": _node_text(det, "infAdProd"),
                "ncm": _node_text(prod, "NCM"),
                "cst": cst_full,
                "cfop": _node_text(prod, "CFOP"),
                "un": _node_text(prod, "uCom"),
                "qty": _node_text(prod, "qCom"),
                "unit": _node_text(prod, "vUnCom"),
                "total": _node_text(prod, "vProd"),
                "bc": _node_text(icms_node, "vBC"),
                "vicms": _node_text(icms_node, "vICMS"),
                "vipi": _node_text(ipi_node, "vIPI"),
                "picms": _node_text(icms_node, "pICMS"),
                "pipi": _node_text(ipi_node, "pIPI"),
                "discount": _node_text(prod, "vDesc"),
            }
        )

    return {
        "nf": _node_text(ide, "nNF"),
        "serie": _node_text(ide, "serie"),
        "tpNF": _node_text(ide, "tpNF"),
        "natOp": _node_text(ide, "natOp"),
        "dhEmi": _node_text(ide, "dhEmi") or _node_text(ide, "dEmi"),
        "dhSaiEnt": _node_text(ide, "dhSaiEnt") or _node_text(ide, "dSaiEnt"),
        "tpAmb": _node_text(ide, "tpAmb"),
        "emitente": _node_text(emit, "xNome"),
        "emitente_cnpj": _format_cnpj_cpf(
            _node_text(emit, "CNPJ") or _node_text(emit, "CPF")
        ),
        "emitente_ie": _node_text(emit, "IE"),
        "emitente_iest": _node_text(emit, "IEST"),
        "emitente_im": _node_text(emit, "IM"),
        "emitente_end": {
            "logradouro": _node_text(emit_addr, "xLgr"),
            "numero": _node_text(emit_addr, "nro"),
            "complemento": _node_text(emit_addr, "xCpl"),
            "bairro": _node_text(emit_addr, "xBairro"),
            "cep": _format_cep(_node_text(emit_addr, "CEP")),
            "municipio": _node_text(emit_addr, "xMun"),
            "uf": _node_text(emit_addr, "UF"),
            "fone": _node_text(emit_addr, "fone"),
        },
        "destinatario": _node_text(dest, "xNome"),
        "destinatario_cnpj": _format_cnpj_cpf(
            _node_text(dest, "CNPJ") or _node_text(dest, "CPF")
        ),
        "destinatario_ie": _node_text(dest, "IE"),
        "destinatario_end": {
            "logradouro": _node_text(dest_addr, "xLgr"),
            "numero": _node_text(dest_addr, "nro"),
            "complemento": _node_text(dest_addr, "xCpl"),
            "bairro": _node_text(dest_addr, "xBairro"),
            "cep": _format_cep(_node_text(dest_addr, "CEP")),
            "municipio": _node_text(dest_addr, "xMun"),
            "uf": _node_text(dest_addr, "UF"),
            "fone": _node_text(dest_addr, "fone"),
        },
        "key": key,
        "protocolo": _node_text(prot, "nProt"),
        "protocolo_data": _node_text(prot, "dhRecbto"),
        "status_codigo": _node_text(prot, "cStat"),
        "status_motivo": _node_text(prot, "xMotivo"),
        "totais": {
            tag: _node_text(total, tag)
            for tag in [
                "vBC",
                "vICMS",
                "vBCST",
                "vST",
                "vProd",
                "vFrete",
                "vSeg",
                "vDesc",
                "vOutro",
                "vIPI",
                "vNF",
            ]
        },
        "issqn": {
            tag: _node_text(issqn, tag) for tag in ["vServ", "vBC", "vISS"]
        },
        "transportador": {
            "nome": _node_text(carrier, "xNome"),
            "cnpj": _format_cnpj_cpf(
                _node_text(carrier, "CNPJ") or _node_text(carrier, "CPF")
            ),
            "ie": _node_text(carrier, "IE"),
            "endereco": _node_text(carrier, "xEnder"),
            "municipio": _node_text(carrier, "xMun"),
            "uf": _node_text(carrier, "UF"),
            "frete": _node_text(transp, "modFrete"),
        },
        "volume": {
            "quantidade": _node_text(volume, "qVol"),
            "especie": _node_text(volume, "esp"),
            "marca": _node_text(volume, "marca"),
            "numeracao": _node_text(volume, "nVol"),
            "peso_bruto": _node_text(volume, "pesoB"),
            "peso_liquido": _node_text(volume, "pesoL"),
        },
        "fatura": {
            "numero": _node_text(fat, "nFat"),
            "original": _node_text(fat, "vOrig"),
            "desconto": _node_text(fat, "vDesc"),
            "liquido": _node_text(fat, "vLiq"),
        },
        "duplicatas": [
            {
                "numero": _node_text(dup, "nDup"),
                "vencimento": _node_text(dup, "dVenc"),
                "valor": _node_text(dup, "vDup"),
            }
            for dup in dups
        ],
        "pagamento": {
            "forma": _node_text(payment, "tPag"),
            "valor": _node_text(payment, "vPag"),
        },
        "items": items,
        "informacoes": _node_text(inf_adic, "infCpl"),
    }


def extract_danfe_metadata(raw_xml: bytes) -> DanfeMetadata:
    data = _parse_nfe(raw_xml)
    return DanfeMetadata(
        numero_nf=data["nf"],
        serie=data["serie"],
        chave=data["key"],
        emitente=data["emitente"],
        cnpj_emitente=_digits(data["emitente_cnpj"]),
        destinatario=data["destinatario"],
        data_emissao=data["dhEmi"],
        protocolo=data["protocolo"],
        status_codigo=data["status_codigo"],
        status_motivo=data["status_motivo"],
    )


def extract_nfe_processing_data(raw_xml: bytes) -> dict:
    """Extrai os dados fiscais usados pelo fluxo operacional de NF.

    O XML é tratado como fonte prioritária para identidade fiscal e duplicatas.
    A natureza fiscal (natOp) é mantida separada da natureza interna operacional.
    """
    data = _parse_nfe(raw_xml)

    due_dates = []
    for dup in data.get("duplicatas") or []:
        raw_due = str(dup.get("vencimento") or "").strip()
        if not raw_due:
            continue
        try:
            due_dates.append(datetime.strptime(raw_due[:10], "%Y-%m-%d").date())
        except Exception:
            continue

    due_dates = sorted(set(due_dates))
    return {
        "numero_nf": str(data.get("nf") or "").strip(),
        "serie": str(data.get("serie") or "").strip(),
        "chave_nfe": _digits(data.get("key")),
        "cnpj_fornecedor": _digits(data.get("emitente_cnpj")),
        "fornecedor_lido": str(data.get("emitente") or "").strip(),
        "data_emissao": _format_date(str(data.get("dhEmi") or "")),
        "vencimento": due_dates[0] if due_dates else None,
        "vencimentos": due_dates,
        "natureza_fiscal": str(data.get("natOp") or "").strip(),
        "protocolo": str(data.get("protocolo") or "").strip(),
        "status_codigo": str(data.get("status_codigo") or "").strip(),
        "status_motivo": str(data.get("status_motivo") or "").strip(),
    }


def _draw_line(page: fitz.Page, x0: float, y0: float, x1: float, y1: float, width: float = LINE_W):
    page.draw_line(
        fitz.Point(x0, y0),
        fitz.Point(x1, y1),
        color=BLACK,
        width=width,
        overlay=True,
    )


def _draw_rect(page: fitz.Page, x0: float, y0: float, x1: float, y1: float):
    page.draw_rect(
        fitz.Rect(x0, y0, x1, y1),
        color=BLACK,
        fill=None,
        width=LINE_W,
        overlay=True,
    )


def _text_width(value: str, size: float, bold: bool = False) -> float:
    return fitz.get_text_length(
        str(value or ""),
        fontname=FONT_BOLD if bold else FONT_REGULAR,
        fontsize=size,
    )


def _draw_text(
    page: fitz.Page,
    x: float,
    y: float,
    value: object,
    size: float = 6.321,
    bold: bool = False,
    align: str = "left",
    x1: float | None = None,
):
    value = str(value or "")
    font = FONT_BOLD if bold else FONT_REGULAR
    if x1 is not None and align != "left":
        width = _text_width(value, size, bold)
        if align == "center":
            x = x + (x1 - x - width) / 2
        elif align == "right":
            x = x1 - width

    page.insert_text(
        (x, y),
        value,
        fontsize=size,
        fontname=font,
        color=BLACK,
        overlay=True,
    )


def _fit_text_size(
    value: object,
    max_width: float,
    max_size: float,
    min_size: float = 4.4,
    bold: bool = False,
) -> float:
    text = str(value or "")
    size = max_size
    while size > min_size and _text_width(text, size, bold) > max_width:
        size -= 0.2
    return max(min_size, size)


def _draw_fit_text(
    page: fitz.Page,
    x0: float,
    y: float,
    x1: float,
    value: object,
    max_size: float = 6.321,
    min_size: float = 4.4,
    bold: bool = False,
    align: str = "left",
):
    size = _fit_text_size(
        value,
        max(1.0, x1 - x0),
        max_size,
        min_size,
        bold,
    )
    _draw_text(page, x0, y, value, size, bold, align, x1)


def _wrap_lines(
    value: str,
    max_width: float,
    size: float,
    bold: bool = False,
    max_lines: int | None = None,
) -> list[str]:
    words = str(value or "").split()
    font = FONT_BOLD if bold else FONT_REGULAR
    lines: list[str] = []
    current = ""

    for word in words:
        candidate = word if not current else f"{current} {word}"
        if (
            fitz.get_text_length(candidate, fontname=font, fontsize=size)
            <= max_width
        ):
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
            if max_lines and len(lines) >= max_lines - 1:
                break

    if current and (not max_lines or len(lines) < max_lines):
        lines.append(current)

    return lines


def _draw_wrapped(
    page: fitz.Page,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    value: str,
    size: float,
    bold: bool = False,
    align: str = "left",
    leading: float | None = None,
    max_lines: int | None = None,
):
    lines = _wrap_lines(value, x1 - x0, size, bold, max_lines)
    leading = leading or size * 1.08
    y = y0 + size

    for row in lines:
        if y > y1:
            break
        _draw_text(page, x0, y, row, size, bold, align, x1)
        y += leading


def _label(page: fitz.Page, x: float, y: float, value: str):
    _draw_text(page, x, y, value, 5.418, True)


def _code128_values(digits: str) -> list[int]:
    digits = _digits(digits)
    if len(digits) % 2:
        digits = f"0{digits}"

    values = [105]
    values.extend(int(digits[i : i + 2]) for i in range(0, len(digits), 2))
    checksum = (values[0] + sum(value * idx for idx, value in enumerate(values[1:], 1))) % 103
    return [*values, checksum, 106]


def _draw_barcode(
    page: fitz.Page,
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    key: str,
):
    values = _code128_values(key)
    patterns = [CODE128_PATTERNS[value] for value in values]
    total_modules = sum(sum(int(char) for char in pattern) for pattern in patterns)
    module = (x1 - x0) / total_modules
    cursor = x0

    for pattern in patterns:
        black = True
        for char in pattern:
            width = int(char) * module
            if black:
                page.draw_rect(
                    fitz.Rect(cursor, y0, cursor + width, y1),
                    color=None,
                    fill=BLACK,
                    overlay=True,
                )
            cursor += width
            black = not black


def _draw_header(page: fitz.Page, data: dict, page_no: int, total_pages: int):
    # Canhoto superior
    _draw_rect(page, 18.43, 19.46, 480.89, 28.69)
    _draw_rect(page, 18.43, 27.77, 111.66, 53.62)
    _draw_rect(page, 110.73, 27.77, 479.97, 53.62)
    _draw_rect(page, 479.97, 19.46, 575.04, 53.62)

    receipt = (
        f"RECEBEMOS DE {data['emitente']} OS PRODUTOS CONSTANTES "
        "DA NOTA FISCAL INDICADA AO LADO"
    )
    _draw_text(page, 20.27, 25.20, receipt, 5.418)
    _label(page, 20.27, 36.32, "DATA DE RECEBIMENTO")
    _label(page, 112.58, 36.32, "IDENTIFICAÇÃO E ASSINATURA DO RECEBEDOR")
    _draw_text(page, 518.73, 27.09, "NF-e", 5.418, True, "center", 536.0)
    _draw_text(page, 489.20, 36.52, f"N. {_format_nf9(data['nf'])}", 6.321)
    _draw_text(page, 489.20, 45.75, f"SÉRIE {data['serie']}", 6.321)

    # Cabeçalho principal
    _draw_rect(page, 18.43, 58.23, 249.20, 145.92)
    _draw_rect(page, 247.35, 58.23, 342.43, 145.92)
    _draw_rect(page, 341.50, 58.23, 575.04, 100.69)
    _draw_rect(page, 341.50, 88.69, 575.04, 121.00)
    _draw_rect(page, 341.50, 116.39, 575.04, 145.92)

    _draw_text(page, 20.0, 68.80, "Identificação do emitente", 8.58, True, "center", 247.5)
    _draw_wrapped(
        page,
        22,
        71.5,
        245,
        91.5,
        data["emitente"],
        8.58,
        True,
        "center",
        9.2,
        2,
    )

    address = data["emitente_end"]
    address_lines = [
        f"{address['logradouro']}, {address['numero']}".strip(", "),
    ]
    if address["complemento"]:
        address_lines.append(f"Complemento: {address['complemento']}")
    address_lines.extend(
        [
            f"{address['bairro']} Cep:{address['cep']}".strip(),
            f"{address['municipio']}/{address['uf']}".strip("/"),
        ]
    )
    if address["fone"]:
        address_lines.append(f"Fone: {address['fone']}")

    y = 98.0
    for value in address_lines[:5]:
        _draw_text(page, 22, y, value, 5.418, True, "center", 247.0)
        y += 9.23

    _draw_text(page, 272.27, 73.10, "DANFE", 13.26, True, "center", 317.92)
    _draw_text(page, 256.58, 80.63, "DOCUMENTO AUXILIAR DA", 5.418, False, "center", 327.88)
    _draw_text(page, 256.58, 89.86, "NOTA FISCAL ELETRÔNICA", 5.418, False, "center", 327.88)
    _draw_text(page, 263.96, 99.29, "0-ENTRADA", 6.321)
    _draw_text(page, 263.96, 108.52, "1-SAÍDA", 6.321)
    _draw_rect(page, 309.20, 91.46, 318.43, 107.15)
    _draw_text(page, 309.2, 102.79, data["tpNF"] or "1", 5.418, True, "center", 318.43)
    _draw_text(page, 253.81, 122.56, f"N. {_format_nf9(data['nf'])}", 7.224, True)
    _draw_text(page, 253.81, 131.79, f"SÉRIE {data['serie']}", 7.224, True)
    _draw_text(page, 253.81, 141.02, f"FOLHA {page_no:02d}/{total_pages:02d}", 7.224, True)

    _draw_barcode(page, 359.96, 60.54, 557.40, 85.92, data["key"])
    _draw_text(page, 346.12, 99.78, "CHAVE DE ACESSO DA NF-E", 8.58, True)
    grouped_key = " ".join(data["key"][i : i + 4] for i in range(0, len(data["key"]), 4))
    _draw_text(page, 346.12, 109.01, grouped_key, 8.58, True)
    _draw_text(
        page,
        346.12,
        129.32,
        "Consulta de autenticidade no portal nacional da NF-e",
        8.58,
    )
    _draw_text(
        page,
        346.12,
        138.55,
        "www.nfe.fazenda.gov.br/portal ou no site da SEFAZ Autorizada",
        8.58,
    )

    _draw_rect(page, 18.43, 147.77, 575.04, 169.00)
    _draw_line(page, 341.50, 147.77, 341.50, 169.00)
    _label(page, 20.27, 157.25, "NATUREZA DA OPERAÇÃO")
    _label(page, 343.35, 157.25, "PROTOCOLO DE AUTORIZAÇÃO DE USO")
    _draw_fit_text(page, 20.27, 166.67, 339.0, data["natOp"], 6.321, 4.5)

    protocol = data["protocolo"]
    if data["protocolo_data"]:
        protocol = f"{protocol} - " if protocol else ""
        protocol += _format_date(data["protocolo_data"])
        protocol_time = _format_time(data["protocolo_data"])
        if protocol_time:
            protocol += f" {protocol_time}"
    _draw_fit_text(page, 343.35, 166.67, 573.0, protocol, 5.9, 4.5)

    _draw_rect(page, 18.43, 170.85, 575.04, 192.08)
    _draw_line(page, 203.04, 170.85, 203.04, 192.08)
    _draw_line(page, 387.66, 170.85, 387.66, 192.08)
    _label(page, 20.27, 179.05, "INSCRIÇÃO ESTADUAL")
    _label(page, 204.88, 179.05, "INSC.ESTADUAL DO SUBST.TRIB.")
    _label(page, 389.50, 179.05, "CNPJ/CPF")
    _draw_fit_text(page, 20.27, 186.98, 200.5, data["emitente_ie"], 6.321)
    _draw_fit_text(page, 204.88, 186.98, 385.0, data["emitente_iest"], 6.321)
    _draw_fit_text(page, 389.50, 186.98, 573.0, data["emitente_cnpj"], 6.321)


def _draw_recipient(page: fitz.Page, data: dict):
    _label(page, 20.27, 200.63, "DESTINATARIO/REMETENTE")

    _draw_rect(page, 18.43, 201.31, 575.04, 219.77)
    _draw_line(page, 276.89, 201.31, 276.89, 219.77)
    _draw_line(page, 481.81, 201.31, 481.81, 219.77)
    _label(page, 20.27, 209.86, "NOME/RAZÃO SOCIAL")
    _label(page, 279.66, 209.86, "CNPJ/CPF")
    _label(page, 483.66, 209.86, "DATA DE EMISSÃO")
    _draw_fit_text(page, 20.27, 217.92, 274.5, data["destinatario"], 6.321)
    _draw_fit_text(page, 279.66, 217.92, 479.0, data["destinatario_cnpj"], 6.321)
    _draw_fit_text(page, 483.66, 217.92, 573.0, _format_date(data["dhEmi"]), 6.321)

    _draw_rect(page, 18.43, 219.77, 575.04, 238.23)
    _draw_line(page, 230.73, 219.77, 230.73, 238.23)
    _draw_line(page, 369.20, 219.77, 369.20, 238.23)
    _draw_line(page, 481.81, 219.77, 481.81, 238.23)
    _label(page, 20.27, 227.40, "ENDEREÇO")
    _label(page, 232.58, 227.40, "BAIRRO/DISTRITO")
    _label(page, 371.04, 227.40, "CEP")
    _label(page, 483.66, 227.40, "DATA ENTRADA/SAÍDA")

    address = data["destinatario_end"]
    full_address = ", ".join(
        value
        for value in [
            address["logradouro"],
            address["numero"],
            address["complemento"],
        ]
        if value
    )
    _draw_fit_text(page, 20.27, 235.46, 228.5, full_address, 6.0, 4.4)
    _draw_fit_text(page, 232.58, 235.46, 366.0, address["bairro"], 6.321, 4.4)
    _draw_fit_text(page, 371.04, 235.46, 479.0, address["cep"], 6.321, 4.4)
    _draw_text(page, 483.66, 235.46, _format_date(data["dhSaiEnt"]), 6.321)

    _draw_rect(page, 18.43, 237.31, 575.04, 256.69)
    for x in [156.89, 253.81, 332.27, 481.81]:
        _draw_line(page, x, 237.31, x, 256.69)

    _label(page, 20.27, 246.79, "MUNICIPIO")
    _label(page, 158.73, 246.79, "FONE/FAX")
    _label(page, 255.66, 246.79, "UF")
    _label(page, 334.12, 246.79, "INSCRIÇÃO ESTADUAL")
    _label(page, 482.73, 244.94, "HORA ENTRADA/SAÍDA")
    _draw_text(page, 20.27, 254.85, address["municipio"], 6.321)
    _draw_text(page, 158.73, 254.85, address["fone"], 6.0)
    _draw_text(page, 255.66, 254.85, address["uf"], 6.321)
    _draw_text(page, 334.12, 254.85, data["destinatario_ie"], 6.321)
    _draw_text(page, 482.73, 252.08, _format_time(data["dhSaiEnt"]), 6.321)


def _draw_billing(page: fitz.Page, data: dict):
    _label(page, 20.27, 263.40, "FATURA")
    columns = [18.43, 80.27, 142.12, 203.96, 265.81, 327.66, 389.50, 451.35, 513.20, 575.04]
    for left, right in zip(columns, columns[1:]):
        _draw_rect(page, left, 264.08, right, 292.69)

    if data["duplicatas"]:
        for idx, duplicate in enumerate(data["duplicatas"][:9]):
            _draw_text(
                page,
                columns[idx] + 1.8,
                273.0,
                f"{duplicate['numero']} {_format_date(duplicate['vencimento'])}",
                5.3,
            )
            _draw_text(
                page,
                columns[idx] + 1.8,
                285.0,
                _format_number(duplicate["valor"]),
                5.8,
            )
        return

    if data["fatura"]["numero"] or data["fatura"]["liquido"]:
        values = [
            f"Nº {data['fatura']['numero']}",
            f"ORIG {_format_number(data['fatura']['original'])}",
            f"DESC {_format_number(data['fatura']['desconto'])}",
            f"LIQ {_format_number(data['fatura']['liquido'])}",
        ]
        for idx, value in enumerate(values):
            _draw_text(page, columns[idx] + 1.8, 279.0, value, 5.5)
        return

    if data["pagamento"]["forma"] or data["pagamento"]["valor"]:
        _draw_text(page, 20.27, 272.83, f"Forma {data['pagamento']['forma']}", 6.321)
        _draw_text(page, 20.27, 287.60, _format_number(data["pagamento"]["valor"]), 6.321)


def _draw_taxes(page: fitz.Page, data: dict):
    _label(page, 20.27, 302.17, "CALCULO DO IMPOSTO")

    row1 = [18.43, 129.19, 202.12, 350.73, 470.73, 575.04]
    labels1 = [
        "BASE DE CALCULO DO ICMS",
        "VALOR DO ICMS",
        "BASE DE CALCULO DO ICMS SUBSTITUIÇÃO",
        "VALOR DO ICMS SUBSTITUIÇÃO",
        "VALOR TOTAL DOS PRODUTOS",
    ]
    values1 = [
        data["totais"]["vBC"],
        data["totais"]["vICMS"],
        data["totais"]["vBCST"],
        data["totais"]["vST"],
        data["totais"]["vProd"],
    ]

    for idx in range(5):
        _draw_rect(page, row1[idx], 302.85, row1[idx + 1], 324.08)
        _label(page, row1[idx] + 1.84, 311.05, labels1[idx])
        _draw_text(
            page,
            row1[idx] + 2,
            321.30,
            _format_number(values1[idx]),
            6.321,
            False,
            "right",
            row1[idx + 1] - 2,
        )

    row2 = [18.43, 110.73, 193.81, 286.12, 400.58, 479.97, 575.04]
    labels2 = [
        "VALOR DO FRETE",
        "VALOR DO SEGURO",
        "DESCONTO",
        "OUTRAS DESPESAS ACESSÓRIAS",
        "VALOR DO IPI",
        "VALOR TOTAL DA NOTA",
    ]
    values2 = [
        data["totais"]["vFrete"],
        data["totais"]["vSeg"],
        data["totais"]["vDesc"],
        data["totais"]["vOutro"],
        data["totais"]["vIPI"],
        data["totais"]["vNF"],
    ]

    for idx in range(6):
        _draw_rect(page, row2[idx], 324.08, row2[idx + 1], 345.31)
        _label(page, row2[idx] + 1.84, 332.28, labels2[idx])
        _draw_text(
            page,
            row2[idx] + 2,
            342.55,
            _format_number(values2[idx]),
            6.321,
            False,
            "right",
            row2[idx + 1] - 2,
        )


def _draw_shipping(page: fitz.Page, data: dict):
    _label(page, 20.27, 354.00, "TRANSPORTADOR/VOLUMES TRANSPORTADOS")
    carrier = data["transportador"]
    volume = data["volume"]

    row1 = [18.43, 244.58, 309.20, 359.96, 433.81, 489.20, 575.04]
    labels1 = ["RAZÃO SOCIAL", "FRETE POR CONTA", "CÓDIGO ANTT", "PLACA DO VEÍCULO", "UF", "CNPJ/CPF"]
    values1 = [
        carrier["nome"],
        _freight_label(carrier["frete"]),
        "",
        "",
        carrier["uf"],
        carrier["cnpj"],
    ]
    for idx in range(6):
        _draw_rect(page, row1[idx], 354.54, row1[idx + 1], 375.77)
        _label(page, row1[idx] + 1.84, 362.74, labels1[idx])
        _draw_fit_text(
            page,
            row1[idx] + 1.84,
            372.08,
            row1[idx + 1] - 1.84,
            values1[idx],
            5.9,
            4.2,
        )

    row2 = [18.43, 239.96, 332.27, 424.58, 575.04]
    labels2 = ["ENDEREÇO", "MUNICIPIO", "UF", "INSCRIÇÃO ESTADUAL"]
    values2 = [carrier["endereco"], carrier["municipio"], carrier["uf"], carrier["ie"]]
    for idx in range(4):
        _draw_rect(page, row2[idx], 374.85, row2[idx + 1], 397.00)
        _label(page, row2[idx] + 1.84, 383.05, labels2[idx])
        _draw_fit_text(
            page,
            row2[idx] + 1.84,
            392.39,
            row2[idx + 1] - 1.84,
            values2[idx],
            5.9,
            4.2,
        )

    row3 = [18.43, 110.73, 203.04, 295.35, 387.66, 479.97, 575.04]
    labels3 = ["QUANTIDADE", "ESPECIE", "MARCA", "NUMERAÇÃO", "PESO BRUTO", "PESO LIQUIDO"]
    values3 = [
        volume["quantidade"],
        volume["especie"],
        volume["marca"],
        volume["numeracao"],
        _format_number(volume["peso_bruto"], 3),
        _format_number(volume["peso_liquido"], 3),
    ]
    for idx in range(6):
        _draw_rect(page, row3[idx], 396.08, row3[idx + 1], 418.23)
        _label(page, row3[idx] + 1.84, 404.28, labels3[idx])
        _draw_text(page, row3[idx] + 1.84, 414.54, values3[idx], 6.321)


def _product_description(item: dict) -> str:
    parts = [
        str(item.get("desc") or "").strip(),
        str(item.get("inf_ad_prod") or "").strip(),
    ]
    return " ".join(part for part in parts if part)


def _product_row_height(item: dict) -> float:
    lines = _wrap_lines(
        _product_description(item),
        PRODUCT_X[2] - PRODUCT_X[1] - 4.0,
        5.45,
        False,
        10,
    )
    # Espaço real entre linhas e entre itens. Evita que o separador atravesse
    # descrição e valores, problema visível nas primeiras amostras geradas.
    return max(15.0, len(lines) * 6.15 + 6.0)


def _split_products(items: list[dict]) -> tuple[list[list[dict]], list[list[float]]]:
    if not items:
        return [[]], [[]]

    pages: list[list[dict]] = []
    heights_pages: list[list[float]] = []

    first_capacity = 643.0 - 445.44
    continuation_capacity = 812.0 - 219.0
    current: list[dict] = []
    heights: list[float] = []
    used = 0.0
    capacity = first_capacity

    for item in items:
        height = _product_row_height(item)
        if current and used + height > capacity:
            pages.append(current)
            heights_pages.append(heights)
            current = []
            heights = []
            used = 0.0
            capacity = continuation_capacity

        current.append(item)
        heights.append(height)
        used += height

    pages.append(current)
    heights_pages.append(heights)
    return pages, heights_pages


def _draw_product_table(
    page: fitz.Page,
    items: list[dict],
    heights: list[float],
    top: float,
    bottom: float,
    title_y: float,
    header_y: float,
    data_y: float,
):
    _label(page, 20.27, title_y, "DADOS DO PRODUTO / SERVIÇO")

    for idx in range(len(PRODUCT_X) - 1):
        _draw_rect(page, PRODUCT_X[idx], top, PRODUCT_X[idx + 1], bottom)

    labels = [
        "COD. PROD",
        "DESCRIÇÃO DO PROD./SERV.",
        "NCM/SH",
        "CST",
        "CFOP",
        "UN",
        "QUANT.",
        "V.UNITARIO",
        "V.TOTAL",
        "BC.ICMS",
        "V.ICMS",
        "V.IPI",
        "A.ICMS",
        "A.IPI",
        "VLR.DESC",
    ]
    for idx, value in enumerate(labels):
        _label(page, PRODUCT_X[idx] + 1.84, header_y, value)

    row_top = data_y - 5.2
    for row_idx, item in enumerate(items):
        row_height = heights[row_idx]
        baseline = row_top + 6.0

        description_lines = _wrap_lines(
            _product_description(item),
            PRODUCT_X[2] - PRODUCT_X[1] - 4.0,
            5.45,
            False,
            10,
        )

        values = [
            item["code"],
            _product_description(item),
            item["ncm"],
            item["cst"],
            item["cfop"],
            item["un"],
            _format_number(item["qty"], 4),
            _format_number(item["unit"], 6),
            _format_number(item["total"], 2),
            _format_number(item["bc"], 2),
            _format_number(item["vicms"], 2),
            _format_number(item["vipi"], 2),
            f"{_format_number(item['picms'], 2)}%" if item["picms"] else "0,00%",
            f"{_format_number(item['pipi'], 2)}%" if item["pipi"] else "0,00%",
            _format_number(item["discount"], 2),
        ]

        for idx, value in enumerate(values):
            if idx == 1:
                line_y = baseline
                for desc_line in description_lines:
                    _draw_text(
                        page,
                        PRODUCT_X[idx] + 1.84,
                        line_y,
                        desc_line,
                        5.45,
                    )
                    line_y += 6.15
            else:
                align = "right" if idx >= 6 else "left"
                max_size = 5.55 if idx >= 6 else 5.45
                _draw_fit_text(
                    page,
                    PRODUCT_X[idx] + 1.5,
                    baseline,
                    PRODUCT_X[idx + 1] - 1.5,
                    value,
                    max_size,
                    4.15,
                    False,
                    align,
                )

        row_bottom = row_top + row_height
        if row_idx < len(items) - 1:
            # Separador fino e colocado de fato ENTRE as linhas. Nas versões
            # anteriores os traços passavam sobre valores e descrições.
            cursor = 18.8
            while cursor < 574.5:
                _draw_line(
                    page,
                    cursor,
                    row_bottom,
                    min(cursor + 1.35, 574.5),
                    row_bottom,
                    0.12,
                )
                cursor += 3.7

        row_top = row_bottom


def _draw_issqn_and_additional(page: fitz.Page, data: dict):
    _label(page, 20.27, 653.87, "CALCULO DO ISSQN")
    columns = [18.43, 156.89, 295.35, 433.81, 575.04]
    labels = [
        "INSCRIÇÃO MUNICIPAL",
        "VALOR TOTAL DOS SERVIÇOS",
        "BASE DE CÁLCULO DO ISSQN",
        "VALOR DO ISSQN",
    ]
    values = [
        data.get("emitente_im") or "",
        data["issqn"]["vServ"],
        data["issqn"]["vBC"],
        data["issqn"]["vISS"],
    ]

    for idx in range(4):
        _draw_rect(page, columns[idx], 654.54, columns[idx + 1], 675.77)
        _label(page, columns[idx] + 1.84, 662.74, labels[idx])

        if idx == 0:
            if values[idx]:
                _draw_fit_text(
                    page,
                    columns[idx] + 1.84,
                    672.0,
                    columns[idx + 1] - 1.84,
                    values[idx],
                    6.321,
                    4.5,
                )
        elif values[idx]:
            try:
                numeric = float(values[idx] or 0)
            except Exception:
                numeric = 0.0
            if numeric != 0:
                _draw_text(
                    page,
                    columns[idx] + 1.84,
                    672.0,
                    _format_number(values[idx]),
                    6.321,
                )

    _label(page, 20.27, 684.33, "DADOS ADICIONAIS")
    _draw_rect(page, 18.43, 685.00, 342.43, 817.93)
    _draw_rect(page, 341.50, 685.00, 575.04, 817.93)
    _label(page, 20.27, 694.20, "INFORMAÇÕES COMPLEMENTARES")
    _label(page, 343.35, 694.20, "RESERVADO AO FISCO")
    _draw_wrapped(
        page,
        20.27,
        697.0,
        340.0,
        815.5,
        data["informacoes"],
        5.75,
        False,
        "left",
        6.5,
    )


def _draw_continuation(page: fitz.Page, data: dict, page_no: int, total_pages: int, items: list[dict], heights: list[float]):
    _draw_header(page, data, page_no, total_pages)
    _draw_product_table(
        page,
        items,
        heights,
        top=201.31,
        bottom=817.93,
        title_y=200.63,
        header_y=210.25,
        data_y=219.0,
    )


def _draw_void_watermark(page: fitz.Page, data: dict):
    if data["tpAmb"] == "2" or not data["protocolo"]:
        text = "SEM VALOR FISCAL"
        page.insert_text(
            (155, 500),
            text,
            fontsize=42,
            fontname=FONT_BOLD,
            color=(0.75, 0.75, 0.75),
            overlay=True,
        )


def generate_danfe_pdf(raw_xml: bytes) -> bytes:
    data = _parse_nfe(raw_xml)
    product_pages, height_pages = _split_products(data["items"])
    total_pages = len(product_pages)

    doc = fitz.open()

    first = doc.new_page(width=PAGE_W, height=PAGE_H)
    _draw_header(first, data, 1, total_pages)
    _draw_recipient(first, data)
    _draw_billing(first, data)
    _draw_taxes(first, data)
    _draw_shipping(first, data)
    _draw_product_table(
        first,
        product_pages[0],
        height_pages[0],
        top=427.46,
        bottom=645.31,
        title_y=426.79,
        header_y=436.02,
        data_y=445.44,
    )
    _draw_issqn_and_additional(first, data)
    _draw_void_watermark(first, data)

    for page_idx in range(1, total_pages):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)
        _draw_continuation(
            page,
            data,
            page_idx + 1,
            total_pages,
            product_pages[page_idx],
            height_pages[page_idx],
        )
        _draw_void_watermark(page, data)

    output = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return output


def danfe_file_name(meta: DanfeMetadata) -> str:
    numero = _digits(meta.numero_nf) or "SEM_NUMERO"
    emitente = _safe_name(meta.emitente)
    return f"DANFE_NF_{numero}_{emitente}.pdf"
