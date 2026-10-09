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
from collections import Counter
from pathlib import PurePosixPath

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


def library_api(action:str,values:dict|None=None,timeout:int=70):
    if not _token():
        raise RuntimeError("Entre com seu usuário SETTA para acessar a biblioteca XML.")
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
    return unique,errors


def _make_report(uploaded:list):
    records=[]
    files,errors=_read_xml_uploads(uploaded)
    records.extend({"ARQUIVO":"—","RESULTADO":"INVÁLIDO","INFORMAÇÃO":err} for err in errors)
    if not files:return pd.DataFrame(records)
    progress=st.progress(0,text="Importando documentos fiscais na biblioteca privada...")
    for ix,(filename,raw) in enumerate(files,1):
        try:
            result=library_api("ingest",{
                "filename":filename,
                "raw_base64":base64.b64encode(raw).decode("ascii"),
            },timeout=90)
            records.append({
                "ARQUIVO":filename,
                "RESULTADO":str(result.get("resultado") or "?"),
                "INFORMAÇÃO":str(result.get("chave") or ""),
            })
        except Exception as exc:
            records.append({"ARQUIVO":filename,"RESULTADO":"ERRO","INFORMAÇÃO":str(exc)})
        progress.progress(ix/len(files),text=f"Importando {ix} de {len(files)}...")
    progress.empty()
    return pd.DataFrame(records)


def render_page():
    st.markdown("## BIBLIOTECA DE XMLs")
    st.caption("CENTRAL SETTA · NF-e / CT-e · ARMAZENAMENTO PRIVADO · ALIMENTAÇÃO MANUAL E FUTURA API")
    if not _login_panel():return

    tab_upload,tab_documents,tab_access=st.tabs(["IMPORTAR XMLs","DOCUMENTOS ARMAZENADOS","PERMISSÕES"])
    with tab_upload:
        st.markdown("#### IMPORTAR PASTA OU ZIP")
        st.caption("Selecione vários XMLs de uma só vez ou envie um arquivo ZIP contendo XMLs. Arquivos duplicados não são substituídos; versões conflitantes exigem análise.")
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
            for c,(key,title) in zip(cols,[("INCLUIDO","INCLUÍDOS"),("DUPLICADO","DUPLICADOS"),("CONFLITO","CONFLITOS"),("ERRO","ERROS")]):
                c.metric(title,int(counts.get(key,0)))
            st.dataframe(report,hide_index=True,use_container_width=True,height=min(500,95+35*len(report)))
            st.download_button("EXPORTAR RELATÓRIO DE IMPORTAÇÃO",report.to_csv(index=False,sep=";").encode("utf-8-sig"),"biblioteca_xml_importacao.csv","text/csv",use_container_width=True)

    with tab_documents:
        if st.button("ATUALIZAR CONSULTA",key="nf_xml_refresh_list"):
            st.session_state.pop("nf_xml_library_index",None)
        try:
            if "nf_xml_library_index" not in st.session_state:
                st.session_state.nf_xml_library_index=library_api("list")
            index=st.session_state.nf_xml_library_index
            documents=index.get("documentos") or []
            imports=index.get("historico") or []
            a,b,c=st.columns(3)
            a.metric("DOCUMENTOS CONSULTADOS",len(documents))
            b.metric("NF-e",sum(d.get("tipo")=="NFE" for d in documents))
            c.metric("CT-e",sum(d.get("tipo")=="CTE" for d in documents))
            query=st.text_input("PESQUISAR NÚMERO, CHAVE OU EMITENTE")
            show=[d for d in documents if not query.strip() or query.lower().strip() in (
                str(d.get("numero",""))+" "+str(d.get("chave",""))+" "+str(d.get("cnpj_emitente",""))+" "+str(d.get("arquivo_nome",""))
            ).lower()]
            if show:
                data=pd.DataFrame(show)[["tipo","numero","chave","cnpj_emitente","cnpj_destinatario","arquivo_nome","origem","importado_em"]]
                data.columns=["TIPO","NÚMERO","CHAVE","CNPJ EMITENTE","CNPJ DESTINATÁRIO","ARQUIVO","ORIGEM","IMPORTADO EM"]
                st.dataframe(data,hide_index=True,use_container_width=True,height=min(500,95+35*len(data)))
            else:st.info("Nenhum documento encontrado nesta consulta.")
            if imports:
                with st.expander("ÚLTIMOS REGISTROS DE IMPORTAÇÃO"):
                    st.dataframe(pd.DataFrame(imports),use_container_width=True,hide_index=True)
        except Exception as exc:st.error("Erro na biblioteca: "+str(exc))

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


def prefill_stage2(pending_pre:pd.DataFrame):
    """Consulta automática uma vez por seleção; importa apenas documentos inequívocos."""
    if not _token():
        st.caption("BIBLIOTECA XML · Faça login no menu Biblioteca XML para associar automaticamente os documentos disponíveis.")
        return
    if not isinstance(pending_pre,pd.DataFrame) or pending_pre.empty:return
    requests_nfs=[]
    for _,row in pending_pre.iterrows():
        numero=_simple_nf(row.get("numero_nf"))
        cnpj=re.sub(r"\D","",str(row.get("cnpj") or ""))
        chave=re.sub(r"\D","",str(row.get("chave_nfe") or ""))
        if numero!="0" and (len(cnpj)==14 or len(chave)==44):
            requests_nfs.append({"numero":numero,"cnpj":cnpj,"chave":chave})
    if not requests_nfs:return
    fingerprint=hashlib.sha256(repr(sorted((x["numero"],x["cnpj"],x["chave"]) for x in requests_nfs)).encode()).hexdigest()
    refresh=st.button("RECONSULTAR BIBLIOTECA XML",key="nf_xml_force_refresh")
    if refresh:st.session_state.pop("nf_xml_auto_signature",None)
    target=f"{_token()}:{fingerprint}"
    if st.session_state.get("nf_xml_auto_signature")==target:
        linked=st.session_state.get("nf_xml_auto_stats") or {}
        if linked:
            st.caption(f"BIBLIOTECA · {linked.get('nfe',0)} NF-e e {linked.get('cte',0)} CT-e encontrados · {linked.get('missing',0)} NF(s) ainda sem XML.")
        return
    try:
        matched=library_api("match",{"nfs":requests_nfs},timeout=60)
        cached=list(st.session_state.get("document_upload_cache") or [])
        existing={hashlib.sha256(x.get("raw") or b"").hexdigest() for x in cached}
        imported=0
        for record in (matched.get("nfe") or [])+(matched.get("cte") or []):
            result=library_api("download",{"id":record["id"]},timeout=70)
            raw=base64.b64decode(result.get("raw_base64") or "",validate=True)
            digest=hashlib.sha256(raw).hexdigest()
            if raw and digest not in existing:
                name=str(result.get("filename") or record.get("arquivo_nome") or record.get("chave")+".xml")
                cached.append({"name":name,"raw":raw,"ext":".xml","origem":"BIBLIOTECA"})
                existing.add(digest)
                imported+=1
        st.session_state.document_upload_cache=cached
        st.session_state.nf_xml_auto_signature=target
        st.session_state.nf_xml_auto_stats={
            "nfe":len(matched.get("nfe") or []),
            "cte":len(matched.get("cte") or []),
            "missing":len(matched.get("nao_encontradas") or []),
        }
        if imported:
            st.session_state.document_reprocess_needed=True
            st.success(f"{imported} XML(s) da biblioteca incluídos no lote; os documentos serão analisados automaticamente.")
        else:
            st.info("Biblioteca consultada. Nenhum XML novo correspondeu a esta seleção.")
    except Exception as exc:
        st.warning("Não foi possível pré-carregar XMLs da biblioteca: "+str(exc))
