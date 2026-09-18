from __future__ import annotations

import math
from dataclasses import dataclass

import fitz


PAGE_W = 595.276
PAGE_H = 841.89
MARGIN = 18.4
RIGHT = PAGE_W - MARGIN
BOTTOM = PAGE_H - 22.0

# Posições-base inspiradas no DANFE padrão Protheus/TOTVS usado como referência.
# A primeira folha mantém ISSQN e Dados Adicionais na faixa inferior; a área de
# produtos cresce até esse limite e continua em novas páginas quando necessário.
FIRST_PRODUCT_BOTTOM = 646.0
ISSQN_TOP = 654.0
ADDITIONAL_TOP = 684.0
ADDITIONAL_BOTTOM = 818.0

BLACK = (0, 0, 0)
DARK = (0.13, 0.13, 0.13)
MID = (0.48, 0.48, 0.48)
LIGHT = (0.94, 0.94, 0.94)
VERY_LIGHT = (0.975, 0.975, 0.975)

# MOC 7.0 Anexo II, item 3.7: Times New Roman ou Courier New.
# PyMuPDF disponibiliza a família Times como fonte PDF base.
FONT = "Times-Roman"
FONT_BOLD = "Times-Bold"
BORDER = 0.42

PRODUCT_X = [
    18.4, 64.0, 180.0, 217.0, 238.0, 260.0, 279.0, 320.0,
    369.0, 410.0, 450.0, 482.0, 508.0, 535.0, 556.0, 576.9,
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


@dataclass
class PagePlan:
    items: list[dict]
    row_heights: list[float]
    first: bool
    additional_lines: list[str] | None = None
    additional_only: bool = False


def _fmt_number(value, decimals=2) -> str:
    try:
        number = float(str(value or "0").replace(",", "."))
    except Exception:
        number = 0.0
    raw = f"{number:,.{decimals}f}"
    return raw.replace(",", "X").replace(".", ",").replace("X", ".")


def _fmt_date(value: str) -> str:
    if not value:
        return ""
    try:
        from datetime import datetime
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).strftime("%d/%m/%Y")
    except Exception:
        raw = str(value)
        if len(raw) >= 10 and raw[4] == "-" and raw[7] == "-":
            return f"{raw[8:10]}/{raw[5:7]}/{raw[:4]}"
        return raw


def _fmt_time(value: str) -> str:
    raw = str(value or "")
    return raw[11:19] if len(raw) >= 19 and "T" in raw else ""


def _fmt_nf(value: str) -> str:
    try:
        return f"{int(value):09d}"
    except Exception:
        return str(value or "")


def _text_width(value: str, size: float, bold=False) -> float:
    return fitz.get_text_length(
        str(value or ""),
        fontname=FONT_BOLD if bold else FONT,
        fontsize=size,
    )


def _fit_size(value: str, width: float, preferred: float, minimum: float, bold=False) -> float:
    size = preferred
    while size > minimum and _text_width(value, size, bold) > width:
        size -= 0.15
    return max(minimum, size)


def _wrap(value: str, width: float, size: float, bold=False) -> list[str]:
    value = str(value or "").strip()
    if not value:
        return []
    words = value.split()
    font = FONT_BOLD if bold else FONT
    lines = []
    current = ""
    for word in words:
        candidate = word if not current else f"{current} {word}"
        if fitz.get_text_length(candidate, fontname=font, fontsize=size) <= width:
            current = candidate
        else:
            if current:
                lines.append(current)
            # quebrar palavras excepcionalmente longas
            if fitz.get_text_length(word, fontname=font, fontsize=size) > width:
                part = ""
                for char in word:
                    test = part + char
                    if fitz.get_text_length(test, fontname=font, fontsize=size) <= width:
                        part = test
                    else:
                        if part:
                            lines.append(part)
                        part = char
                current = part
            else:
                current = word
    if current:
        lines.append(current)
    return lines


def _line(page, x0, y0, x1, y1, width=BORDER, color=BLACK):
    page.draw_line(
        fitz.Point(x0, y0),
        fitz.Point(x1, y1),
        width=width,
        color=color,
        overlay=True,
    )


def _rect(page, rect, fill=None, width=BORDER, color=BLACK):
    page.draw_rect(
        fitz.Rect(*rect),
        width=width,
        color=color,
        fill=fill,
        overlay=True,
    )


def _text(page, x, y, value, size=6.4, bold=False, color=BLACK):
    if value is None:
        return
    page.insert_text(
        (x, y),
        str(value),
        fontsize=size,
        fontname=FONT_BOLD if bold else FONT,
        color=color,
        overlay=True,
    )


def _fit_text(page, x0, y, x1, value, preferred=6.4, minimum=4.4, bold=False, align="left"):
    value = str(value or "")
    size = _fit_size(value, max(1, x1 - x0), preferred, minimum, bold)
    width = _text_width(value, size, bold)
    x = x0
    if align == "right":
        x = x1 - width
    elif align == "center":
        x = x0 + max(0, (x1 - x0 - width) / 2)
    _text(page, x, y, value, size, bold)


def _textbox(page, rect, value, size=6.0, bold=False, align=0, color=BLACK, lineheight=1.08):
    if not str(value or "").strip():
        return
    page.insert_textbox(
        fitz.Rect(*rect),
        str(value),
        fontsize=size,
        fontname=FONT_BOLD if bold else FONT,
        color=color,
        align=align,
        lineheight=lineheight,
        overlay=True,
    )


def _label(page, x, y, value):
    _text(page, x, y, value, 4.85, True, MID)


def _cell(page, rect, label, value="", value_size=6.25, bold=False, align="left", fill=None):
    x0, y0, x1, y1 = rect
    _rect(page, rect, fill=fill)
    _label(page, x0 + 2.1, y0 + 6.7, label)
    if value not in (None, ""):
        baseline = y1 - 3.5
        _fit_text(
            page,
            x0 + 2.1,
            baseline,
            x1 - 2.1,
            value,
            preferred=value_size,
            minimum=4.3,
            bold=bold,
            align=align,
        )


def _section_title(page, y, title):
    _text(page, MARGIN + 1, y + 8, title, 5.0, True, DARK)
    _line(page, MARGIN, y + 10, RIGHT, y + 10, 0.55, DARK)


def _code128_a_value(char: str) -> int:
    code = ord(char)
    if 32 <= code <= 95:
        return code - 32
    if 0 <= code <= 31:
        return code + 64
    raise ValueError(f"Caractere não suportado no CODE-128A: {char!r}")


def _code128_values(raw_key: str) -> list[int]:
    """Codifica chave de acesso em CODE-128C e alterna para A quando necessário.

    O MOC vigente exige CODE-128C para chave numérica. A NT conjunta de CNPJ
    alfanumérico prevê modelo híbrido C/A quando houver letras na chave.
    """
    key = "".join(ch for ch in str(raw_key or "").upper() if ch.isalnum())
    if len(key) != 44:
        raise ValueError(
            f"Chave de acesso deve possuir 44 posições; recebidas {len(key)}."
        )

    # Começa em C quando possível, como no padrão tradicional.
    values = [105]  # Start C
    mode = "C"
    i = 0

    while i < len(key):
        if mode == "C":
            if i + 1 < len(key) and key[i].isdigit() and key[i + 1].isdigit():
                values.append(int(key[i:i + 2]))
                i += 2
                continue

            # Troca para A para letras ou um dígito isolado.
            values.append(101)  # Code A
            mode = "A"
            continue

        # Em A, volta para C quando houver sequência numérica de pelo menos
        # quatro dígitos; isso preserva a compactação do padrão C.
        numeric_run = 0
        while (
            i + numeric_run < len(key)
            and key[i + numeric_run].isdigit()
        ):
            numeric_run += 1

        if numeric_run >= 4:
            if numeric_run % 2:
                values.append(_code128_a_value(key[i]))
                i += 1
            values.append(99)  # Code C
            mode = "C"
            continue

        values.append(_code128_a_value(key[i]))
        i += 1

    checksum = (
        values[0]
        + sum(value * idx for idx, value in enumerate(values[1:], 1))
    ) % 103
    return [*values, checksum, 106]


def _barcode(page, rect, key):
    x0, y0, x1, y1 = rect
    values = _code128_values(key)
    patterns = [CODE128_PATTERNS[v] for v in values]

    pattern_modules = sum(
        sum(int(char) for char in pattern)
        for pattern in patterns
    )
    quiet_modules = 10
    total_modules = pattern_modules + (quiet_modules * 2)

    width = x1 - x0
    height = y1 - y0
    # MOC: largura total mínima de 6 cm em laser/jato de tinta,
    # altura mínima de 0,8 cm e módulo mínimo de 0,02 cm.
    min_width_pt = 60.0 / 25.4 * 72.0
    min_height_pt = 8.0 / 25.4 * 72.0
    min_module_pt = 0.2 / 25.4 * 72.0

    if width < min_width_pt:
        raise ValueError(
            "Área do código de barras inferior aos 6 cm mínimos do MOC."
        )
    if height < min_height_pt:
        raise ValueError(
            "Altura do código de barras inferior aos 0,8 cm mínimos do MOC."
        )

    module = width / total_modules
    if module < min_module_pt:
        raise ValueError(
            "Módulo do código de barras inferior a 0,02 cm."
        )

    cursor = x0 + quiet_modules * module

    for pattern in patterns:
        black = True
        for char in pattern:
            bar_width = int(char) * module
            if black:
                page.draw_rect(
                    fitz.Rect(cursor, y0, cursor + bar_width, y1),
                    color=None,
                    fill=BLACK,
                    overlay=True,
                )
            cursor += bar_width
            black = not black


def _validate_payload(data: dict) -> None:
    required = {
        "nf": "Número da NF-e",
        "serie": "Série",
        "key": "Chave de acesso",
        "emitente": "Emitente",
        "emitente_cnpj": "CNPJ/CPF do emitente",
        "destinatario": "Destinatário",
    }
    missing = [
        label
        for key, label in required.items()
        if not str(data.get(key) or "").strip()
    ]
    if missing:
        raise ValueError(
            "XML não possui dados mínimos para o DANFE: "
            + ", ".join(missing)
        )

    key = "".join(
        ch
        for ch in str(data.get("key") or "").upper()
        if ch.isalnum()
    )
    if len(key) != 44:
        raise ValueError(
            f"Chave de acesso inválida: esperado 44 posições, encontrado {len(key)}."
        )


def _draw_receipt(page, data, y):
    # Canhoto no topo no modo retrato, conforme MOC. Acrescentamos uma faixa
    # de controle interno logo abaixo; o Portal permite campos adicionais no
    # canhoto desde que o conteúdo fiscal e a leitura do DANFE não sejam
    # prejudicados.
    h = 48.0
    split = RIGHT - 127.5  # ~4,5 cm para NF-e / número / série

    _rect(page, (MARGIN, y, RIGHT, y + h))
    _line(page, split, y, split, y + h)
    _line(page, MARGIN, y + 24, split, y + 24)

    _textbox(
        page,
        (MARGIN + 3, y + 3, split - 3, y + 21),
        (
            f"RECEBEMOS DE {data['emitente']} OS PRODUTOS/SERVIÇOS "
            "CONSTANTES DA NOTA FISCAL ELETRÔNICA INDICADA AO LADO."
        ),
        6.0,
        False,
        0,
        BLACK,
        1.0,
    )

    date_w = 116.0
    _line(page, MARGIN + date_w, y + 24, MARGIN + date_w, y + h)
    _label(page, MARGIN + 3, y + 31, "DATA DE RECEBIMENTO")
    _label(
        page,
        MARGIN + date_w + 3,
        y + 31,
        "IDENTIFICAÇÃO E ASSINATURA DO RECEBEDOR",
    )

    _fit_text(
        page,
        split + 5,
        y + 12,
        RIGHT - 5,
        "NF-e",
        10.0,
        10.0,
        True,
        "center",
    )
    _fit_text(
        page,
        split + 5,
        y + 29,
        RIGHT - 5,
        f"Nº {_fmt_nf(data['nf'])}",
        10.0,
        10.0,
        True,
        "center",
    )
    _fit_text(
        page,
        split + 5,
        y + 42,
        RIGHT - 5,
        f"SÉRIE {data['serie']}",
        10.0,
        10.0,
        True,
        "center",
    )

    # Faixa adicional do canhoto para o fluxo SETTA. Ela fica fora do quadro
    # RESERVADO AO FISCO e será preenchida depois do cruzamento operacional.
    y2 = y + h + 2
    control_h = 24.0
    _rect(page, (MARGIN, y2, RIGHT, y2 + control_h), fill=VERY_LIGHT)
    widths = [94.0, 62.0, 112.0, 165.0]
    points = [MARGIN]
    for width in widths:
        points.append(points[-1] + width)
    points.append(RIGHT)

    for x in points[1:-1]:
        _line(page, x, y2, x, y2 + control_h, 0.35, MID)

    labels = [
        "CONTROLE INTERNO — SETTA",
        "CR",
        "DESC. CR",
        "NATUREZA",
        "RECEBIDO POR",
    ]
    for idx, label in enumerate(labels):
        x0, x1 = points[idx], points[idx + 1]
        _label(page, x0 + 3, y2 + 7, label)

    return y2 + control_h + 4


def _draw_main_header(page, data, y, page_no, total_pages):
    h = 88.0
    left_w = 232.0
    center_w = 95.0
    x1 = MARGIN + left_w
    x2 = x1 + center_w

    _rect(page, (MARGIN, y, x1, y + h))
    _rect(page, (x1, y, x2, y + h))
    _rect(page, (x2, y, RIGHT, y + h))

    # emitente
    _text(page, MARGIN + 5, y + 12, data["emitente"], 8.0, True)
    a = data["emitente_end"]
    address = ", ".join(v for v in [a["logradouro"], a["numero"], a["complemento"]] if v)
    rows = [
        address,
        " - ".join(v for v in [a["bairro"], f"CEP {a['cep']}" if a["cep"] else ""] if v),
        " / ".join(v for v in [a["municipio"], a["uf"]] if v),
        f"Fone: {a['fone']}" if a["fone"] else "",
    ]
    yy = y + 26
    for row in rows:
        if row:
            _fit_text(page, MARGIN + 5, yy, x1 - 5, row, 6.0, 4.6)
            yy += 10

    # centro DANFE
    _fit_text(page, x1 + 4, y + 15, x2 - 4, "DANFE", 14.0, 10.0, True, "center")
    _textbox(
        page,
        (x1 + 5, y + 19, x2 - 5, y + 42),
        "Documento Auxiliar da Nota Fiscal Eletrônica",
        5.6,
        False,
        1,
    )
    _text(page, x1 + 10, y + 52, "0 - ENTRADA", 5.6)
    _text(page, x1 + 10, y + 61, "1 - SAÍDA", 5.6)
    _rect(page, (x2 - 22, y + 45, x2 - 8, y + 61))
    _fit_text(page, x2 - 22, y + 57, x2 - 8, data.get("tpNF") or "1", 7.0, 6.0, True, "center")
    _text(page, x1 + 7, y + 72, f"Nº {_fmt_nf(data['nf'])}", 6.8, True)
    _text(page, x1 + 7, y + 81, f"SÉRIE {data['serie']}  |  FOLHA {page_no}/{total_pages}", 5.8, True)

    # direita
    _barcode(page, (x2 + 12, y + 6, RIGHT - 12, y + 29), data["key"])
    _label(page, x2 + 7, y + 39, "CHAVE DE ACESSO")
    grouped = " ".join(data["key"][i:i+4] for i in range(0, len(data["key"]), 4))
    _fit_text(page, x2 + 7, y + 49, RIGHT - 7, grouped, 7.6, 5.2, True)
    _textbox(
        page,
        (x2 + 7, y + 56, RIGHT - 7, y + 83),
        "Consulta de autenticidade no portal nacional da NF-e\nwww.nfe.fazenda.gov.br/portal",
        5.3,
        False,
        0,
    )
    return y + h


def _draw_identification(page, data, y):
    row_h = 21
    w = RIGHT - MARGIN
    # natureza + protocolo
    split = MARGIN + w * 0.57
    _cell(page, (MARGIN, y, split, y + row_h), "NATUREZA DA OPERAÇÃO", data["natOp"])
    protocol = data["protocolo"]
    if data["protocolo_data"]:
        protocol += f" - {_fmt_date(data['protocolo_data'])} {_fmt_time(data['protocolo_data'])}".rstrip()
    _cell(page, (split, y, RIGHT, y + row_h), "PROTOCOLO DE AUTORIZAÇÃO DE USO", protocol, 5.7)
    y += row_h

    x1 = MARGIN + w / 3
    x2 = MARGIN + 2 * w / 3
    _cell(page, (MARGIN, y, x1, y + row_h), "INSCRIÇÃO ESTADUAL", data["emitente_ie"])
    _cell(page, (x1, y, x2, y + row_h), "INSC. ESTADUAL DO SUBST. TRIB.", data["emitente_iest"])
    _cell(page, (x2, y, RIGHT, y + row_h), "CNPJ / CPF", data["emitente_cnpj"])
    return y + row_h + 4


def _draw_recipient(page, data, y):
    _section_title(page, y, "DESTINATÁRIO / REMETENTE")
    y += 13
    w = RIGHT - MARGIN
    a = data["destinatario_end"]

    r = 20
    x1 = MARGIN + w * 0.48
    x2 = MARGIN + w * 0.82
    _cell(page, (MARGIN, y, x1, y + r), "NOME / RAZÃO SOCIAL", data["destinatario"], 6.2, True)
    _cell(page, (x1, y, x2, y + r), "CNPJ / CPF", data["destinatario_cnpj"])
    _cell(page, (x2, y, RIGHT, y + r), "DATA DE EMISSÃO", _fmt_date(data["dhEmi"]))
    y += r

    x1 = MARGIN + w * 0.39
    x2 = MARGIN + w * 0.65
    x3 = MARGIN + w * 0.82
    address = ", ".join(v for v in [a["logradouro"], a["numero"], a["complemento"]] if v)
    _cell(page, (MARGIN, y, x1, y + r), "ENDEREÇO", address, 5.7)
    _cell(page, (x1, y, x2, y + r), "BAIRRO / DISTRITO", a["bairro"])
    _cell(page, (x2, y, x3, y + r), "CEP", a["cep"])
    _cell(page, (x3, y, RIGHT, y + r), "DATA ENTRADA / SAÍDA", _fmt_date(data["dhSaiEnt"]))
    y += r

    x1 = MARGIN + w * 0.25
    x2 = MARGIN + w * 0.44
    x3 = MARGIN + w * 0.54
    x4 = MARGIN + w * 0.82
    _cell(page, (MARGIN, y, x1, y + r), "MUNICÍPIO", a["municipio"])
    _cell(page, (x1, y, x2, y + r), "FONE / FAX", a["fone"])
    _cell(page, (x2, y, x3, y + r), "UF", a["uf"])
    _cell(page, (x3, y, x4, y + r), "INSCRIÇÃO ESTADUAL", data["destinatario_ie"])
    _cell(page, (x4, y, RIGHT, y + r), "HORA ENTRADA / SAÍDA", _fmt_time(data["dhSaiEnt"]))
    return y + r + 4


def _billing_rows(data):
    dups = data.get("duplicatas") or []
    if not dups:
        return [[]]
    per_row = 8
    return [dups[i:i+per_row] for i in range(0, len(dups), per_row)]


def _billing_height(data):
    rows = _billing_rows(data)
    return 14 + max(1, len(rows)) * 23 + 3


def _draw_billing(page, data, y):
    _section_title(page, y, "FATURA / DUPLICATAS")
    y += 13
    rows = _billing_rows(data)
    if not rows or rows == [[]]:
        rows = [[]]
    h = 23
    for row in rows:
        count = max(1, len(row))
        col_w = (RIGHT - MARGIN) / max(8, count)
        # mantém 8 espaços para aparência de DANFE mesmo quando há poucas parcelas
        col_w = (RIGHT - MARGIN) / 8
        for i in range(8):
            x0 = MARGIN + i * col_w
            x1 = x0 + col_w
            _rect(page, (x0, y, x1, y + h))
            if i < len(row):
                dup = row[i]
                _fit_text(page, x0 + 2, y + 8, x1 - 2, dup["numero"], 5.0, 4.0)
                _fit_text(page, x0 + 2, y + 15, x1 - 2, _fmt_date(dup["vencimento"]), 5.0, 4.0)
                _fit_text(page, x0 + 2, y + 21, x1 - 2, _fmt_number(dup["valor"]), 5.3, 4.0, True, "right")
        y += h

    if rows == [[]]:
        f = data.get("fatura") or {}
        p = data.get("pagamento") or {}
        value = ""
        if f.get("numero") or f.get("liquido"):
            value = f"Fatura {f.get('numero','')}  |  Valor líquido {_fmt_number(f.get('liquido'))}"
        elif p.get("forma") or p.get("valor"):
            value = f"Pagamento {p.get('forma','')}  |  Valor {_fmt_number(p.get('valor'))}"
        if value:
            _fit_text(page, MARGIN + 3, y - 7, RIGHT - 3, value, 5.6, 4.4)
    return y + 4


def _draw_taxes(page, data, y):
    _section_title(page, y, "CÁLCULO DO IMPOSTO")
    y += 13
    row_h = 21
    totals = data["totais"]
    labels1 = [
        ("BASE DE CÁLCULO DO ICMS", totals["vBC"]),
        ("VALOR DO ICMS", totals["vICMS"]),
        ("BASE DE CÁLCULO DO ICMS ST", totals["vBCST"]),
        ("VALOR DO ICMS ST", totals["vST"]),
        ("VALOR TOTAL DOS PRODUTOS", totals["vProd"]),
    ]
    widths1 = [0.20, 0.16, 0.25, 0.18, 0.21]
    x = MARGIN
    for (label, value), frac in zip(labels1, widths1):
        x1 = x + (RIGHT - MARGIN) * frac
        _cell(page, (x, y, x1, y + row_h), label, _fmt_number(value), 6.2, False, "right")
        x = x1
    y += row_h

    labels2 = [
        ("VALOR DO FRETE", totals["vFrete"]),
        ("VALOR DO SEGURO", totals["vSeg"]),
        ("DESCONTO", totals["vDesc"]),
        ("OUTRAS DESPESAS", totals["vOutro"]),
        ("VALOR DO IPI", totals["vIPI"]),
        ("VALOR TOTAL DA NOTA", totals["vNF"]),
    ]
    x = MARGIN
    for label, value in labels2:
        x1 = x + (RIGHT - MARGIN) / 6
        _cell(page, (x, y, x1, y + row_h), label, _fmt_number(value), 6.2, label.endswith("NOTA"), "right")
        x = x1
    return y + row_h + 4


def _freight(value):
    return {
        "0": "0 - REMETENTE",
        "1": "1 - DESTINATÁRIO",
        "2": "2 - TERCEIROS",
        "3": "3 - PRÓPRIO REM.",
        "4": "4 - PRÓPRIO DEST.",
        "9": "9 - SEM FRETE",
    }.get(str(value or ""), str(value or ""))


def _draw_shipping(page, data, y):
    _section_title(page, y, "TRANSPORTADOR / VOLUMES TRANSPORTADOS")
    y += 13
    c = data["transportador"]
    v = data["volume"]
    h = 20
    w = RIGHT - MARGIN

    x1 = MARGIN + w * 0.38
    x2 = MARGIN + w * 0.53
    x3 = MARGIN + w * 0.66
    x4 = MARGIN + w * 0.78
    x5 = MARGIN + w * 0.84
    _cell(page, (MARGIN, y, x1, y + h), "RAZÃO SOCIAL", c["nome"], 5.7)
    _cell(page, (x1, y, x2, y + h), "FRETE POR CONTA", _freight(c["frete"]), 5.2)
    _cell(page, (x2, y, x3, y + h), "CÓDIGO ANTT", "")
    _cell(page, (x3, y, x4, y + h), "PLACA DO VEÍCULO", "")
    _cell(page, (x4, y, x5, y + h), "UF", c["uf"])
    _cell(page, (x5, y, RIGHT, y + h), "CNPJ / CPF", c["cnpj"], 5.4)
    y += h

    x1 = MARGIN + w * 0.40
    x2 = MARGIN + w * 0.62
    x3 = MARGIN + w * 0.72
    _cell(page, (MARGIN, y, x1, y + h), "ENDEREÇO", c["endereco"], 5.5)
    _cell(page, (x1, y, x2, y + h), "MUNICÍPIO", c["municipio"])
    _cell(page, (x2, y, x3, y + h), "UF", c["uf"])
    _cell(page, (x3, y, RIGHT, y + h), "INSCRIÇÃO ESTADUAL", c["ie"])
    y += h

    labels = [
        ("QUANTIDADE", v["quantidade"]),
        ("ESPÉCIE", v["especie"]),
        ("MARCA", v["marca"]),
        ("NUMERAÇÃO", v["numeracao"]),
        ("PESO BRUTO", _fmt_number(v["peso_bruto"], 3)),
        ("PESO LÍQUIDO", _fmt_number(v["peso_liquido"], 3)),
    ]
    x = MARGIN
    for label, value in labels:
        x1 = x + w / 6
        _cell(page, (x, y, x1, y + h), label, value, 5.7)
        x = x1
    return y + h + 5


def _product_description(item):
    parts = [
        str(item.get("desc") or "").strip(),
        str(item.get("inf_ad_prod") or "").strip(),
    ]
    return " ".join(p for p in parts if p)


def _row_height(item):
    lines = _wrap(
        _product_description(item),
        PRODUCT_X[2] - PRODUCT_X[1] - 5,
        5.2,
    )
    return max(15.5, len(lines) * 6.1 + 6.0)


def _product_header_height():
    return 27.0


def _draw_product_header(page, y):
    _section_title(page, y, "DADOS DOS PRODUTOS / SERVIÇOS")
    y += 13
    h = _product_header_height()
    headers = [
        "CÓD. PROD.", "DESCRIÇÃO DO PRODUTO / SERVIÇO", "NCM/SH", "CST",
        "CFOP", "UN", "QUANT.", "V. UNITÁRIO", "V. TOTAL", "BC ICMS",
        "V. ICMS", "V. IPI", "% ICMS", "% IPI", "DESC.",
    ]
    for i in range(len(PRODUCT_X) - 1):
        x0, x1 = PRODUCT_X[i], PRODUCT_X[i + 1]
        _rect(page, (x0, y, x1, y + h), fill=LIGHT)
        _textbox(
            page,
            (x0 + 1.2, y + 3, x1 - 1.2, y + h - 2),
            headers[i],
            4.5,
            True,
            1,
            DARK,
            1.0,
        )
    return y + h


def _draw_product_rows(page, items, heights, y, bottom):
    for item, h in zip(items, heights):
        if y + h > bottom + 0.5:
            break
        _rect(page, (MARGIN, y, RIGHT, y + h), width=0.25, color=(0.72, 0.72, 0.72))
        for x in PRODUCT_X[1:-1]:
            _line(page, x, y, x, y + h, 0.25, (0.72, 0.72, 0.72))

        values = [
            item["code"],
            None,
            item["ncm"],
            item["cst"],
            item["cfop"],
            item["un"],
            _fmt_number(item["qty"], 4),
            _fmt_number(item["unit"], 6),
            _fmt_number(item["total"]),
            _fmt_number(item["bc"]),
            _fmt_number(item["vicms"]),
            _fmt_number(item["vipi"]),
            f"{_fmt_number(item['picms'])}%" if item["picms"] else "",
            f"{_fmt_number(item['pipi'])}%" if item["pipi"] else "",
            _fmt_number(item["discount"]) if item["discount"] else "",
        ]

        for i, value in enumerate(values):
            x0, x1 = PRODUCT_X[i], PRODUCT_X[i + 1]
            if i == 1:
                _textbox(
                    page,
                    (x0 + 2, y + 3, x1 - 2, y + h - 2),
                    _product_description(item),
                    5.2,
                    False,
                    0,
                    BLACK,
                    1.05,
                )
            elif value not in (None, ""):
                align = "right" if i >= 6 else "left"
                _fit_text(
                    page,
                    x0 + 1.5,
                    y + 8,
                    x1 - 1.5,
                    value,
                    5.2,
                    3.8,
                    False,
                    align,
                )
        y += h
    return y



def _extend_product_grid(page, y, bottom):
    if bottom <= y:
        return
    _rect(page, (MARGIN, y, RIGHT, bottom), width=0.25, color=(0.72, 0.72, 0.72))
    for x in PRODUCT_X[1:-1]:
        _line(page, x, y, x, bottom, 0.25, (0.72, 0.72, 0.72))


def _draw_issqn(page, data, y=ISSQN_TOP):
    _section_title(page, y, "CÁLCULO DO ISSQN")
    y += 13
    h = 21.0
    values = [
        ("INSCRIÇÃO MUNICIPAL", data.get("emitente_im") or ""),
        ("VALOR TOTAL DOS SERVIÇOS", _fmt_number(data["issqn"].get("vServ")) if data["issqn"].get("vServ") else ""),
        ("BASE DE CÁLCULO DO ISSQN", _fmt_number(data["issqn"].get("vBC")) if data["issqn"].get("vBC") else ""),
        ("VALOR DO ISSQN", _fmt_number(data["issqn"].get("vISS")) if data["issqn"].get("vISS") else ""),
    ]
    x = MARGIN
    for label, value in values:
        x1 = x + (RIGHT - MARGIN) / 4
        _cell(page, (x, y, x1, y + h), label, value, 5.8, False, "right" if label != "INSCRIÇÃO MUNICIPAL" else "left")
        x = x1
    return y + h


def _draw_additional_fixed(page, data, lines):
    y = ADDITIONAL_TOP
    _section_title(page, y, "DADOS ADICIONAIS")
    y += 13
    h = ADDITIONAL_BOTTOM - y
    xmid = MARGIN + 326.0
    _rect(page, (MARGIN, y, xmid, y + h))
    _rect(page, (xmid, y, RIGHT, y + h))
    _label(page, MARGIN + 3, y + 8, "INFORMAÇÕES COMPLEMENTARES")
    _label(page, xmid + 3, y + 8, "RESERVADO AO FISCO")
    _textbox(
        page,
        (MARGIN + 3, y + 12, xmid - 3, y + h - 3),
        "\n".join(lines),
        5.25,
        False,
        0,
        BLACK,
        1.03,
    )
    return y + h


def _compact_header_height():
    return 138.0


def _draw_compact_header(page, data, y, page_no, total_pages):
    # Cabeçalho das páginas seguintes reproduz a lógica do Protheus:
    # emitente + DANFE + chave, seguido de natureza/protocolo e inscrições.
    top_h = 92.0
    left = MARGIN + 230
    center = left + 96

    _rect(page, (MARGIN, y, left, y + top_h))
    _rect(page, (left, y, center, y + top_h))
    _rect(page, (center, y, RIGHT, y + top_h))

    _text(page, MARGIN + 5, y + 14, "Identificação do emitente", 5.0, True, MID)
    _fit_text(page, MARGIN + 5, y + 28, left - 5, data["emitente"], 8.0, 5.4, True, "center")
    a = data["emitente_end"]
    address = ", ".join(v for v in [a["logradouro"], a["numero"]] if v)
    _fit_text(page, MARGIN + 5, y + 44, left - 5, address, 5.5, 4.2, False, "center")
    _fit_text(page, MARGIN + 5, y + 56, left - 5, f"{a['municipio']}/{a['uf']}", 5.4, 4.2, False, "center")
    _fit_text(page, MARGIN + 5, y + 68, left - 5, f"Fone: {a['fone']}" if a["fone"] else "", 5.2, 4.0, False, "center")

    _fit_text(page, left + 4, y + 18, center - 4, "DANFE", 13.5, 10.0, True, "center")
    _textbox(
        page,
        (left + 5, y + 23, center - 5, y + 48),
        "Documento Auxiliar da\nNota Fiscal Eletrônica",
        5.0,
        False,
        1,
    )
    _fit_text(page, left + 4, y + 60, center - 4, f"Nº {_fmt_nf(data['nf'])}", 6.5, 5.0, True, "center")
    _fit_text(page, left + 4, y + 71, center - 4, f"SÉRIE {data['serie']}", 5.8, 4.8, True, "center")
    _fit_text(page, left + 4, y + 82, center - 4, f"FOLHA {page_no}/{total_pages}", 5.8, 4.8, True, "center")

    _barcode(page, (center + 13, y + 8, RIGHT - 13, y + 31), data["key"])
    grouped = " ".join(data["key"][i:i+4] for i in range(0, len(data["key"]), 4))
    _fit_text(page, center + 8, y + 45, RIGHT - 8, "CHAVE DE ACESSO DA NF-e", 5.2, 4.3, True)
    _fit_text(page, center + 8, y + 57, RIGHT - 8, grouped, 6.6, 4.8, True)
    _textbox(
        page,
        (center + 8, y + 63, RIGHT - 8, y + 88),
        "Consulta de autenticidade no portal nacional da NF-e\nwww.nfe.fazenda.gov.br/portal",
        5.0,
        False,
    )

    y2 = y + top_h + 4
    w = RIGHT - MARGIN
    split = MARGIN + w * 0.57
    _cell(page, (MARGIN, y2, split, y2 + 20), "NATUREZA DA OPERAÇÃO", data["natOp"], 5.8)
    protocol = data["protocolo"]
    if data["protocolo_data"]:
        protocol += f" - {_fmt_date(data['protocolo_data'])}"
    _cell(page, (split, y2, RIGHT, y2 + 20), "PROTOCOLO DE AUTORIZAÇÃO DE USO", protocol, 5.3)
    y2 += 20
    x1 = MARGIN + w / 3
    x2 = MARGIN + 2 * w / 3
    _cell(page, (MARGIN, y2, x1, y2 + 20), "INSCRIÇÃO ESTADUAL", data["emitente_ie"])
    _cell(page, (x1, y2, x2, y2 + 20), "INSC. ESTADUAL DO SUBST. TRIB.", data["emitente_iest"])
    _cell(page, (x2, y2, RIGHT, y2 + 20), "CNPJ / CPF", data["emitente_cnpj"])

    return y + _compact_header_height() + 6


def _additional_lines(data):
    return _wrap(data.get("informacoes") or "", 300, 5.4)


def _additional_height(lines):
    line_count = max(1, len(lines))
    text_h = min(180, line_count * 6.0 + 23)
    return max(96.0, text_h)


def _draw_additional(page, data, y, lines, max_height=None):
    h = _additional_height(lines)
    if max_height is not None:
        h = min(h, max_height)
    _section_title(page, y, "DADOS ADICIONAIS")
    y += 13
    left_w = 326.0
    xmid = MARGIN + left_w
    _rect(page, (MARGIN, y, xmid, y + h))
    _rect(page, (xmid, y, RIGHT, y + h))
    _label(page, MARGIN + 3, y + 8, "INFORMAÇÕES COMPLEMENTARES")
    _label(page, xmid + 3, y + 8, "RESERVADO AO FISCO")
    _textbox(
        page,
        (MARGIN + 3, y + 12, xmid - 3, y + h - 3),
        "\n".join(lines),
        5.4,
        False,
        0,
        BLACK,
        1.05,
    )
    # O lado direito fica deliberadamente livre para o controle interno SETTA.
    return y + h


def _first_static_end(data):
    # Deve espelhar as alturas usadas no desenho.
    y = MARGIN
    y += 34 + 4
    y += 88
    y += 21 * 2 + 4
    y += 13 + 20 * 3 + 4
    y += _billing_height(data)
    y += 13 + 21 * 2 + 4
    y += 13 + 20 * 3 + 5
    return y


def _paginate(data):
    items = data.get("items") or []
    heights = [_row_height(item) for item in items]

    first_start = _first_static_end(data) + 13 + _product_header_height()
    cont_start = MARGIN + _compact_header_height() + 6 + 13 + _product_header_height()

    additional_lines = _additional_lines(data)
    # O bloco inferior da 1ª página comporta aproximadamente 17 linhas no
    # padrão de fonte adotado. O excesso segue para páginas adicionais.
    first_additional_capacity = 17
    first_additional = additional_lines[:first_additional_capacity]
    extra_additional = additional_lines[first_additional_capacity:]

    plans = []
    idx = 0

    first_items, first_heights = [], []
    used = first_start
    while idx < len(items):
        h = heights[idx]
        if first_items and used + h > FIRST_PRODUCT_BOTTOM:
            break
        if not first_items and used + h > FIRST_PRODUCT_BOTTOM:
            h = max(15.5, FIRST_PRODUCT_BOTTOM - used)
        first_items.append(items[idx])
        first_heights.append(h)
        used += h
        idx += 1

    plans.append(
        PagePlan(
            first_items,
            first_heights,
            True,
            additional_lines=first_additional,
        )
    )

    while idx < len(items):
        page_items, page_heights = [], []
        used = cont_start
        while idx < len(items):
            h = heights[idx]
            if page_items and used + h > BOTTOM:
                break
            if not page_items and used + h > BOTTOM:
                h = max(15.5, BOTTOM - used)
            page_items.append(items[idx])
            page_heights.append(h)
            used += h
            idx += 1
        plans.append(PagePlan(page_items, page_heights, False))

    if extra_additional:
        per_page_lines = max(
            25,
            int((BOTTOM - (MARGIN + _compact_header_height() + 45)) / 5.8),
        )
        for pos in range(0, len(extra_additional), per_page_lines):
            plans.append(
                PagePlan(
                    [],
                    [],
                    False,
                    additional_lines=extra_additional[pos:pos + per_page_lines],
                    additional_only=True,
                )
            )

    return plans


def render_danfe_pdf(data: dict) -> bytes:
    plans = _paginate(data)
    total_pages = len(plans)
    doc = fitz.open()

    for page_index, plan in enumerate(plans, start=1):
        page = doc.new_page(width=PAGE_W, height=PAGE_H)

        if plan.first:
            y = MARGIN
            y = _draw_receipt(page, data, y)
            y = _draw_main_header(page, data, y, page_index, total_pages)
            y = _draw_identification(page, data, y)
            y = _draw_recipient(page, data, y)
            y = _draw_billing(page, data, y)
            y = _draw_taxes(page, data, y)
            y = _draw_shipping(page, data, y)

            y = _draw_product_header(page, y)
            y = _draw_product_rows(
                page,
                plan.items,
                plan.row_heights,
                y,
                FIRST_PRODUCT_BOTTOM,
            )
            _extend_product_grid(page, y, FIRST_PRODUCT_BOTTOM)
            _draw_issqn(page, data)
            _draw_additional_fixed(
                page,
                data,
                plan.additional_lines or [],
            )

        else:
            y = MARGIN
            y = _draw_compact_header(
                page,
                data,
                y,
                page_index,
                total_pages,
            )

            if plan.additional_only:
                lines = plan.additional_lines or []
                _section_title(page, y, "DADOS ADICIONAIS")
                y += 13
                xmid = MARGIN + 326.0
                _rect(page, (MARGIN, y, xmid, BOTTOM))
                _rect(page, (xmid, y, RIGHT, BOTTOM))
                _label(page, MARGIN + 3, y + 8, "INFORMAÇÕES COMPLEMENTARES")
                _label(page, xmid + 3, y + 8, "RESERVADO AO FISCO")
                _textbox(
                    page,
                    (MARGIN + 3, y + 12, xmid - 3, BOTTOM - 3),
                    "\n".join(lines),
                    5.25,
                    False,
                    0,
                    BLACK,
                    1.03,
                )
            else:
                y = _draw_product_header(page, y)
                y = _draw_product_rows(
                    page,
                    plan.items,
                    plan.row_heights,
                    y,
                    BOTTOM - 4,
                )
                _extend_product_grid(page, y, BOTTOM - 4)

        if data.get("tpAmb") == "2" or not data.get("protocolo"):
            _textbox(
                page,
                (85, 350, 510, 520),
                "SEM VALOR FISCAL",
                34,
                True,
                1,
                (0.78, 0.78, 0.78),
                1.0,
            )

    output = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return output
