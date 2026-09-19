from __future__ import annotations

from datetime import date, datetime

import fitz


STAMP_BORDER = (0.28, 0.31, 0.35)
STAMP_HEADER = (0.90, 0.91, 0.93)
STAMP_TEXT = (0.08, 0.09, 0.11)


def _stamp_date(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y")
    if isinstance(value, date):
        return value.strftime("%d/%m/%Y")

    raw = str(value or "").strip()
    if not raw:
        return ""

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw[:10], fmt).strftime("%d/%m/%Y")
        except Exception:
            pass
    return raw


def _stamp_fit_size(
    value: str,
    width: float,
    preferred: float = 7.0,
    minimum: float = 5.2,
) -> float:
    size = preferred
    while size > minimum:
        if fitz.get_text_length(
            str(value or ""),
            fontname="helv",
            fontsize=size,
        ) <= width:
            return size
        size -= 0.2
    return minimum


def draw_operational_stamp_block(
    page: fitz.Page,
    rect: fitz.Rect,
    data_chegada: object,
    cr: object,
    desc_cr: object,
    natureza: object,
    recebido_por: object,
) -> None:
    """Desenha apenas a camada operacional SETTA, sem alterar a DANFE-base."""
    x0, y0, x1, y1 = rect
    if x1 <= x0 or y1 <= y0:
        raise ValueError("Área inválida para o controle interno.")

    page.draw_rect(
        rect,
        color=STAMP_BORDER,
        fill=(1, 1, 1),
        width=0.75,
        overlay=True,
    )

    title_h = 18.0
    title_rect = fitz.Rect(x0, y0, x1, min(y1, y0 + title_h))
    page.draw_rect(
        title_rect,
        color=STAMP_BORDER,
        fill=STAMP_HEADER,
        width=0.75,
        overlay=True,
    )
    page.insert_textbox(
        fitz.Rect(x0 + 6, y0 + 4, x1 - 6, y0 + title_h - 2),
        "CONTROLE INTERNO - SETTA",
        fontsize=8.0,
        fontname="Times-Bold",
        color=STAMP_TEXT,
        align=0,
        overlay=True,
    )

    rows = [
        ("DATA DE CHEGADA", _stamp_date(data_chegada)),
        ("CR", str(cr or "").strip()),
        ("DESC. CR", str(desc_cr or "").strip()),
        ("NATUREZA", str(natureza or "").strip().upper()),
        ("RECEBIDO POR", str(recebido_por or "").strip().upper()),
    ]

    body_top = y0 + title_h
    body_h = max(1.0, y1 - body_top)
    row_h = body_h / len(rows)
    label_w = min(92.0, (x1 - x0) * 0.36)

    for idx, (label, value) in enumerate(rows):
        ry0 = body_top + idx * row_h
        ry1 = body_top + (idx + 1) * row_h

        if idx:
            page.draw_line(
                fitz.Point(x0, ry0),
                fitz.Point(x1, ry0),
                color=(0.76, 0.76, 0.76),
                width=0.35,
                overlay=True,
            )

        page.draw_line(
            fitz.Point(x0 + label_w, ry0),
            fitz.Point(x0 + label_w, ry1),
            color=(0.76, 0.76, 0.76),
            width=0.35,
            overlay=True,
        )

        page.insert_textbox(
            fitz.Rect(x0 + 5, ry0 + 3, x0 + label_w - 4, ry1 - 2),
            label,
            fontsize=5.4,
            fontname="Times-Bold",
            color=(0.25, 0.25, 0.25),
            align=0,
            overlay=True,
        )

        value_size = _stamp_fit_size(
            value,
            max(15.0, x1 - (x0 + label_w) - 10),
            preferred=7.2,
            minimum=5.4,
        )
        page.insert_textbox(
            fitz.Rect(x0 + label_w + 5, ry0 + 3, x1 - 5, ry1 - 2),
            value,
            fontsize=value_size,
            fontname="Times-Roman",
            color=STAMP_TEXT,
            align=0,
            lineheight=1.0,
            overlay=True,
        )


def operational_stamp_default_size() -> tuple[float, float]:
    return 250.0, 104.0


def apply_operational_stamp(
    pdf_bytes: bytes,
    data_chegada: object,
    cr: object,
    desc_cr: object,
    natureza: object,
    recebido_por: object,
) -> bytes:
    """Aplica o carimbo após a DANFE estar completamente renderizada."""
    if not pdf_bytes:
        return pdf_bytes

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if doc.page_count == 0:
        doc.close()
        return pdf_bytes

    target_page = None
    target_label = None

    for candidate in doc:
        text = candidate.get_text("text").upper()
        if (
            "CONTROLE INTERNO - SETTA" in text
            or "CONTROLE INTERNO - SETTA" in text
        ):
            doc.close()
            return pdf_bytes

        hits = candidate.search_for("RESERVADO AO FISCO")
        if hits:
            target_page = candidate
            target_label = hits[-1]

    page = target_page if target_page is not None else doc[-1]
    page_rect = page.rect
    width, height = operational_stamp_default_size()

    if target_label is not None:
        x0 = max(target_label.x0 - 2.0, page_rect.width * 0.565)
        x1 = page_rect.width - 21.0
        available_width = max(150.0, x1 - x0)
        width = min(width, available_width)
        x0 = x1 - width
        y0 = target_label.y1 + 5.0
        y1 = min(y0 + height, page_rect.height - 24.0)
        if y1 - y0 < 76.0:
            y0 = max(target_label.y1 + 2.0, y1 - 92.0)
    else:
        x1 = page_rect.width - 21.0
        x0 = max(21.0, x1 - width)
        y1 = page_rect.height - 24.0
        y0 = max(21.0, y1 - height)

    draw_operational_stamp_block(
        page,
        fitz.Rect(x0, y0, x1, y1),
        data_chegada=data_chegada,
        cr=cr,
        desc_cr=desc_cr,
        natureza=natureza,
        recebido_por=recebido_por,
    )

    output = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    return output
