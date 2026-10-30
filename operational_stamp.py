from __future__ import annotations

from datetime import date, datetime
import re

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



def _wrapped_lines(value: str, width: float, size: float) -> list[str]:
    """Quebra palavras respeitando a largura em pontos da fonte Times-Roman."""
    if not value:
        return [""]
    result: list[str] = []
    for paragraph in str(value).replace("\r", "").split("\n"):
        words = paragraph.split()
        if not words:
            result.append("")
            continue
        line = ""
        for word in words:
            candidate = (line + " " + word).strip()
            if fitz.get_text_length(candidate, fontname="Times-Roman", fontsize=size) <= width:
                line = candidate
                continue
            if line:
                result.append(line)
                line = ""
            # Código/descrição sem espaço: não deixar a palavra invadir
            # a borda do carimbo. Dividir apenas quando indispensável.
            part = ""
            for char in word:
                trial = part + char
                if (part and fitz.get_text_length(
                    trial, fontname="Times-Roman", fontsize=size
                ) > width):
                    result.append(part)
                    part = char
                else:
                    part = trial
            line = part
        if line:
            result.append(line)
    return result or [""]


def _stamp_row_layout(
    rows: list[tuple[str, str]], rect: fitz.Rect
) -> tuple[float, list[tuple[float, list[str]]]]:
    """Dimensiona linhas e tipografia antes de desenhar qualquer conteúdo."""
    title_h = 18.0
    body_h = rect.height - title_h
    label_w = min(92.0, rect.width * 0.36)
    content_w = rect.width - label_w - 10.0
    if body_h < 60 or content_w < 50:
        raise ValueError("Área insuficiente para o carimbo de controle interno.")

    for tenths in range(72, 49, -2):
        fontsize = tenths / 10.0
        planned = []
        for _, value in rows:
            lines = _wrapped_lines(value, content_w - 1.5, fontsize)
            height = max(13.8, len(lines) * fontsize * 1.16 + 5.0)
            planned.append((height, lines))
        required = sum(h for h, _ in planned)
        if required <= body_h + 1e-6:
            slack = max(0.0, body_h - required) / len(rows)
            return fontsize, [(h + slack, lines) for h, lines in planned]
    raise ValueError(
        "O texto do controle interno excede a área disponível. "
        "Nenhuma descrição foi omitida; revise a quantidade de CRs "
        "ou utilize um layout com maior área reservada."
    )


def draw_operational_stamp_block(
    page: fitz.Page,
    rect: fitz.Rect,
    data_chegada: object,
    cr: object,
    desc_cr: object,
    natureza: object,
    recebido_por: object,
) -> None:
    """Desenha o carimbo SETTA completo, sem cortes nem campos silenciosos.

    O retângulo e a posição permanecem iguais; a altura das linhas internas
    é distribuída automaticamente entre os cinco campos. Texto excessivo
    provoca erro explícito ANTES da inserção do carimbo.
    """
    if rect.is_empty:
        raise ValueError("Área inválida para o controle interno.")
    rows = [
        ("DATA DE CHEGADA", _stamp_date(data_chegada)),
        ("CR", str(cr or "").strip()),
        ("DESC. CR", str(desc_cr or "").strip()),
        ("NATUREZA", str(natureza or "").strip().upper()),
        ("RECEBIDO POR", str(recebido_por or "").strip().upper()),
    ]
    if rows[1][1] and not rows[2][1]:
        raise ValueError(
            "CR informado, mas DESC. CR está vazio. "
            "O carimbo não pode ser gerado sem a descrição."
        )
    fontsize, layout = _stamp_row_layout(rows, rect)

    x0, y0, x1, y1 = rect
    title_h = 18.0
    label_w = min(92.0, rect.width * 0.36)
    page.draw_rect(rect, color=STAMP_BORDER, fill=(1, 1, 1),
                   width=0.75, overlay=True)
    page.draw_rect(
        fitz.Rect(x0, y0, x1, y0 + title_h),
        color=STAMP_BORDER, fill=STAMP_HEADER,
        width=0.75, overlay=True,
    )
    title_result = page.insert_textbox(
        fitz.Rect(x0 + 6, y0 + 4, x1 - 6, y0 + title_h - 2),
        "CONTROLE INTERNO - SETTA", fontsize=8.0,
        fontname="Times-Bold", color=STAMP_TEXT, overlay=True,
    )
    if title_result < 0:
        raise ValueError("Não foi possível renderizar o título do controle interno.")

    y = y0 + title_h
    for index, ((label, _), (height, lines)) in enumerate(zip(rows, layout)):
        top = y
        bottom = y1 if index == len(rows) - 1 else y + height
        if index:
            page.draw_line(
                fitz.Point(x0, top), fitz.Point(x1, top),
                color=(0.76, 0.76, 0.76), width=0.35, overlay=True,
            )
        page.draw_line(
            fitz.Point(x0 + label_w, top),
            fitz.Point(x0 + label_w, bottom),
            color=(0.76, 0.76, 0.76), width=0.35, overlay=True,
        )
        page.insert_text(
            fitz.Point(x0 + 5, top + 3 + 5.4),
            label, fontsize=5.4, fontname="Times-Bold",
            color=(0.25, 0.25, 0.25), overlay=True,
        )
        for line_number, line in enumerate(lines):
            baseline = top + 3.0 + fontsize * (1 + line_number * 1.16)
            if baseline > bottom - 1:
                raise ValueError(f"Sem espaço para o campo {label}.")
            page.insert_text(
                fitz.Point(x0 + label_w + 5, baseline),
                line, fontsize=fontsize, fontname="Times-Roman",
                color=STAMP_TEXT, overlay=True,
            )
        y = bottom


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
