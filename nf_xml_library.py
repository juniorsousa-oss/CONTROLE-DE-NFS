"""Biblioteca privada de XMLs NF-e/CT-e da Central SETTA.

O Streamlit só utiliza chave pública. Todas as operações de escrita/leitura de XML
ocorrem na Edge Function com sessão e permissão verificadas no servidor.
"""
from __future__ import annotations

import base64
import hashlib
import io
import re
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter
from pathlib import PurePosixPath
from xml.etree import ElementTree as ET
from rapidfuzz import fuzz
from nf_processor import normalize_text

import pandas as pd
import requests
import streamlit as st

import db

MAX_XML=4*1024*1024
MAX_ZIP=120*1024*1024
MAX_TOTAL_EXPANDED=200*1024*1024
MAX_FILES=1500


def _call(action:str,payload:dict|None=None,timeout:int=70):
    url=f"{db.supabase_url().rstrip('/')}/functions/v1/nf-xml-library-api"
    response=requests.post(url,headers={
        "apikey":db.supabase_key(),
        "Authorization":f"Bearer {db.supabase_key()}",
        "Content-Type":"application/json",
    },json={"action":action,"payload":payload or {}},timeout=timeout)
    try:
        result=response.json()
    except ValueError:
        raise RuntimeError(f"Biblioteca XML indisponível (HTTP {response.status_code}).") from None
    if not response.ok or not result.get("ok"):
        raise RuntimeError(str(result.get("error") or f"HTTP {response.status_code}"))
    return result.get("data") or {}


def _session():
    return st.session_state.get("nf_xml_library_auth") or {}


def _token():
    return str(_session().get("token") or "")


def _automatic_service_token():
    # Exclusivo do servidor Streamlit, nunca incluído em URL, widget ou HTML.
    return db._secret("NF_XML_AUTOMATION_TOKEN")


def library_api(action:str,values:dict|None=None,timeout:int=70):
    # A consulta do lote é automática via credencial de serviço restrita.
    # Para importar, consultar o catálogo ou gerir pessoas, login humano persiste.
    if action in {"match","download"} and _automatic_service_token():
        return _call(action,{
            "service_token":_automatic_service_token(),**(values or {})
        },timeout=timeout)
    if not _token():
        raise RuntimeError("Biblioteca XML ainda não autorizada nesta sessão.")
    return _call(action,{"token":_token(),**(values or {})},timeout=timeout)


def _login_panel():
    if _token():
        user=_session()
        c1,c2=st.columns([4,1])
        c1.caption(f"USUÁRIO SETTA · {user.get('nome','')} · {user.get('perfil','')}")
        if c2.button("SAIR DA BIBLIOTECA",key="nf_xml_library_logout"):
            try:library_api("logout")
            except Exception:pass
            st.session_state.pop("nf_xml_library_auth",None)
            st.session_state.pop("nf_xml_auto_signature",None)
            st.rerun()
        return True
    st.info("Para importar e consultar XMLs, autentique-se com seu usuário SETTA. Somente usuários autorizados podem abrir documentos fiscais.")
    with st.form("nf_xml_library_login"):
        username=st.text_input("USUÁRIO / E-MAIL SETTA")
        password=st.text_input("SENHA",type="password")
        login=st.form_submit_button("ENTRAR NA BIBLIOTECA",type="primary",use_container_width=True)
    if login:
        try:
            result=_call("login",{"login":username.strip(),"password":password},timeout=35)
            st.session_state.nf_xml_library_auth=result
            st.rerun()
        except Exception as exc:
            st.error("Não foi possível acessar a biblioteca: "+str(exc))
    return False


def _read_xml_uploads(uploaded):
    """XMLs individuais ou ZIP; elimina zip-slip, zip-bomb e arquivos não XML."""
    total=0
    entries=[]
    errors=[]
    for upload in uploaded:
        name=str(upload.name or "")
        size=int(getattr(upload,"size",0) or 0)
        if name.lower().endswith(".xml"):
            if size>MAX_XML:
                errors.append(f"{name}: arquivo maior que 4 MB.")
                continue
            raw=upload.getvalue()
            if not raw or len(raw)>MAX_XML:
                errors.append(f"{name}: XML vazio ou acima do limite.")
            else:
                entries.append((PurePosixPath(name.replace("\\","/")).name,raw))
        elif name.lower().endswith(".zip"):
            if size>MAX_ZIP:
                errors.append(f"{name}: ZIP maior que 120 MB.")
                continue
            try:
                with zipfile.ZipFile(io.BytesIO(upload.getvalue())) as z:
                    for member in z.infolist():
                        if member.is_dir() or not member.filename.lower().endswith(".xml"):
                            continue
                        path=PurePosixPath(member.filename.replace("\\","/"))
                        if path.is_absolute() or ".." in path.parts:
                            errors.append(f"{member.filename}: caminho inseguro.")
                            continue
                        if member.file_size>MAX_XML:
                            errors.append(f"{path.name}: XML maior que 4 MB.")
                            continue
                        total+=member.file_size
                        if total>MAX_TOTAL_EXPANDED or len(entries)>=MAX_FILES:
                            raise ValueError("ZIP excede 1.500 XMLs ou 200 MB de dados descompactados.")
                        if member.compress_size and member.file_size/max(1,member.compress_size)>500:
                            errors.append(f"{path.name}: taxa de compressão suspeita.")
                            continue
                        entries.append((path.name,z.read(member)))
            except (zipfile.BadZipFile,ValueError,RuntimeError) as exc:
                errors.append(f"{name}: {exc}")
        else:
            errors.append(f"{name}: somente XML ou ZIP.")
    # O mesmo XML em pastas diferentes é enviado uma única vez por carga.
    unique=[]
    seen=set()
    for name,raw in entries:
        fingerprint=hashlib.sha256(raw).hexdigest()
        if fingerprint not in seen:
            seen.add(fingerprint)
            unique.append((name,raw))
        else:
            errors.append(f"DUPLICADO NA CARGA | {name}: conteúdo repetido dentro da seleção.")
    return unique,errors


def _fiscal_key(raw: bytes) -> str:
    """Extrai somente a chave fiscal para pré-consulta; validação completa fica na API."""
    for tag, prefix, model in ((b"infNFe", b"NFe", b"55"), (b"infCte", b"CTe", b"57")):
        # O atributo Id pode estar em qualquer posição, com quebra de linha.
        pattern = (
            rb"<(?:[A-Za-z_][\w.-]*:)?" + tag +
            rb"\b[^>]{0,1200}?\bId\s*=\s*['\"]" + prefix +
            rb"([0-9]{44})['\"]"
        )
        match = re.search(pattern, raw)
        if match and match.group(1)[20:22] == model:
            return match.group(1).decode("ascii")
    return ""


def _preflight_files(files):
    """Consulta por chave e hash sem transmitir bytes de XML ao Supabase."""
    hashed = [
        {"filename": filename, "raw": raw, "sha256": hashlib.sha256(raw).hexdigest(),
         "chave": _fiscal_key(raw)}
        for filename, raw in files
    ]
    by_key = {}
    for item in hashed:
        if item["chave"]:
            by_key.setdefault(item["chave"], []).append(item)

    # Chave igual com conteúdos diferentes na MESMA carga exige revisão,
    # independentemente do que já exista na biblioteca.
    conflicts = {
        key for key,group in by_key.items()
        if len({entry["sha256"] for entry in group}) > 1
    }
    candidates = [item for item in hashed if item["chave"] and item["chave"] not in conflicts]
    requested = [
        {"chave": item["chave"], "sha256": item["sha256"]}
        for item in candidates
    ]
    states = {}
    for start in range(0, len(requested), 200):
        batch = requested[start:start+200]
        response = library_api("check_existing", {"items": batch}, timeout=60)
        for state in response.get("results") or []:
            if state.get("status") not in ("NOVO","DUPLICADO","CONFLITO"):
                raise RuntimeError("A biblioteca retornou um estado de conferência desconhecido.")
            states[str(state["chave"])] = str(state["status"])
        if any(item["chave"] not in states for item in batch):
            raise RuntimeError("Resposta incompleta da biblioteca ao conferir as chaves.")

    uploads,results = [],[]
    for item in hashed:
        filename,key=item["filename"],item["chave"]
        if key in conflicts:
            results.append({"ARQUIVO":filename,"RESULTADO":"CONFLITO",
                            "INFORMAÇÃO":f"Chave {key} com arquivos diferentes na mesma carga. Revisão necessária."})
        elif key and states.get(key) in ("DUPLICADO","CONFLITO"):
            status=states[key]
            results.append({"ARQUIVO":filename,"RESULTADO":status,
                            "INFORMAÇÃO":key if status=="DUPLICADO"
                            else f"Chave {key}: biblioteca já possui conteúdo diferente."})
        else:
            uploads.append(item)
    return uploads,results


def _upload_new_xml(item:dict,url:str,headers:dict,token:str):
    """Thread sem chamadas ao Streamlit; só a API controla acesso e duplicidade."""
    filename=item["filename"]
    try:
        raw=base64.b64encode(item["raw"]).decode("ascii")
        response=requests.post(
            url,headers=headers,
            json={"action":"ingest","payload":{
                "token":token,"filename":filename,"raw_base64":raw,
            }},
            timeout=(10,90),
        )
        try: result=response.json()
        except ValueError:
            raise RuntimeError(f"Resposta inválida do servidor (HTTP {response.status_code})")
        if not response.ok or not result.get("ok"):
            raise RuntimeError(str(result.get("error") or f"HTTP {response.status_code}"))
        data=result.get("data") or {}
        return {
            "ARQUIVO":filename,"RESULTADO":str(data.get("resultado") or "ERRO"),
            "INFORMAÇÃO":str(data.get("chave") or ""),
        }
    except Exception as exc:
        return {"ARQUIVO":filename,"RESULTADO":"ERRO","INFORMAÇÃO":str(exc)[:300]}


def _make_report(uploaded:list):
    files,errors=_read_xml_uploads(uploaded)
    records=[]
    for error in errors:
        duplicate=error.startswith("DUPLICADO NA CARGA |")
        records.append({
            "ARQUIVO":"—","RESULTADO":"DUPLICADO" if duplicate else "INVÁLIDO",
            "INFORMAÇÃO":error.replace("DUPLICADO NA CARGA | ",""),
        })
    if not files:
        return pd.DataFrame(records,columns=["ARQUIVO","RESULTADO","INFORMAÇÃO"])

    with st.spinner(f"Conferindo {len(files)} XMLs na biblioteca antes do envio..."):
        try:
            to_upload,checked=_preflight_files(files)
        except Exception as exc:
            records.append({
                "ARQUIVO":"—","RESULTADO":"ERRO",
                "INFORMAÇÃO":f"Conferência prévia indisponível: {exc}. Nenhum XML foi enviado.",
            })
            return pd.DataFrame(records,columns=["ARQUIVO","RESULTADO","INFORMAÇÃO"])
    records.extend(checked)

    st.caption(
        f"CONFERÊNCIA PRÉVIA · {len(files)} arquivos únicos · "
        f"{len(checked)} já existentes/conflitantes · "
        f"{len(to_upload)} para envio"
    )
    if not to_upload:
        return pd.DataFrame(records,columns=["ARQUIVO","RESULTADO","INFORMAÇÃO"])

    # Credenciais e URL são obtidas na thread principal; workers não acessam
    # st.session_state nem st.secrets, preservando o contexto do Streamlit.
    token=_token()
    url=f"{db.supabase_url().rstrip('/')}/functions/v1/nf-xml-library-api"
    key=db.supabase_key()
    headers={
        "apikey":key,"Authorization":f"Bearer {key}",
        "Content-Type":"application/json",
    }
    progress=st.progress(0,text=f"Enviando somente os {len(to_upload)} XMLs novos...")
    completed=0
    with ThreadPoolExecutor(max_workers=min(5,len(to_upload))) as executor:
        futures=[
            executor.submit(_upload_new_xml,item,url,headers,token)
            for item in to_upload
        ]
        for future in as_completed(futures):
            records.append(future.result())
            completed+=1
            progress.progress(
                completed/len(to_upload),
                text=f"Enviados {completed}/{len(to_upload)} · "
                     f"{len(files)-len(to_upload)} ignorados na pré-consulta",
            )
    progress.empty()
    return pd.DataFrame(records,columns=["ARQUIVO","RESULTADO","INFORMAÇÃO"])

def render_page():
    st.markdown("## BIBLIOTECA DE XMLs")
    st.caption("CENTRAL SETTA · NF-e / CT-e · ARMAZENAMENTO PRIVADO · ALIMENTAÇÃO MANUAL E FUTURA API")
    if not _login_panel():return

    tab_upload,tab_documents,tab_access=st.tabs(["IMPORTAR XMLs","DOCUMENTOS ARMAZENADOS","PERMISSÕES"])
    with tab_upload:
        st.markdown("#### IMPORTAR PASTA OU ZIP")
        st.caption("Selecione vários XMLs ou um ZIP. O sistema confere as chaves fiscais primeiro e envia somente arquivos novos. Cargas repetidas não substituem documentos já armazenados.")
        with st.form("nf_xml_library_import_form",clear_on_submit=True):
            uploads=st.file_uploader(
                "XMLs NF-e / CT-e ou ZIP",type=["xml","zip"],
                accept_multiple_files=True,key="nf_xml_library_files",
            )
            upload=st.form_submit_button("IMPORTAR PARA A BIBLIOTECA",type="primary",use_container_width=True)
        if upload:
            if not uploads:st.warning("Selecione ao menos um arquivo XML ou ZIP.")
            else:
                report=_make_report(uploads)
                st.session_state.nf_xml_last_report=report
                st.session_state.pop("nf_xml_library_index",None)
                st.session_state.pop("nf_xml_auto_signature",None)
        report=st.session_state.get("nf_xml_last_report")
        if isinstance(report,pd.DataFrame) and not report.empty:
            counts=report["RESULTADO"].value_counts().to_dict()
            cols=st.columns(4)
            for c,(key,title) in zip(cols,[("INCLUIDO","INCLUÍDOS"),("DUPLICADO","IGNORADOS · JÁ EXISTEM"),("CONFLITO","CONFLITOS"),("ERRO","FALHAS")]):
                c.metric(title,int(counts.get(key,0)))
            st.dataframe(report,hide_index=True,use_container_width=True,height=min(500,95+35*len(report)))
            st.download_button("EXPORTAR RELATÓRIO DE IMPORTAÇÃO",report.to_csv(index=False,sep=";").encode("utf-8-sig"),"biblioteca_xml_importacao.csv","text/csv",use_container_width=True)

    with tab_documents:
        # O índice antigo retornava somente 300 registros e fazia parecer que
        # a biblioteca não possuía todos os XMLs. Totais agora são globais e
        # a pesquisa/paginação são executadas diretamente no banco.
        if "nf_xml_doc_page" not in st.session_state:
            st.session_state.nf_xml_doc_page=1
        left,right=st.columns([3,1])
        left.markdown("#### ACERVO XML ARMAZENADO")
        refresh=right.button(
            "ATUALIZAR CONSULTA",key="nf_xml_refresh_list",use_container_width=True,
        )
        if refresh:
            st.session_state.pop("nf_xml_library_index",None)
            st.session_state.pop("nf_xml_doc_request",None)

        with st.form("nf_xml_search_catalog_form"):
            search_col,type_col,button_col=st.columns([2.5,1,1])
            typed_search=search_col.text_input(
                "PESQUISAR NÚMERO, CHAVE, EMITENTE OU ARQUIVO",
                value=str(st.session_state.get("nf_xml_doc_filter_search") or ""),
                placeholder="Pesquisa em toda a biblioteca",
            )
            typed_type=type_col.selectbox(
                "TIPO DE DOCUMENTO",["TODOS","NFE","CTE"],
                index=["TODOS","NFE","CTE"].index(
                    str(st.session_state.get("nf_xml_doc_filter_type") or "TODOS")
                ),
            )
            search_now=button_col.form_submit_button(
                "PESQUISAR",type="primary",use_container_width=True,
            )
        if search_now:
            st.session_state.nf_xml_doc_filter_search=typed_search.strip()
            st.session_state.nf_xml_doc_filter_type=typed_type
            st.session_state.nf_xml_doc_page=1
            st.session_state.pop("nf_xml_library_index",None)

        search=str(st.session_state.get("nf_xml_doc_filter_search") or "")
        kind=str(st.session_state.get("nf_xml_doc_filter_type") or "TODOS")
        requested_page=int(st.session_state.get("nf_xml_doc_page") or 1)
        request_signature=(requested_page,search,kind)
        try:
            if (
                st.session_state.get("nf_xml_doc_request")!=request_signature
                or "nf_xml_library_index" not in st.session_state
            ):
                st.session_state.nf_xml_library_index=library_api("list",{
                    "page":requested_page,
                    "page_size":100,
                    "search":search,
                    "tipo":kind,
                })
                st.session_state.nf_xml_doc_request=request_signature
            index=st.session_state.nf_xml_library_index
            documents=index.get("documentos") or []
            imports=index.get("historico") or []
            count=int(index.get("total") or 0)
            nfe=int(index.get("total_nfe") or 0)
            cte=int(index.get("total_cte") or 0)
            filtered=int(index.get("filtered_total") or 0)
            last_page=max(1,int(index.get("page_count") or 1))
            displayed_page=int(index.get("page") or requested_page)
            page_size=max(1,int(index.get("page_size") or 100))
            a,b,c=st.columns(3)
            a.metric("TOTAL DE XMLs NA BIBLIOTECA",count)
            b.metric("NF-e ARMAZENADAS",nfe)
            c.metric("CT-e ARMAZENADOS",cte)
            if search or kind!="TODOS":
                st.caption(f"FILTROS ATIVOS · {filtered} DOCUMENTOS ENCONTRADOS EM TODO O ACERVO")
            first=(displayed_page-1)*page_size+1 if filtered else 0
            last=min(displayed_page*page_size,filtered)
            st.caption(
                f"EXIBINDO {first} A {last} DE {filtered} · "
                f"PÁGINA {displayed_page} DE {last_page}"
            )
            if documents:
                data=pd.DataFrame(documents)[[
                    "tipo","numero","chave","cnpj_emitente",
                    "cnpj_destinatario","arquivo_nome","origem","importado_em"
                ]]
                data.columns=[
                    "TIPO","NÚMERO","CHAVE","CNPJ EMITENTE",
                    "CNPJ DESTINATÁRIO","ARQUIVO","ORIGEM","IMPORTADO EM"
                ]
                st.dataframe(
                    data,hide_index=True,use_container_width=True,
                    height=min(500,95+35*len(data)),
                )
            else:
                st.info("Nenhum documento encontrado para os filtros selecionados.")

            prev_col,page_col,next_col=st.columns([1,2,1])
            if prev_col.button(
                "PÁGINA ANTERIOR",key="nf_xml_doc_previous",
                disabled=displayed_page<=1,use_container_width=True,
            ):
                st.session_state.nf_xml_doc_page=displayed_page-1
                st.rerun()
            page_col.markdown(
                f"<div style='text-align:center;padding:10px'>"
                f"PÁGINA {displayed_page} / {last_page}</div>",
                unsafe_allow_html=True,
            )
            if next_col.button(
                "PRÓXIMA PÁGINA",key="nf_xml_doc_next",
                disabled=displayed_page>=last_page,use_container_width=True,
            ):
                st.session_state.nf_xml_doc_page=displayed_page+1
                st.rerun()
            if imports:
                with st.expander("ÚLTIMOS REGISTROS DE IMPORTAÇÃO"):
                    st.dataframe(
                        pd.DataFrame(imports),
                        use_container_width=True,hide_index=True,
                    )
        except Exception as exc:
            st.error("Erro ao consultar a biblioteca: "+str(exc))

    with tab_access:
        if _session().get("perfil")!="ADMIN":
            st.info("Somente administradores gerenciam permissões.")
        else:
            try:
                users=library_api("users")
                available=[x for x in users if x.get("is_active") and x.get("xml_perfil")!="ADMIN"]
                if not available:
                    st.info("Não há operadores elegíveis cadastrados no OperaHub.")
                else:
                    options={
                        f"{x.get('full_name') or x.get('username')} · {x.get('username')} · {x.get('xml_perfil')}":x["id"]
                        for x in available
                    }
                    with st.form("nf_xml_grant_form"):
                        selected=st.selectbox("COLABORADOR",list(options.keys()))
                        permission=st.radio("ACESSO",["OPERADOR","SEM_ACESSO"],horizontal=True)
                        apply=st.form_submit_button("SALVAR PERMISSÃO",type="primary")
                    if apply:
                        library_api("grant",{"user_id":options[selected],"perfil":permission})
                        st.success("Permissão atualizada. O próximo acesso utilizará a regra nova.")
                        st.rerun()
            except Exception as exc:st.error("Não foi possível carregar permissões: "+str(exc))


def _simple_nf(value):
    ds=re.sub(r"\D","",str(value or ""))
    return ds.lstrip("0") or "0"



def _validate_name_fallback(record: dict, raw: bytes) -> bool:
    """Valida candidato SEM CNPJ: número, chave e emitente devem concordar."""
    reference = normalize_text(str(record.get("fornecedor_referencia") or ""))
    if not reference or len(reference) < 6 or b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        return False
    if len(raw) > MAX_XML:
        return False
    try:
        xml = ET.fromstring(raw)
        inf = xml.find(".//{*}infNFe")
        if inf is None:
            return False
        emitted = inf.findtext("./{*}emit/{*}xNome", default="")
        cnpj = re.sub(r"\D", "", inf.findtext("./{*}emit/{*}CNPJ", default=""))
        number = _simple_nf(inf.findtext("./{*}ide/{*}nNF", default=""))
        key = re.sub(r"\D", "", str(inf.attrib.get("Id") or ""))
        if (number != _simple_nf(record.get("numero")) or
                len(cnpj) != 14 or cnpj != re.sub(r"\D", "",str(record.get("cnpj_emitente") or "")) or
                key != re.sub(r"\D", "",str(record.get("chave") or "")) or
                key[20:22] != "55"):
            return False
        name = normalize_text(emitted)
        if not name or len(name) < 6:
            return False
        if reference == name:
            return True
        a, b = set(reference.split()), set(name.split())
        common = a & b
        if len(common) < 2:
            return False
        score = int(round(
            fuzz.token_set_ratio(reference, name) * .55 +
            fuzz.token_sort_ratio(reference, name) * .45
        ))
        return score >= 88 and len(common) / max(1, max(len(a), len(b))) >= .55
    except (ET.ParseError, ValueError, TypeError):
        return False


def prefill_stage2(pending_pre: pd.DataFrame):
    """Match a seleção uma vez e recupera XMLs em paralelo, preservando êxitos."""
    service_token = _automatic_service_token()
    session_token = _token()
    if not service_token and not session_token:
        st.warning("INTEGRAÇÃO DE XMLs NÃO CONFIGURADA. Upload manual disponível.")
        return
    if not isinstance(pending_pre, pd.DataFrame) or pending_pre.empty:
        return
    requests_nfs = []
    for _, row in pending_pre.iterrows():
        numero = _simple_nf(row.get("numero_nf"))
        cnpj = re.sub(r"\D", "", str(row.get("cnpj") or ""))
        chave = re.sub(r"\D", "", str(row.get("chave_nfe") or ""))
        supplier = str(row.get("fornecedor") or row.get("fornecedor_validacao") or "").strip()
        if numero != "0" and (len(cnpj) == 14 or len(chave) == 44 or supplier):
            requests_nfs.append({
                "numero": numero, "cnpj": cnpj, "chave": chave, "fornecedor": supplier,
            })
    if not requests_nfs:
        return
    fingerprint = hashlib.sha256(
        repr(sorted((x["numero"], x["cnpj"], x["chave"], x["fornecedor"]) for x in requests_nfs)).encode()
    ).hexdigest()
    # Este método é invocado exclusivamente pelo botão da etapa 2.
    # Nenhum widget adicional ou consulta automática durante render.
    target = f"{'SERVICO' if service_token else 'SESSAO'}:{fingerprint}"
    if st.session_state.get("nf_xml_auto_signature") == target:
        linked = st.session_state.get("nf_xml_auto_stats") or {}
        if linked:
            st.caption(
                f"BIBLIOTECA · {linked.get('nfe', 0)} NF-e e "
                f"{linked.get('cte', 0)} CT-e encontrados · "
                f"{linked.get('missing', 0)} NF(s) ainda sem XML."
            )
            if linked.get("pending_name"):
                st.warning(
                    f"{linked['pending_name']} NF(s) com XML encontrado pelo número, "
                    "mas emitente não confirmado. Requer conferência manual."
                )
            if linked.get("download_errors"):
                st.warning(
                    f"{linked['download_errors']} documento(s) falharam na busca. "
                    "Clique novamente em INICIAR BUSCA DE DOCUMENTOS."
                )
        return

    # Credenciais obtidas apenas na thread principal; workers não usam Streamlit.
    url = f"{db.supabase_url().rstrip('/')}/functions/v1/nf-xml-library-api"
    key = db.supabase_key()
    headers = {
        "apikey": key, "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    credential = (
        {"service_token": service_token} if service_token
        else {"token": session_token}
    )

    def download_one(record: dict) -> tuple[str, bytes]:
        response = requests.post(
            url, headers=headers,
            json={"action": "download", "payload": {**credential, "id": record["id"]}},
            timeout=(8, 25),
        )
        try:
            answer = response.json()
        except ValueError:
            raise RuntimeError(f"Resposta inválida (HTTP {response.status_code})") from None
        if not response.ok or not answer.get("ok"):
            raise RuntimeError(str(answer.get("error") or f"HTTP {response.status_code}"))
        data = answer.get("data") or {}
        raw = base64.b64decode(data.get("raw_base64") or "", validate=True)
        if not raw:
            raise ValueError("XML vazio na biblioteca.")
        filename = str(
            data.get("filename") or record.get("arquivo_nome")
            or (str(record.get("chave") or record["id"]) + ".xml")
        )
        return filename, raw

    try:
        with st.spinner("Buscando XMLs vinculados à seleção na biblioteca..."):
            matched = library_api("match", {"nfs": requests_nfs}, timeout=25)
        cached = list(st.session_state.get("document_upload_cache") or [])
        existing_hashes = {
            hashlib.sha256(x.get("raw") or b"").hexdigest() for x in cached
        }
        existing_ids = {
            str(x.get("library_id") or "")
            for x in cached if x.get("library_id")
        }
        cte_candidates = list(matched.get("cte") or [])
        cte_expected_keys = sorted({
            re.sub(r"\D", "", str(item.get("chave") or ""))
            for item in cte_candidates
            if len(re.sub(r"\D", "", str(item.get("chave") or ""))) == 44
        })
        records = [
            item for item in (matched.get("nfe") or []) + cte_candidates
            if str(item.get("id") or "") not in existing_ids
        ]
        fallback = [
            dict(item, _verify_name=True)
            for item in (matched.get("candidatos_sem_cnpj") or [])
            if str(item.get("id") or "") not in existing_ids
        ]
        records.extend(fallback)
        imported = 0
        failures = []
        pending_name = []
        if records:
            with st.spinner(f"Recuperando {len(records)} XML(s) em paralelo..."):
                with ThreadPoolExecutor(max_workers=min(4, len(records))) as executor:
                    jobs = {
                        executor.submit(download_one, item): item for item in records
                    }
                    for future in as_completed(jobs):
                        item = jobs[future]
                        try:
                            name, raw = future.result()
                            if item.get("_verify_name") and not _validate_name_fallback(item, raw):
                                pending_name.append(str(item.get("numero") or ""))
                                continue
                            digest = hashlib.sha256(raw).hexdigest()
                            if digest not in existing_hashes:
                                cached.append({
                                    "name": name, "raw": raw, "ext": ".xml",
                                    "origem": "BIBLIOTECA",
                                    "library_id": str(item["id"]),
                                })
                                existing_hashes.add(digest)
                                imported += 1
                        except Exception as exc:
                            failures.append(
                                f"{item.get('arquivo_nome') or item.get('chave') or item.get('id')}: {exc}"
                            )
        st.session_state.document_upload_cache = cached
        st.session_state.nf_xml_auto_signature = target
        st.session_state.nf_xml_auto_stats = {
            "nfe": len(matched.get("nfe") or []),
            "cte": len(cte_candidates),
            "cte_expected_keys": cte_expected_keys,
            "match_version": 2,
            "missing": len(matched.get("nao_encontradas") or []),
            "download_errors": len(failures),
            "pending_name": len(pending_name),
        }
        if imported:
            st.session_state.document_reprocess_needed = True
            st.success(
                f"{imported} XML(s) vinculados ao lote. "
                "A conferência será executada automaticamente."
            )
        if pending_name:
            st.warning(
                "XML encontrado pelo número da NF, mas o emitente não teve "
                "correspondência segura: " + ", ".join(sorted(set(pending_name)))
                + ". Documento NÃO vinculado automaticamente; revise o cadastro "
                "ou faça a conferência manual."
            )
        if failures:
            st.warning(
                f"{len(failures)} XML(s) não puderam ser recuperados. "
                "Os demais foram preservados; reconsulte para tentar novamente."
            )
        if not imported and not failures:
            st.caption("Biblioteca consultada. Nenhum XML novo para esta seleção.")
    except Exception as exc:
        # Não reinicia requisições demoradas a cada widget/rerun.
        st.session_state.nf_xml_auto_signature = target
        st.session_state.nf_xml_auto_stats = {
            "nfe": 0, "cte": 0, "missing": 0, "download_errors": 1,
        }
        st.warning(
            "Não foi possível consultar a biblioteca XML: "
            f"{exc}. Clique em INICIAR BUSCA DE DOCUMENTOS novamente; "
            "os documentos já carregados permanecem no lote."
        )
