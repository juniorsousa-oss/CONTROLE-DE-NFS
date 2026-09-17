from __future__ import annotations

import base64, io, json, re, uuid, zipfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd
import streamlit as st
from nf_processor import build_final_name, digits_only, process_nf_pdf, supplier_dataframe

ROOT = Path(__file__).parent
SUPPLIERS_FILE = ROOT / "data" / "fornecedores.csv"
LOGO_FILE = ROOT / "config" / "logo_setta.svg"

st.set_page_config(page_title="Controle de NFs | Setta", page_icon="📄", layout="wide", initial_sidebar_state="expanded")

DEFAULT = {
    "title": "CONTROLE DE NOTAS FISCAIS",
    "subtitle": "Leitura, conferência e renomeação inteligente de documentos fiscais",
    "sidebar_title": "CONTROLE DE NFs",
    "sidebar_subtitle": "Automação do fluxo fiscal",
    "intro": "Envie os PDFs, valide as correspondências encontradas e somente depois gere os arquivos com o padrão definitivo.",
    "button_color": "#111111",
    "footer": "SETTA | Controle de Notas Fiscais",
}


def load_default_logo():
    if not LOGO_FILE.exists(): return "", "image/svg+xml"
    return base64.b64encode(LOGO_FILE.read_bytes()).decode(), "image/svg+xml"


def init():
    if "cfg" not in st.session_state:
        data, mime = load_default_logo()
        st.session_state.cfg = {**DEFAULT, "logo_data": data, "logo_mime": mime}
    if "suppliers" not in st.session_state:
        try: base = pd.read_csv(SUPPLIERS_FILE, dtype=str).fillna("")
        except Exception: base = pd.DataFrame()
        st.session_state.suppliers = supplier_dataframe(base)
    for key, value in {"analysis": pd.DataFrame(), "pdfs": {}, "zip": None, "zip_name": "", "history": []}.items():
        st.session_state.setdefault(key, value)


init(); cfg = st.session_state.cfg
color = str(cfg.get("button_color") or "#111111").upper()
if not re.fullmatch(r"#[0-9A-F]{6}", color): color = "#111111"


def logo_html():
    data = cfg.get("logo_data", ""); mime = cfg.get("logo_mime", "image/svg+xml")
    return f'<img src="data:{mime};base64,{data}" alt="Logo">' if data else '<b class="fallback">SETTA</b>'


st.markdown("""
<style>
:root{--p:__COLOR__}.stApp{background:#f7f8fa}.block-container{padding-top:1rem;max-width:1600px}
section[data-testid="stSidebar"]{background:#fff;border-right:1px solid #e7e9ee}
.brand,.info,.intro,.logo-card,.metric{background:#fff;border:1px solid #e7e9ee;border-radius:14px}
.brand{padding:.85rem;margin-bottom:1rem;background:#fafbfc}.brand b{font-size:.95rem}.brand small{color:#737982}
.label{font-size:.68rem;font-weight:800;letter-spacing:.08em;text-transform:uppercase;color:#8a9099;margin:.45rem 0}
.logo-preview{background:#fff;border:1px solid #eceef2;border-radius:12px;min-height:86px;display:flex;align-items:center;justify-content:center;padding:.6rem}.logo-preview img{max-height:70px;max-width:100%}
.info{padding:.8rem;background:#fafbfc;font-size:.78rem;color:#5f6670;line-height:1.45}
.logo-card{min-height:116px;display:flex;align-items:center;justify-content:center;box-shadow:0 5px 20px rgba(16,24,40,.04)}.logo-card img{max-height:92px;max-width:300px}.fallback{font-size:2rem;letter-spacing:.08em}
.title{font-size:1.85rem;font-weight:850;margin:.9rem 0 .1rem}.subtitle{color:#737982;margin-bottom:1rem}.intro{padding:.9rem 1rem;color:#555c66;margin-bottom:1rem}
.metric{padding:.8rem}.metric small{font-size:.7rem;color:#8a9099;font-weight:800;text-transform:uppercase}.metric strong{display:block;font-size:1.45rem;margin-top:.15rem}.metric span{font-size:.72rem;color:#8a9099}
button[kind="primary"],button[data-testid="stBaseButton-primary"]{background:var(--p)!important;border-color:var(--p)!important;color:#fff!important}.footer{text-align:center;color:#9298a1;font-size:.72rem;padding-top:1.2rem}
</style>
""".replace("__COLOR__", color), unsafe_allow_html=True)


def recalc(df):
    if df.empty: return df
    out=df.copy(); names=[]; stats=[]; issues=[]
    for _,r in out.iterrows():
        due=r.get("vencimento")
        if isinstance(due,(pd.Timestamp,datetime)): due=due.date()
        elif isinstance(due,str) and due.strip():
            x=pd.to_datetime(due,errors="coerce",dayfirst=True); due=None if pd.isna(x) else x.date()
        num=str(r.get("numero_nf") or "").strip(); forn=str(r.get("fornecedor_padrao") or "").strip()
        missing=[]
        if not due: missing.append("vencimento")
        if not digits_only(num): missing.append("número NF")
        if not forn: missing.append("fornecedor")
        names.append(build_final_name(due,num,forn)); current=str(r.get("status") or "REVISAR")
        stats.append("REVISAR" if missing else (current if current in {"APROVADO","REVISAR"} else "REVISAR"))
        issues.append("Campos pendentes: "+", ".join(missing) if missing else "")
    out["nome_sugerido"]=names; out["status"]=stats; out["validacao"]=issues
    return out


def metrics(df):
    vals=[("Documentos",len(df),"PDFs analisados"),("Aprovados",int(df.status.eq("APROVADO").sum()),"Prontos"),("Revisar",int(df.status.eq("REVISAR").sum()),"Conferir"),("CNPJ exato",int(df.metodo_fornecedor.eq("CNPJ exato").sum()),"Vínculo direto")]
    for c,(a,b,d) in zip(st.columns(4),vals): c.markdown(f'<div class="metric"><small>{a}</small><strong>{b}</strong><span>{d}</span></div>',unsafe_allow_html=True)


def make_zip(df):
    buf=io.BytesIO(); manifest=[]; batch=f"NF-{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:5].upper()}"; used=set()
    with zipfile.ZipFile(buf,"w",zipfile.ZIP_DEFLATED) as z:
        for _,r in df.iterrows():
            item=st.session_state.pdfs.get(str(r.file_id)); name=str(r.nome_sugerido or "").strip()
            if not item: raise ValueError(f"PDF original indisponível: {r.arquivo_original}")
            if not name or name in used: raise ValueError(f"Nome final vazio ou duplicado: {name}")
            used.add(name); z.writestr(name,item["bytes"])
            manifest.append({"lote_id":batch,"arquivo_original":r.arquivo_original,"arquivo_final":name,"numero_nf":str(r.numero_nf),"serie":str(r.serie),"chave_nfe":str(r.chave_nfe),"cnpj_fornecedor":str(r.cnpj_fornecedor),"fornecedor_padrao":str(r.fornecedor_padrao),"vencimento":r.vencimento,"metodo_fornecedor":str(r.metodo_fornecedor),"confianca":int(r.confianca),"processado_em":datetime.now().isoformat(timespec="seconds")})
    return buf.getvalue(),f"NOTAS_FISCAIS_{datetime.now():%d-%m-%Y_%H-%M}.zip",manifest


with st.sidebar:
    st.markdown(f'<div class="brand"><b>{cfg["sidebar_title"]}</b><br><small>{cfg["sidebar_subtitle"]}</small></div>',unsafe_allow_html=True)
    st.markdown('<div class="label">Navegação</div>',unsafe_allow_html=True)
    page=st.radio("Página",["Processar NFs","Fornecedores","Histórico","Configurações"],label_visibility="collapsed",format_func=str.upper)
    st.divider(); st.markdown('<div class="label">Identidade visual</div>',unsafe_allow_html=True)
    st.markdown(f'<div class="logo-preview">{logo_html()}</div>',unsafe_allow_html=True); st.caption("Personalize logo, títulos e cor em Configurações.")
    st.divider(); st.markdown('<div class="label">Informações</div>',unsafe_allow_html=True)
    st.markdown(f'<div class="info"><b>Data operacional</b><br>{date.today():%d/%m/%Y}<br><br><b>Fluxo</b><br>NF-e → conferência → ZIP<br><br><b>Versão</b><br>Protótipo 0.1</div>',unsafe_allow_html=True)

st.markdown(f'<div class="logo-card">{logo_html()}</div><div class="title">{cfg["title"]}</div><div class="subtitle">{cfg["subtitle"]}</div>',unsafe_allow_html=True)

if page=="Processar NFs":
    st.markdown(f'<div class="intro">{cfg["intro"]}</div>',unsafe_allow_html=True)
    files=st.file_uploader("Selecione ou arraste os PDFs das notas fiscais",type=["pdf"],accept_multiple_files=True)
    a,b=st.columns(2)
    analyze=a.button("Analisar documentos",type="primary",use_container_width=True,disabled=not files)
    if b.button("Limpar lote atual",use_container_width=True):
        st.session_state.analysis=pd.DataFrame(); st.session_state.pdfs={}; st.session_state.zip=None; st.rerun()
    if analyze:
        rows=[]; store={}; prog=st.progress(0,text="Analisando documentos...")
        for i,f in enumerate(files,1):
            raw=f.getvalue(); r=process_nf_pdf(f.name,raw,st.session_state.suppliers,ocr_fallback=True); rows.append(r.to_dict()); store[r.file_id]={"name":f.name,"bytes":raw}; prog.progress(i/len(files),text=f"{i}/{len(files)} — {f.name}")
        prog.empty(); df=pd.DataFrame(rows)
        if not df.empty: df["vencimento"]=pd.to_datetime(df["vencimento"],errors="coerce").dt.date; df=recalc(df)
        st.session_state.analysis=df; st.session_state.pdfs=store; st.session_state.zip=None; st.success(f"{len(df)} documento(s) analisado(s). Confira antes da renomeação final.")

    df=st.session_state.analysis.copy()
    if df.empty: st.info("Nenhum lote analisado nesta sessão.")
    else:
        st.markdown("### Conferência das correspondências"); metrics(df)
        st.caption("Vencimento, número da NF, fornecedor padrão e status podem ser corrigidos pelo operador.")
        cols=["arquivo_original","vencimento","numero_nf","cnpj_fornecedor","fornecedor_lido","fornecedor_padrao","metodo_fornecedor","confianca","leitura","status","nome_sugerido","observacao"]
        ed=st.data_editor(df[cols],use_container_width=True,hide_index=True,num_rows="fixed",key="review",
            disabled=["arquivo_original","cnpj_fornecedor","fornecedor_lido","metodo_fornecedor","confianca","leitura","nome_sugerido","observacao"],
            column_config={"arquivo_original":"Arquivo original","vencimento":st.column_config.DateColumn("Vencimento",format="DD/MM/YYYY"),"numero_nf":"NF","cnpj_fornecedor":"CNPJ emitente","fornecedor_lido":"Fornecedor lido","fornecedor_padrao":"Fornecedor padrão","metodo_fornecedor":"Correspondência","confianca":st.column_config.ProgressColumn("Confiança",min_value=0,max_value=100,format="%d%%"),"leitura":"Leitura","status":st.column_config.SelectboxColumn("Status",options=["APROVADO","REVISAR"],required=True),"nome_sugerido":"Nome final","observacao":"Observação automática"})
        merged=df.copy()
        for c in ["vencimento","numero_nf","fornecedor_padrao","status"]: merged[c]=ed[c].values
        merged=recalc(merged); st.session_state.analysis=merged
        st.markdown("#### Prévia da renomeação"); st.dataframe(merged[["arquivo_original","nome_sugerido","status","validacao"]],use_container_width=True,hide_index=True)
        invalid=merged[merged.nome_sugerido.fillna("").eq("")|merged.status.ne("APROVADO")|merged.validacao.fillna("").ne("")]
        dup=merged.nome_sugerido.fillna("").duplicated(keep=False)&merged.nome_sugerido.fillna("").ne("")
        if dup.any(): st.error("Há nomes finais duplicados.")
        elif not invalid.empty: st.warning(f"{len(invalid)} documento(s) ainda em revisão.")
        else: st.success("Todas as correspondências estão aprovadas.")
        if st.button("Renomear e gerar ZIP",type="primary",use_container_width=True,disabled=(not invalid.empty or dup.any())):
            try:
                z,n,h=make_zip(merged); st.session_state.zip=z; st.session_state.zip_name=n; st.session_state.history.extend(h); st.success("ZIP criado. Os PDFs não foram enviados ao banco.")
            except Exception as e: st.error(f"Falha ao gerar ZIP: {e}")
        if st.session_state.zip:
            st.download_button("Baixar ZIP com os PDFs renomeados",st.session_state.zip,file_name=st.session_state.zip_name,mime="application/zip",type="primary",use_container_width=True)

elif page=="Fornecedores":
    st.markdown("### Base de fornecedores"); st.write("O vínculo principal usa o CNPJ do emitente; o nome do DANFE é contingência.")
    base=supplier_dataframe(st.session_state.suppliers)
    ed=st.data_editor(base,use_container_width=True,hide_index=True,num_rows="dynamic",key="supplier_editor",column_config={"cnpj":"CNPJ","nome_padrao":"Nome padrão do arquivo","aliases":"Nomes alternativos separados por |","ativo":st.column_config.CheckboxColumn("Ativo",default=True)})
    a,b=st.columns(2)
    if a.button("Aplicar base nesta sessão",type="primary",use_container_width=True):
        clean=supplier_dataframe(ed); dup=clean[clean.cnpj.ne("")&clean.cnpj.duplicated(keep=False)]
        if not dup.empty: st.error("Há CNPJs duplicados.")
        else: st.session_state.suppliers=clean; st.success("Base aplicada.")
    b.download_button("Baixar base de fornecedores",supplier_dataframe(ed).to_csv(index=False).encode("utf-8-sig"),file_name="fornecedores_nf.csv",mime="text/csv",use_container_width=True)
    up=st.file_uploader("Importar base de fornecedores (CSV)",type=["csv"],key="supplier_csv")
    if up:
        try:
            incoming=supplier_dataframe(pd.read_csv(up,dtype=str).fillna("")); st.dataframe(incoming,use_container_width=True,hide_index=True)
            if st.button("Usar CSV importado",type="primary"): st.session_state.suppliers=incoming; st.rerun()
        except Exception as e: st.error(f"Falha ao importar CSV: {e}")
    st.info("Nesta versão a edição é de sessão. A persistência será ligada ao Supabase na próxima etapa.")

elif page=="Histórico":
    st.markdown("### Histórico da sessão"); h=pd.DataFrame(st.session_state.history)
    if h.empty: st.info("Ainda não há lotes finalizados.")
    else:
        st.dataframe(h,use_container_width=True,hide_index=True); st.download_button("Baixar histórico CSV",h.to_csv(index=False).encode("utf-8-sig"),file_name=f"historico_nf_{date.today():%d%m%Y}.csv",mime="text/csv",use_container_width=True)
    st.caption("Aqui serão gravados apenas os metadados no Supabase; nunca o PDF.")

else:
    st.markdown("### Personalização do aplicativo"); cur=st.session_state.cfg.copy()
    with st.form("cfg"):
        title=st.text_input("Título principal",cur["title"]); sub=st.text_input("Subtítulo",cur["subtitle"]); side=st.text_input("Título do menu lateral",cur["sidebar_title"]); sidesub=st.text_input("Subtítulo do menu lateral",cur["sidebar_subtitle"]); intro=st.text_area("Texto da tela principal",cur["intro"]); footer=st.text_input("Rodapé",cur["footer"]); col=st.color_picker("Cor principal dos botões",cur["button_color"]); save=st.form_submit_button("Aplicar textos e cor",type="primary",use_container_width=True)
    if save:
        cur.update(title=title or DEFAULT["title"],subtitle=sub or DEFAULT["subtitle"],sidebar_title=side or DEFAULT["sidebar_title"],sidebar_subtitle=sidesub or DEFAULT["sidebar_subtitle"],intro=intro or DEFAULT["intro"],footer=footer or DEFAULT["footer"],button_color=col.upper()); st.session_state.cfg=cur; st.rerun()
    st.markdown("#### Logo da empresa"); up=st.file_uploader("Selecionar nova logo",type=["png","jpg","jpeg","svg"],key="logo")
    if up:
        raw=up.getvalue()
        if len(raw)>1_500_000: st.error("Logo acima de 1,5 MB.")
        else:
            mime=up.type or ("image/svg+xml" if up.name.lower().endswith(".svg") else "image/png"); enc=base64.b64encode(raw).decode(); st.markdown(f'<div class="logo-preview"><img src="data:{mime};base64,{enc}"></div>',unsafe_allow_html=True)
            if st.button("Aplicar nova logo",type="primary",use_container_width=True): cur=st.session_state.cfg.copy(); cur.update(logo_data=enc,logo_mime=mime); st.session_state.cfg=cur; st.rerun()
    a,b=st.columns(2)
    if a.button("Restaurar padrão visual",use_container_width=True):
        d,m=load_default_logo(); st.session_state.cfg={**DEFAULT,"logo_data":d,"logo_mime":m}; st.rerun()
    b.download_button("Baixar configuração textual",json.dumps({k:v for k,v in st.session_state.cfg.items() if k!="logo_data"},ensure_ascii=False,indent=2).encode(),file_name="config_controle_nfs.json",mime="application/json",use_container_width=True)
    st.info("As configurações ainda são de sessão; serão persistidas no Supabase junto com o cadastro de fornecedores.")

st.markdown(f'<div class="footer">{cfg["footer"]}</div>',unsafe_allow_html=True)
