import { createClient } from "jsr:@supabase/supabase-js@2";
import { XMLParser, XMLValidator } from "npm:fast-xml-parser@4.5.3";

const cors: Record<string,string> = {
 "Access-Control-Allow-Origin":"*",
 "Access-Control-Allow-Methods":"POST, OPTIONS",
 "Access-Control-Allow-Headers":"apikey, authorization, content-type, x-client-info",
};
const json=(data:unknown,status=200)=>new Response(JSON.stringify(data),{status,headers:{...cors,"Content-Type":"application/json"}});
const fail=(msg:string,status=400)=>json({ok:false,error:msg},status);
const trim=(v:unknown)=>String(v??"").trim();
const digits=(v:unknown)=>trim(v).replace(/\D/g,"");
const fiscalNumber=(v:unknown)=>digits(v).replace(/^0+/,"")||"0";
const limitName=(v:unknown)=>trim(v).replace(/[\\/\x00-\x1f]/g,"_").slice(0,180)||"documento.xml";
const array=(x:unknown):any[]=>x===undefined||x===null?[]:Array.isArray(x)?x:[x];
const errText=(e:unknown)=>e instanceof Error?e.message:String(e);
const parser=new XMLParser({ignoreAttributes:false,attributeNamePrefix:"@",removeNSPrefix:true,parseTagValue:false,parseAttributeValue:false,trimValues:true,processEntities:false});
const SCOPE="nf-xml-library";
const MAX_BYTES=4194304;

function classify(xml:Uint8Array){
 const source=new TextDecoder("utf-8",{fatal:true}).decode(xml);
 if (/<!DOCTYPE|<!ENTITY/i.test(source)) throw Error("DOCTYPE_E_ENTIDADES_NAO_PERMITIDOS");
 const valid=XMLValidator.validate(source);
 if(valid!==true)throw Error("ESTRUTURA_XML_INVALIDA");
 const doc=parser.parse(source);
 const nfe=doc.nfeProc?.NFe??doc.NFe;
 const cte=doc.cteProc?.CTe??doc.CTe;
 if(!nfe&&!cte)throw Error("ARQUIVO_NAO_E_NFE_OU_CTE");
 if(nfe&&cte)throw Error("XML_AMBIGUO");
 if(nfe){
  const inf=nfe.infNFe,ide=inf?.ide,emit=inf?.emit,dest=inf?.dest;
  if(!inf||!ide||!emit)throw Error("NFE_ESTRUTURA_INCOMPLETA");
  const chave=digits(inf["@Id"]);
  const parsedId=trim(inf["@Id"]);
  if(!/^NFe[0-9]{44}$/.test(parsedId)||chave.slice(20,22)!=="55")throw Error("CHAVE_NFE_INVALIDA");
  if(digits(ide.mod)!=="55")throw Error("MODELO_NFE_INVALIDO");
  const numero=fiscalNumber(ide.nNF);
  if(fiscalNumber(chave.slice(25,34))!==numero)throw Error("NUMERO_NFE_DIVERGENTE_DA_CHAVE");
  const cnpj_emitente=digits(emit.CNPJ||emit.CPF);
  if(cnpj_emitente.length!==14||chave.slice(6,20)!==cnpj_emitente)throw Error("CNPJ_EMITENTE_INCONSISTENTE");
  const status=digits(doc.nfeProc?.protNFe?.infProt?.cStat||"");
  if(status&&status!=="100"&&status!=="150")throw Error("NFE_SEM_AUTORIZACAO:"+status);
  return {tipo:"NFE",chave,numero,cnpj_emitente,cnpj_destinatario:digits(dest?.CNPJ||dest?.CPF),status_fiscal:status,refs_nfe:[]};
 }
 const inf=cte.infCte,ide=inf?.ide,emit=inf?.emit;
 if(!inf||!ide||!emit)throw Error("CTE_ESTRUTURA_INCOMPLETA");
 const rawId=trim(inf["@Id"]),chave=digits(rawId);
 if(!/^CTe[0-9]{44}$/.test(rawId)||chave.slice(20,22)!=="57")throw Error("CHAVE_CTE_INVALIDA");
 if(digits(ide.mod)!=="57")throw Error("MODELO_CTE_INVALIDO");
 const numero=fiscalNumber(ide.nCT);
 if(fiscalNumber(chave.slice(25,34))!==numero)throw Error("NUMERO_CTE_DIVERGENTE_DA_CHAVE");
 const cnpj_emitente=digits(emit.CNPJ||emit.CPF);
 if(cnpj_emitente.length!==14||chave.slice(6,20)!==cnpj_emitente)throw Error("CNPJ_CTE_INCONSISTENTE");
 const refs=array(inf.infCTeNorm?.infDoc?.infNFe).map((i:any)=>digits(i?.chave)).filter((x:string)=>x.length===44&&x.slice(20,22)==="55");
 const status=digits(doc.cteProc?.protCTe?.infProt?.cStat||"");
 if(status&&status!=="100"&&status!=="150")throw Error("CTE_SEM_AUTORIZACAO:"+status);
 const toma=inf.ide?.toma3??inf.ide?.toma4??{};
 return {tipo:"CTE",chave,numero,cnpj_emitente,cnpj_destinatario:digits(toma.CNPJ||toma.CPF),status_fiscal:status,refs_nfe:[...new Set(refs)]};
}

Deno.serve(async(req)=>{
 if(req.method==="OPTIONS")return new Response(null,{headers:cors});
 if(req.method!=="POST")return fail("METHOD_NOT_ALLOWED",405);
 const url=Deno.env.get("SUPABASE_URL"),secret=Deno.env.get("SUPABASE_SERVICE_ROLE_KEY");
 if(!url||!secret)return fail("SERVER_NOT_CONFIGURED",500);
 const api=createClient(url,secret,{auth:{persistSession:false,autoRefreshToken:false}});
 let body:any={};
 try{body=await req.json()}catch{return fail("JSON_INVALIDO")}
 const action=trim(body?.action),payload=body?.payload??{};
 try{
  if(action==="login"){
   const login=trim(payload.login),password=trim(payload.password);
   if(!login||!password)return fail("LOGIN_E_SENHA_OBRIGATORIOS");
   const {data,error}=await api.rpc("operahub_auth_user",{p_login:login,p_password:password});
   if(error)return fail("NAO_FOI_POSSIVEL_AUTENTICAR",401);
   const user=Array.isArray(data)?data[0]:data;
   if(!user?.id)return fail("USUARIO_OU_SENHA_INVALIDOS",401);
   const {data:account,error:ae}=await api.from("operahub_users").select("id,username,full_name,role,is_active").eq("id",user.id).maybeSingle();
   if(ae||!account?.is_active)return fail("CONTA_INATIVA",403);
   const isAdmin=trim(account.role).toLowerCase()==="admin";
   const {data:permission,error:pe}=await api.from("nf_xml_permissoes").select("perfil").eq("user_id",account.id).maybeSingle();
   if(pe)return fail("ERRO_NAS_PERMISSOES",500);
   if(!isAdmin&&!permission)return fail("USUARIO_SEM_ACESSO_A_BIBLIOTECA_XML",403);
   const token=crypto.randomUUID(),expires=new Date(Date.now()+6*60*60*1000).toISOString();
   const {error:se}=await api.from("nf_xml_sessoes").insert({token,user_id:account.id,expira_em:expires});
   if(se)return fail("ERRO_AO_CRIAR_SESSAO",500);
   return json({ok:true,data:{token,expira_em:expires,nome:account.full_name,perfil:isAdmin?"ADMIN":permission.perfil}});
  }
  if(action==="logout"){
   const token=trim(payload.token);
   if(token)await api.from("nf_xml_sessoes").delete().eq("token",token);
   return json({ok:true,data:{logout:true}});
  }
  const token=trim(payload.token);
  if(!/^[0-9a-f-]{36}$/i.test(token))return fail("SESSAO_NAO_IDENTIFICADA",401);
  const {data:session,error:se}=await api.from("nf_xml_sessoes").select("user_id,expira_em").eq("token",token).gt("expira_em",new Date().toISOString()).maybeSingle();
  if(se||!session)return fail("SESSAO_INVALIDA_OU_EXPIRADA",401);
  const {data:account,error:ae}=await api.from("operahub_users").select("id,username,full_name,role,is_active").eq("id",session.user_id).maybeSingle();
  if(ae||!account?.is_active)return fail("CONTA_INATIVA",403);
  const admin=trim(account.role).toLowerCase()==="admin";
  const {data:permission,error:pe}=await api.from("nf_xml_permissoes").select("perfil").eq("user_id",account.id).maybeSingle();
  if(pe)return fail("ERRO_NAS_PERMISSOES",500);
  if(!admin&&!permission)return fail("ACESSO_REVOGADO",403);
  const user=account.id,profile=admin?"ADMIN":permission.perfil;
  if(action==="whoami")return json({ok:true,data:{nome:account.full_name,perfil:profile}});
  if(action==="users"){
   if(profile!=="ADMIN")return fail("ADMIN_REQUIRED",403);
   const [users,perms]=await Promise.all([
    api.from("operahub_users").select("id,username,full_name,is_active,role").order("full_name").limit(500),
    api.from("nf_xml_permissoes").select("user_id,perfil").limit(500),
   ]);
   if(users.error||perms.error)return fail("ERRO_USUARIOS",500);
   const rights=new Map((perms.data||[]).map((x:any)=>[x.user_id,x.perfil]));
   return json({ok:true,data:(users.data||[]).map((x:any)=>({...x,xml_perfil:trim(x.role).toLowerCase()==="admin"?"ADMIN":rights.get(x.id)||"SEM_ACESSO"}))});
  }
  if(action==="grant"){
   if(profile!=="ADMIN")return fail("ADMIN_REQUIRED",403);
   const target=trim(payload.user_id),desired=trim(payload.perfil);
   if(!/^[0-9a-f-]{36}$/i.test(target)||!["OPERADOR","SEM_ACESSO"].includes(desired))return fail("PERMISSAO_INVALIDA");
   const {data:other}=await api.from("operahub_users").select("id,role,is_active").eq("id",target).maybeSingle();
   if(!other?.is_active||trim(other.role).toLowerCase()==="admin")return fail("USUARIO_NAO_ELEGIVEL");
   const result=desired==="SEM_ACESSO"
    ?await api.from("nf_xml_permissoes").delete().eq("user_id",target)
    :await api.from("nf_xml_permissoes").upsert({user_id:target,perfil:"OPERADOR",concedido_por:user},{onConflict:"user_id"});
   if(result.error)return fail("NAO_FOI_POSSIVEL_ATUALIZAR_ACESSO",500);
   return json({ok:true,data:{user_id:target,perfil:desired}});
  }
  if(action==="list"){
   const limit=Math.max(1,Math.min(1000,Number(payload.limit)||300));
   const [docs,logs]=await Promise.all([
    api.from("nf_xml_documentos").select("id,tipo,chave,numero,cnpj_emitente,cnpj_destinatario,refs_nfe,arquivo_nome,origem,importado_em,status_fiscal").order("importado_em",{ascending:false}).limit(limit),
    api.from("nf_xml_importacoes").select("arquivo_nome,resultado,mensagem,origem,criado_em").order("criado_em",{ascending:false}).limit(40),
   ]);
   if(docs.error||logs.error)return fail("CONSULTA_INDISPONIVEL",500);
   return json({ok:true,data:{documentos:docs.data||[],historico:logs.data||[]}});
  }
  if(action==="check_existing"){
   // Preflight sem upload de documentos: apenas chaves e SHA-256.
   // A verificação é autenticada, limitada a 200 registros por lote.
   const requested=array(payload.items);
   if(!requested.length || requested.length>200)return fail("LOTE_DE_CONFERENCIA_DEVE_TER_1_A_200_DOCUMENTOS");
   const wanted=new Map<string,string>();
   for(const item of requested){
    const chave=digits(item?.chave),hash=trim(item?.sha256).toLowerCase();
    if(!/^[0-9]{44}$/.test(chave)||!["55","57"].includes(chave.slice(20,22))
      || !/^[0-9a-f]{64}$/.test(hash))return fail("CHAVE_OU_HASH_INVALIDO");
    const prev=wanted.get(chave);
    if(prev&&prev!==hash)return fail("CHAVE_REPETIDA_COM_HASH_DIFERENTE");
    wanted.set(chave,hash);
   }
   const {data,error}=await api.from("nf_xml_documentos").select("chave,sha256")
    .in("chave",[...wanted.keys()]).limit(200);
   if(error)return fail("ERRO_CONSULTA_PREVIA",500);
   const existing=new Map((data||[]).map((row:any)=>[String(row.chave),String(row.sha256).toLowerCase()]));
   const results=[...wanted.entries()].map(([chave,sha256])=>({
    chave,
    status:!existing.has(chave)?"NOVO":existing.get(chave)===sha256?"DUPLICADO":"CONFLITO",
   }));
   return json({ok:true,data:{results}});
  }
  if(action==="ingest"){
   const nome=limitName(payload.filename),raw=trim(payload.raw_base64);
   if(!nome.toLowerCase().endsWith(".xml"))return fail("APENAS_XML");
   if(!raw||raw.length>7500000)return fail("ARQUIVO_ACIMA_DO_LIMITE");
   let bytes:Uint8Array;
   try{bytes=Uint8Array.from(atob(raw),c=>c.charCodeAt(0))}catch{return fail("XML_BASE64_INVALIDO")}
   if(!bytes.length||bytes.length>MAX_BYTES)return fail("ARQUIVO_ACIMA_DE_4_MB");
   let info:ReturnType<typeof classify>;
   try{info=classify(bytes)}catch(e){
    const message=errText(e).slice(0,300);
    await api.from("nf_xml_importacoes").insert({arquivo_nome:nome,resultado:"INVALIDO",mensagem:message,origem:"MANUAL",usuario_id:user});
    return fail(message);
   }
   const hash=Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256",bytes))).map(x=>x.toString(16).padStart(2,"0")).join("");
   const {data:previous,error:existingError}=await api.from("nf_xml_documentos").select("id,sha256").eq("chave",info.chave).maybeSingle();
   if(existingError)return fail("ERRO_VERIFICACAO_DUPLICIDADE",500);
   if(previous){
    const resultado=previous.sha256===hash?"DUPLICADO":"CONFLITO";
    await api.from("nf_xml_importacoes").insert({documento_id:previous.id,arquivo_nome:nome,resultado,mensagem:resultado==="CONFLITO"?"Mesma chave fiscal com conteúdo diferente; revisão manual obrigatória.":"Arquivo já cadastrado.",origem:"MANUAL",usuario_id:user});
    return json({ok:true,data:{resultado,chave:info.chave,tipo:info.tipo}});
   }
   const path=info.tipo+"/"+info.chave+".xml";
   const {error:uploadError}=await api.storage.from(SCOPE).upload(path,bytes,{contentType:"application/xml",upsert:false});
   if(uploadError)return fail("FALHA_ARMAZENAMENTO_PRIVADO:"+uploadError.message,500);
   const {data:record,error:insertError}=await api.from("nf_xml_documentos").insert({
    ...info,arquivo_nome:nome,storage_path:path,sha256:hash,tamanho_bytes:bytes.length,origem:"MANUAL",importado_por:user
   }).select("id,chave,tipo").single();
   if(insertError){
    await api.storage.from(SCOPE).remove([path]);
    // Concorrência: nunca sobrescreve um XML sem análise explícita.
    return fail("ERRO_DE_REGISTRO_OU_CHAVE_DUPLICADA:"+insertError.message,409);
   }
   await api.from("nf_xml_importacoes").insert({documento_id:record.id,arquivo_nome:nome,resultado:"INCLUIDO",origem:"MANUAL",usuario_id:user});
   return json({ok:true,data:{resultado:"INCLUIDO",chave:info.chave,tipo:info.tipo}});
  }
  if(action==="match"){
   const items=array(payload.nfs).slice(0,500);
   const normalized=items.map((i:any)=>({numero:fiscalNumber(i.numero),cnpj:digits(i.cnpj),chave:digits(i.chave)}))
    .filter((i:any)=>i.numero!=="0"&&(i.cnpj.length===14||i.chave.length===44));
   if(!normalized.length)return json({ok:true,data:{nfe:[],cte:[],nao_encontradas:[]}});
   const nums=[...new Set(normalized.map((x:any)=>x.numero))];
   const {data:docs,error:de}=await api.from("nf_xml_documentos")
    .select("id,tipo,chave,numero,cnpj_emitente,refs_nfe,arquivo_nome")
    .eq("tipo","NFE").in("numero",nums).limit(2000);
   if(de)return fail("FALHA_BUSCA_NFE",500);
   const selected:any[]=[],missing:string[]=[];
   for(const item of normalized){
    const matches=(docs||[]).filter((r:any)=>r.numero===item.numero &&
      (item.chave.length===44?r.chave===item.chave:r.cnpj_emitente===item.cnpj));
    if(matches.length===1){
     if(!selected.some(x=>x.id===matches[0].id))selected.push(matches[0]);
    }else missing.push(item.numero+(matches.length>1?" (AMBÍGUA)":""));
   }
   let linkedCte:any[]=[];
   if(selected.length){
    const keys=new Set(selected.map(x=>x.chave));
    const {data:cte,error:ce}=await api.from("nf_xml_documentos")
     .select("id,tipo,chave,numero,refs_nfe,arquivo_nome").eq("tipo","CTE")
     .order("importado_em",{ascending:false}).limit(3000);
    if(ce)return fail("FALHA_BUSCA_CTE",500);
    linkedCte=(cte||[]).filter((x:any)=>array(x.refs_nfe).some((k:any)=>keys.has(k)));
   }
   return json({ok:true,data:{nfe:selected,cte:linkedCte,nao_encontradas:missing}});
  }
  if(action==="download"){
   const id=trim(payload.id);
   if(!/^[0-9a-f-]{36}$/i.test(id))return fail("ID_DOCUMENTO_INVALIDO");
   const {data:record,error:re}=await api.from("nf_xml_documentos").select("arquivo_nome,storage_path").eq("id",id).maybeSingle();
   if(re||!record)return fail("DOCUMENTO_NAO_ENCONTRADO",404);
   const {data:blob,error:be}=await api.storage.from(SCOPE).download(record.storage_path);
   if(be||!blob)return fail("ARQUIVO_INDISPONIVEL",500);
   const content=new Uint8Array(await blob.arrayBuffer());
   if(content.length>MAX_BYTES)return fail("LIMITE_EXCEDIDO");
   let bin="";for(let i=0;i<content.length;i+=8192)bin+=String.fromCharCode(...content.subarray(i,i+8192));
   return json({ok:true,data:{filename:record.arquivo_nome,raw_base64:btoa(bin)}});
  }
  return fail("ACAO_DESCONHECIDA",404);
 }catch(e){return fail("FALHA_BIBLIOTECA_XML:"+errText(e),500)}
});
