"""Impressão avulsa de NF-e e CT-e pela biblioteca fiscal privada da SETTA.

Esta rotina é independente dos lotes de pré-notas: não muda o estado de
processamento, o XML original nem confirma/envia documentos automaticamente.
"""
from __future__ import annotations

import base64
import io
import re
import zipfile
from datetime import date, datetime

import streamlit as st

import nf_xml_library
from cte_generator import cte_output_name, extract_cte_metadata, generate_dacte_pdf
from danfe_generator import (
    extract_danfe_metadata,
    extract_nfe_processing_data,
    generate_danfe_pdf,
    apply_operational_stamp,
)
from nf_processor import build_final_name, digits_only


MAX_SELECTED_NFE = 20
MAX_SELECTED_CTE = 40


def normalized_number(value: object) -> str:
    raw = str(value or "").strip()
    if not re.fullmatch(r"\d{1,9}", raw):
        raise ValueError("Informe apenas o número da NF-e (1 a 9 dígitos).")
    return raw.lstrip("0") or "0"


def safe_nfe_record(record: dict, raw: bytes) -> tuple[object, dict]:
    """Confere identidade completa do XML contra o resultado selecionado."""
    if len(raw) > nf_xml_library.MAX_XML or not raw:
        raise ValueError("XML da NF-e excede o limite permitido ou está vazio.")
    meta = extract_danfe_metadata(raw)
    info = extract_nfe_processing_data(raw)
    key = digits_only(record.get("chave"))
    if (len(key) != 44 or key[20:22] != "55" or meta.chave != key
            or digits_only(meta.cnpj_emitente) != digits_only(record.get("cnpj_emitente"))
            or normalized_number(meta.numero_nf) != normalized_number(record.get("numero"))
            or (meta.status_codigo and meta.status_codigo not in {"100", "150"})):
        raise ValueError(f"XML da NF-e {record.get('numero')} não corresponde à biblioteca.")
    return meta, info


def safe_cte_record(record: dict, raw: bytes, selected_nfe_keys: set[str],
                    validate_tomador, linked_rows: list[dict]) -> object:
    """CT-e deve referenciar uma NF-e selecionada e ter tomador SETTA."""
    if len(raw) > nf_xml_library.MAX_XML or not raw:
        raise ValueError("XML do CT-e excede o limite permitido ou está vazio.")
    meta = extract_cte_metadata(raw)
    key = digits_only(record.get("chave"))
    if (len(key) != 44 or key[20:22] != "57" or meta.chave != key
            or normalized_number(meta.numero) != normalized_number(record.get("numero"))
            or (meta.status_codigo and meta.status_codigo not in {"100", "150"})):
        raise ValueError(f"XML do CT-e {record.get('numero')} não corresponde à biblioteca.")
    refs = set(meta.refs_nfe) & selected_nfe_keys
    if not refs:
        raise ValueError("CT-e não referencia as NF-es selecionadas.")
    matching_rows = [r for r in linked_rows if r.get("chave_nfe") in refs]
    if not validate_tomador(meta.tomador_nome, meta.cnpj_tomador,
                            linked_rows=matching_rows):
        raise ValueError("Tomador do CT-e não corresponde ao grupo SETTA.")
    return meta


def _download_xml(record: dict) -> bytes:
    response = nf_xml_library.library_api("download", {"id": record["id"]}, timeout=35)
    raw = base64.b64decode(str(response.get("raw_base64") or ""), validate=True)
    if not raw or len(raw) > nf_xml_library.MAX_XML:
        raise ValueError("Arquivo XML não disponível ou acima do limite de tamanho.")
    return raw


def _clear_operation() -> None:
    for key in tuple(st.session_state.keys()):
        if key.startswith(("avulsa_nf_sel_", "avulsa_cte_sel_",
                           "avulsa_due_", "avulsa_stamp_")):
            st.session_state.pop(key, None)
    for key in ("avulsa_results", "avulsa_selected_signature", "avulsa_checked_ctes",
                "avulsa_documents", "avulsa_stage", "avulsa_outputs",
                "avulsa_checked_signature", "avulsa_stamp_choice", "avulsa_errors"):
        st.session_state.pop(key, None)


def _selected_nfs() -> list[dict]:
    return [
        r for r in (st.session_state.get("avulsa_results") or [])
        if st.session_state.get("avulsa_nf_sel_" + r["id"], False)
    ]


def _selected_signature(records: list[dict]) -> tuple[str, ...]:
    return tuple(sorted(str(r["chave"]) for r in records))


def _load_nfs(records: list[dict]) -> list[dict]:
    documents = []
    for record in records:
        raw = _download_xml(record)
        meta, info = safe_nfe_record(record, raw)
        documents.append({"record": record, "raw": raw, "meta": meta, "info": info})
    return documents


def _linked_ctes(records: list[dict], validate_tomador, company_sigla) -> tuple[list[dict], list[str]]:
    selected_keys = {digits_only(r["chave"]) for r in records}
    candidates = nf_xml_library.library_api(
        "cte_avulso", {"chaves_nfe": sorted(selected_keys)}, timeout=35
    ).get("cte") or []
    if len(candidates) > MAX_SELECTED_CTE:
        raise ValueError("A busca localizou CT-es acima do limite operacional. Reduza a seleção.")
    docs = _load_nfs(records)
    linked_rows = [
        {"chave_nfe": d["meta"].chave,
         "cnpj_destinatario": digits_only(d["info"].get("cnpj_destinatario")),
         "empresa_sigla": company_sigla(
             d["info"].get("destinatario"), d["info"].get("cnpj_destinatario"))}
        for d in docs
    ]
    valid, rejected = [], []
    for record in candidates:
        try:
            raw = _download_xml(record)
            meta = safe_cte_record(record, raw, selected_keys, validate_tomador, linked_rows)
            valid.append({"record": record, "raw": raw, "meta": meta})
        except Exception as exc:
            rejected.append(f"CT-e {record.get('numero')}: {exc}")
    return valid, rejected


def parse_br_date(value: object) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = str(value or "").strip()
    if not raw:
        return None
    for pattern in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw[:10], pattern).date()
        except ValueError:
            pass
    return None


def make_documents(documents: list[dict], selected_ctes: list[dict],
                   dates: dict[str, date], stamps: dict[str, dict] | None,
                   supplier_resolver) -> dict[str, bytes]:
    """Gera bytes somente após validar todos os nomes/dados obrigatórios."""
    if not documents or len(documents) > MAX_SELECTED_NFE:
        raise ValueError("Selecione entre 1 e 20 NF-es.")
    if len(selected_ctes) > MAX_SELECTED_CTE:
        raise ValueError("Limite de CT-es excedido.")
    stamps = stamps or {}
    names = set()
    plan = []
    suppliers = {}
    for doc in documents:
        meta, info = doc["meta"], doc["info"]
        supplier = supplier_resolver(meta.cnpj_emitente) or meta.emitente
        name = build_final_name(dates.get(meta.chave), meta.numero_nf, supplier)
        if not name:
            raise ValueError(f"Informe o vencimento válido da NF-e {meta.numero_nf}.")
        if name.casefold() in names:
            raise ValueError(f"Nome duplicado ({name}). Confira vencimentos e fornecedores.")
        names.add(name.casefold())
        suppliers[meta.chave] = supplier
        plan.append((name, doc, stamps.get(meta.chave)))
    for cte in selected_ctes:
        meta = cte["meta"]
        linked = [
            d["meta"] for d in documents if d["meta"].chave in meta.refs_nfe
        ]
        if not linked:
            raise ValueError(f"CT-e {meta.numero} perdeu o vínculo com as NF-es.")
        name = cte_output_name(meta, [d.numero_nf for d in linked],
                               suppliers.get(linked[0].chave, linked[0].emitente))
        if name.casefold() in names:
            raise ValueError(f"Nome de CT-e duplicado: {name}.")
        names.add(name.casefold())
        plan.append((name, cte, None))
    generated = {}
    for name, doc, stamp in plan:
        if "info" in doc:
            pdf = generate_danfe_pdf(doc["raw"])
            if stamp is not None:
                pdf = apply_operational_stamp(
                    pdf,
                    data_chegada=stamp["data_chegada"],
                    cr=stamp["cr"],
                    desc_cr=stamp["desc_cr"],
                    natureza=stamp["natureza"],
                    recebido_por=stamp["recebido_por"],
                )
        else:
            pdf = generate_dacte_pdf(doc["raw"])
        generated[name] = pdf
    return generated


def _zip_outputs(outputs: dict[str, bytes]) -> bytes:
    memory = io.BytesIO()
    with zipfile.ZipFile(memory, "w", zipfile.ZIP_DEFLATED) as archive:
        for filename, contents in outputs.items():
            archive.writestr(filename, contents)
    return memory.getvalue()


def render_page(resolve_stamp, supplier_resolver, validate_tomador, company_sigla) -> None:
    """Desenha busca, seleção, conferência CT-e, carimbo e downloads."""
    st.markdown("#### IMPRESSÃO AVULSA DE NF-e / CT-e")
    st.caption("Pesquisa exata na biblioteca XML. Não altera lotes, XMLs ou status de envio.")
    if not nf_xml_library._automatic_service_token() and not nf_xml_library._token():
        if not nf_xml_library._login_panel():
            return

    with st.form("avulsa_busca_form"):
        query = st.text_input("NÚMERO DA NF-e", placeholder="Ex.: 123456", key="avulsa_numero")
        search = st.form_submit_button("INICIAR BUSCA", type="primary",
                                      use_container_width=True)
    if search:
        try:
            number = normalized_number(query)
            response = nf_xml_library.library_api(
                "buscar_avulso", {"numero": number}, timeout=35
            )
            _clear_operation()
            candidates = response.get("nfe") or []
            st.session_state["avulsa_results"] = [
                x for x in candidates
                if str(x.get("tipo")) == "NFE"
                and normalized_number(x.get("numero")) == number
            ]
            st.session_state["avulsa_stage"] = "pesquisa"
        except Exception as exc:
            _clear_operation()
            st.error(f"Não foi possível pesquisar a NF-e: {exc}")

    results = st.session_state.get("avulsa_results")
    if results is None:
        return
    if not results:
        st.info("Nenhuma NF-e correspondente ao número informado foi encontrada.")
        return

    st.markdown(f"**{len(results)} NF-e(s) encontrada(s)**")
    for record in results:
        key = str(record.get("chave") or "")
        st.checkbox(
            f"NF-e {record.get('numero')} · Série {key[22:25] if len(key)==44 else '—'}"
            f" · Emitente CNPJ {record.get('cnpj_emitente') or '—'}"
            f" · Chave {key}",
            key="avulsa_nf_sel_" + record["id"],
        )

    selected = _selected_nfs()
    signature = _selected_signature(selected)
    if signature != st.session_state.get("avulsa_selected_signature"):
        st.session_state["avulsa_selected_signature"] = signature
        st.session_state["avulsa_checked_ctes"] = []
        st.session_state["avulsa_checked_signature"] = ()
        st.session_state["avulsa_documents"] = []
        st.session_state["avulsa_outputs"] = {}
        st.session_state["avulsa_stage"] = "pesquisa"
    if len(selected) > MAX_SELECTED_NFE:
        st.error(f"Selecione no máximo {MAX_SELECTED_NFE} NF-es por operação.")
        return
    c1, c2 = st.columns(2)
    if c1.button("VERIFICAR CT-e", disabled=not selected,
                 use_container_width=True, key="avulsa_verificar_cte"):
        try:
            with st.spinner("Conferindo vínculo fiscal e tomador dos CT-es..."):
                ctes, rejected = _linked_ctes(selected, validate_tomador, company_sigla)
            st.session_state["avulsa_checked_ctes"] = ctes
            st.session_state["avulsa_checked_signature"] = signature
            st.session_state["avulsa_errors"] = rejected
        except Exception as exc:
            st.session_state["avulsa_checked_signature"] = ()
            st.session_state["avulsa_checked_ctes"] = []
            st.error(f"Falha ao verificar CT-e: {exc}")

    checked = st.session_state.get("avulsa_checked_signature") == signature
    if checked:
        ctes = st.session_state.get("avulsa_checked_ctes") or []
        if ctes:
            st.markdown(f"**CT-es com tomador SETTA ({len(ctes)})**")
            for item in ctes:
                meta = item["meta"]
                st.checkbox(
                    f"CT-e {meta.numero} · {meta.emitente} · Chave {meta.chave}",
                    key="avulsa_cte_sel_" + meta.chave,
                )
        else:
            st.info("Nenhum CT-e elegível foi encontrado para as NF-es selecionadas.")
        for error in (st.session_state.get("avulsa_errors") or []):
            st.warning(error)

    if c2.button("GERAR DOCUMENTOS", disabled=not selected,
                 type="primary", use_container_width=True,
                 key="avulsa_preparar_geracao"):
        try:
            with st.spinner("Validando os XMLs selecionados..."):
                docs = _load_nfs(selected)
            st.session_state["avulsa_documents"] = docs
            st.session_state["avulsa_stage"] = "carimbo"
            st.session_state["avulsa_outputs"] = {}
        except Exception as exc:
            st.error(f"Não foi possível preparar os documentos: {exc}")

    if st.session_state.get("avulsa_stage") not in {"carimbo", "downloads"}:
        return

    if st.session_state["avulsa_stage"] == "downloads":
        outputs = st.session_state.get("avulsa_outputs") or {}
        st.success(f"{len(outputs)} documento(s) gerado(s) para download.")
        if len(outputs) > 1:
            st.download_button(
                "BAIXAR TODOS (ZIP)", _zip_outputs(outputs),
                file_name="IMPRESSAO_AVULSA_NFE_CTE.zip", mime="application/zip",
                use_container_width=True, type="primary",
                key="avulsa_baixar_zip", on_click="ignore",
            )
        for index, (filename, content) in enumerate(outputs.items()):
            st.download_button(
                f"BAIXAR · {filename}", content, file_name=filename,
                mime="application/pdf", use_container_width=True,
                key=f"avulsa_baixar_{index}", on_click="ignore",
            )
        return

    docs = st.session_state.get("avulsa_documents") or []
    st.markdown("#### CONFERÊNCIA ANTES DA GERAÇÃO")
    add_stamp = st.radio(
        "Deseja inserir o carimbo de controle interno nas NF-es?",
        ["Não, sem carimbo", "Sim, inserir carimbo"],
        horizontal=True, key="avulsa_stamp_choice",
    ) == "Sim, inserir carimbo"
    st.caption("Vencimento é obrigatório para manter o padrão atual de renomeação.")
    date_values, stamp_values, problems = {}, {}, []
    for index, doc in enumerate(docs):
        meta, info = doc["meta"], doc["info"]
        with st.expander(f"NF-e {meta.numero_nf} · {meta.emitente}", expanded=True):
            default_due = info.get("vencimento")
            due = st.text_input(
                "DATA DE VENCIMENTO (DD/MM/AAAA)",
                value=default_due.strftime("%d/%m/%Y") if default_due else "",
                key="avulsa_due_" + meta.chave,
            )
            due_date = parse_br_date(due)
            if not due_date:
                problems.append(f"NF-e {meta.numero_nf}: vencimento não informado/inválido.")
            else:
                date_values[meta.chave] = due_date
            if add_stamp:
                defaults = resolve_stamp(meta, info) or {}
                fields = {}
                for field, label in [
                    ("data_chegada", "DATA DE CHEGADA (DD/MM/AAAA)"),
                    ("cr", "CR"), ("desc_cr", "DESCRIÇÃO CR"),
                    ("natureza", "NATUREZA INTERNA"),
                    ("recebido_por", "RECEBIDO POR"),
                ]:
                    initial = defaults.get(field) or ""
                    if isinstance(initial, date):
                        initial = initial.strftime("%d/%m/%Y")
                    fields[field] = st.text_input(
                        label, value=str(initial),
                        key=f"avulsa_stamp_{field}_{meta.chave}",
                    ).strip()
                stamp_date = parse_br_date(fields["data_chegada"])
                if stamp_date is None:
                    problems.append(f"NF-e {meta.numero_nf}: data de chegada inválida.")
                elif any(not fields[f] for f in ("cr", "desc_cr", "natureza", "recebido_por")):
                    problems.append(f"NF-e {meta.numero_nf}: preencha todos os campos do carimbo.")
                else:
                    fields["data_chegada"] = stamp_date
                    stamp_values[meta.chave] = fields

    if st.button(
        "SALVAR CARIMBO E GERAR DOCUMENTOS" if add_stamp else "GERAR PDFs SEM CARIMBO",
        type="primary", use_container_width=True, key="avulsa_confirmar_geracao",
    ):
        if problems:
            for problem in problems:
                st.error(problem)
            return
        cte_selected = []
        if checked:
            cte_selected = [
                item for item in st.session_state.get("avulsa_checked_ctes") or []
                if st.session_state.get("avulsa_cte_sel_" + item["meta"].chave, False)
            ]
        try:
            with st.spinner("Gerando DANFEs e DACTEs no padrão SETTA..."):
                outputs = make_documents(
                    docs, cte_selected, date_values,
                    stamp_values if add_stamp else None, supplier_resolver,
                )
            if add_stamp:
                st.session_state.setdefault("avulsa_carimbos_salvos", {}).update(stamp_values)
            st.session_state["avulsa_outputs"] = outputs
            st.session_state["avulsa_stage"] = "downloads"
            st.rerun()
        except Exception as exc:
            st.error(f"Falha ao gerar documentos: {exc}")
