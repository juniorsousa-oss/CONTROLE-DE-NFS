"""Trava de integridade fiscal dos lotes SETTA.

Executada antes de criar ZIPs. Bloqueia documentos da sessão anterior,
NF-e com identidade divergente e CT-e sem vínculo EXATO ao lote aprovado.
Não consulta banco e não altera dados.
"""
from __future__ import annotations

from collections import Counter
from pathlib import PurePosixPath
import io
import re
import zipfile


def _digits(value: object) -> str:
    return re.sub(r"\D", "", str(value or ""))


def _number(value: object) -> str:
    raw = _digits(value)
    return raw.lstrip("0") or ("0" if raw else "")


def _identity(row: dict) -> str:
    return str(row.get("_selection_key") or "").strip()


def validate_batch_selection(
    selected_keys: set[str],
    snapshot: list[dict],
    work: list[dict],
    pdfs: dict,
    ctes: list[dict],
    auxiliary: dict[str, dict] | None = None,
) -> None:
    """A seleção confirmada é a única fonte de autorização da geração."""
    if not selected_keys or not snapshot or not work:
        raise ValueError("LOTE BLOQUEADO: não há seleção congelada válida.")
    original_keys = [_identity(r) for r in snapshot]
    work_keys = [_identity(r) for r in work]
    if (any(not x for x in original_keys + work_keys)
        or len(set(original_keys)) != len(original_keys)
        or len(set(work_keys)) != len(work_keys)
        or set(original_keys) != selected_keys
        or set(work_keys) != selected_keys
        or len(original_keys) != len(work_keys)):
        raise ValueError(
            "LOTE BLOQUEADO: NFs preparadas não coincidem exatamente com as "
            "NFs selecionadas. Reinicie a conferência de documentos."
        )

    reference = {r["_selection_key"]: r for r in snapshot}
    work_by_key = {r["_selection_key"]: r for r in work}
    ids = set()
    valid_nf_keys = set()
    valid_numbers = set()
    for key in selected_keys:
        selected = reference[key]
        item = work_by_key[key]
        nf = _number(selected.get("numero_nf"))
        if not nf or nf != _number(item.get("numero_nf")):
            raise ValueError("LOTE BLOQUEADO: número de NF divergente da seleção.")
        expected_doc = _digits(selected.get("cnpj"))
        actual_doc = _digits(item.get("cnpj_fornecedor"))
        if len(expected_doc) == 14 and actual_doc != expected_doc:
            raise ValueError(
                f"LOTE BLOQUEADO: NF {nf} tem CNPJ diferente da seleção."
            )
        file_id = str(item.get("file_id") or "").strip()
        if not file_id or file_id not in pdfs or file_id in ids:
            raise ValueError(
                f"LOTE BLOQUEADO: PDF da NF {nf} ausente, duplicado ou de outra carga."
            )
        ids.add(file_id)
        fiscal_key = _digits(item.get("chave_nfe"))
        if fiscal_key:
            if (len(fiscal_key) != 44 or fiscal_key[20:22] != "55"
                or _number(fiscal_key[25:34]) != nf
                or (len(actual_doc) == 14 and fiscal_key[6:20] != actual_doc)):
                raise ValueError(
                    f"LOTE BLOQUEADO: chave fiscal da NF {nf} não corresponde ao documento."
                )
            if fiscal_key in valid_nf_keys:
                raise ValueError("LOTE BLOQUEADO: chave de NF-e duplicada.")
            valid_nf_keys.add(fiscal_key)
        valid_numbers.add(nf)

    # CT-e XML pode referenciar NF-e recebida somente como PDF, sem chave
    # extraída. Aceitar a referência apenas se NF+CNPJ fiscal resolverem
    # EXATAMENTE um documento selecionado, sem chave conflitante.
    pdf_only_by_identity = {}
    for item in work:
        if not _digits(item.get("chave_nfe")):
            pair = (_number(item.get("numero_nf")),
                    _digits(item.get("cnpj_fornecedor")))
            if len(pair[1]) == 14:
                pdf_only_by_identity.setdefault(pair, []).append(item)

    auxiliary = auxiliary or {}
    cte_references = {
        _digits(ref) for cte in ctes for ref in cte.get("refs_nfe") or []
    }
    for key, aux in auxiliary.items():
        if (
            key not in cte_references or key != _digits(aux.get("chave"))
            or _number(key[25:34]) != _number(aux.get("numero"))
            or key[6:20] != _digits(aux.get("cnpj"))
            or not aux.get("bytes")
            or "REMESSA" not in str(aux.get("natureza_fiscal") or "").upper()
        ):
            raise ValueError(
                "LOTE BLOQUEADO: remessa auxiliar não corresponde ao XML "
                "referenciado por um CT-e selecionado."
            )
    cte_ids = set()
    for cte in ctes:
        cte_key = _digits(cte.get("chave_cte"))
        cte_id = cte_key or str(cte.get("cte_id") or "").strip()
        if not cte_id or cte_id in cte_ids:
            raise ValueError("LOTE BLOQUEADO: CT-e duplicado ou sem identificação.")
        cte_ids.add(cte_id)
        refs = {_digits(x) for x in cte.get("refs_nfe") or [] if _digits(x)}
        ids_linked = {str(x) for x in cte.get("linked_file_ids") or [] if str(x)}
        numbers = {_number(x) for x in cte.get("linked_nf_numbers") or [] if _number(x)}
        if refs:
            unverified = []
            for ref in refs:
                if len(ref) != 44 or ref[20:22] != "55":
                    unverified.append(ref)
                elif ref not in valid_nf_keys and ref not in auxiliary:
                    pair = (_number(ref[25:34]), ref[6:20])
                    if len(pdf_only_by_identity.get(pair, [])) != 1:
                        unverified.append(ref)
            if unverified:
                raise ValueError(
                    f"LOTE BLOQUEADO: CT-e {cte.get('numero_cte') or cte_id} "
                    "contém referência fiscal fora das NFs selecionadas."
                )
        elif not ids_linked or not ids_linked.issubset(ids):
            raise ValueError(
                f"LOTE BLOQUEADO: CT-e {cte.get('numero_cte') or cte_id} "
                "não tem vínculo seguro ao lote selecionado."
            )
        valid_cte_numbers = valid_numbers | {
            _number(aux.get("numero")) for key, aux in auxiliary.items()
            if key in refs
        }
        if numbers and not numbers.issubset(valid_cte_numbers):
            raise ValueError(
                f"LOTE BLOQUEADO: CT-e {cte.get('numero_cte') or cte_id} "
                "informa NFs fora da seleção."
            )


def cte_reference_coverage(
    cte: dict, selected_nfs: list[dict],
    auxiliary: dict[str, dict] | None = None,
) -> dict:
    """Exibe TODAS as NF-es citadas no XML, incluindo as não selecionadas.

    A referência só é considerada coberta se houver chave exata ou, para
    DANFE somente em PDF sem chave conhecida, número e CNPJ exatos e únicos.
    """
    refs = list(dict.fromkeys(
        _digits(key) for key in cte.get("refs_nfe") or [] if _digits(key)
    ))
    auxiliary = auxiliary or {}
    cited = []
    covered = []
    auxiliaries = []
    missing = []
    invalid = []
    for ref in refs:
        if len(ref) != 44 or ref[20:22] != "55":
            invalid.append(ref or "REFERÊNCIA INVÁLIDA")
            continue
        number = _number(ref[25:34])
        cnpj = ref[6:20]
        cited.append(number)
        exact = [
            row for row in selected_nfs
            if _digits(row.get("chave_nfe")) == ref
            and _number(row.get("numero_nf")) == number
            and _digits(row.get("cnpj_fornecedor")) == cnpj
        ]
        pdf_only = [
            row for row in selected_nfs
            if not _digits(row.get("chave_nfe"))
            and _number(row.get("numero_nf")) == number
            and _digits(row.get("cnpj_fornecedor")) == cnpj
        ]
        if len(exact) == 1 or (not exact and len(pdf_only) == 1):
            covered.append(number)
        elif (
            ref in auxiliary and _digits(auxiliary[ref].get("chave")) == ref
            and _digits(auxiliary[ref].get("cnpj")) == cnpj
            and _number(auxiliary[ref].get("numero")) == number
            and bool(auxiliary[ref].get("bytes"))
        ):
            auxiliaries.append(number)
        else:
            missing.append(number)
    return {
        "cited": cited, "covered": covered, "auxiliary": auxiliaries,
        "missing": missing, "invalid": invalid,
        "complete": bool(refs) and not missing and not invalid,
    }


def validate_zip_manifest(outputs: dict[str, bytes], manifest: list[dict]) -> None:
    """Audita o conteúdo dos ZIPs, não apenas seus contadores declarados."""
    expected = Counter(
        (str(item.get("arquivo_final") or ""), str(item.get("tipo_documento") or ""))
        for item in manifest
    )
    if not expected or any(not name for name, _ in expected):
        raise ValueError("LOTE BLOQUEADO: manifesto fiscal vazio ou inválido.")
    actual = Counter()
    for archive_name, data in outputs.items():
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                for member in archive.infolist():
                    if member.is_dir():
                        continue
                    if member.filename.lower().endswith(".pdf"):
                        typ = "CT-e" if archive_name.upper().startswith("CTE") else "NF-e"
                        actual[(PurePosixPath(member.filename).name, typ)] += 1
                    else:
                        raise ValueError("Arquivo inesperado dentro do ZIP fiscal.")
        except (zipfile.BadZipFile, OSError) as exc:
            raise ValueError("LOTE BLOQUEADO: ZIP fiscal corrompido.") from exc
    if actual != expected:
        raise ValueError(
            "LOTE BLOQUEADO: conteúdo do ZIP difere do manifesto fiscal. "
            "Nenhum arquivo foi liberado."
        )
