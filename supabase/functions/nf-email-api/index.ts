import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";

type Item = {
  id: string;
  nf: string;
  fornecedor: string;
  natureza: string;
  enviado_em: string;
  arquivo: string;
};

const cors = {
  "Access-Control-Allow-Origin": "*",
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "content-type,x-nfs-notification-token",
};
const json = (object: unknown, status=200) => new Response(JSON.stringify(object), {
  status, headers: { ...cors, "Content-Type": "application/json; charset=utf-8" },
});
function escaped(input: string): string {
  return String(input).replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;").replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;").replaceAll("'", "&#39;");
}
function isoDateBrazil(date: Date) {
  return new Intl.DateTimeFormat("pt-BR", {
    timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit", year: "numeric",
  }).format(date);
}
function buildHtml(rows: Item[], testMode: boolean): string {
  const headers = ["NF", "FORNECEDOR", "NATUREZA", "DATA DE ENVIO", "NOME DO ARQUIVO"];
  const th = headers.map(h => '<th style="padding:10px;border:1px solid #ccd4df;text-align:left;background:#e7effa;">' + h + '</th>').join("");
  const trs = rows.map((row, i) => {
    const fields = [row.nf, row.fornecedor, row.natureza, row.enviado_em, row.arquivo];
    const cells = fields.map(value => '<td style="padding:10px;border:1px solid #ccd4df;vertical-align:top;">' +
      escaped(value || "") + "</td>").join("");
    return '<tr style="background:' + (i % 2 ? "#f5f8fc" : "#fff") + ';">' + cells + "</tr>";
  }).join("");
  const prefix = testMode ?
    '<p style="color:#a16207;font-weight:bold;">[TESTE / HOMOLOGAÇÃO] Não representa uma cobrança real.</p>' : "";
  return '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"></head>' +
    '<body style="font:14px Arial,sans-serif;color:#1e293b;line-height:1.6;">' +
    prefix + '<p>Prezados,</p>' +
    '<p>Segue a relação de <strong>' + rows.length +
    ' NF(s)</strong> de compra de matéria-prima com prazo de lançamento vencido, ' +
    'sem confirmação no STSUP01 atualizado.</p>' +
    '<table role="table" style="border-collapse:collapse;width:100%;font:13px Arial,sans-serif;color:#1e293b;">' +
    "<thead><tr>" + th + "</tr></thead><tbody>" + trs + "</tbody></table>" +
    '<p>Solicitamos verificar os lançamentos pendentes e providenciar a regularização.</p>' +
    '<p>Atenciosamente,<br>Controle de NFs | SETTA</p>' +
    "</body></html>";
}
function authorizedEndpoint(raw: string): URL | null {
  try {
    const endpoint = new URL(raw);
    const hosts = ["logic.azure.com", "powerautomate.com", "powerplatform.com"];
    if (endpoint.protocol !== "https:" || !hosts.some(h => endpoint.hostname === h ||
      endpoint.hostname.endsWith("." + h))) return null;
    return endpoint;
  } catch { return null; }
}
function secureMatch(a: string, b: string): boolean {
  const x = new TextEncoder().encode(a);
  const y = new TextEncoder().encode(b);
  let difference = x.length ^ y.length;
  for (let i = 0; i < Math.max(x.length, y.length); i++) {
    difference |= (x[i] || 0) ^ (y[i] || 0);
  }
  return difference === 0;
}
function validEmail(address: string) {
  return /^[^\s@;]+@[^\s@;]+\.[^\s@;]+$/.test(address);
}

Deno.serve(async req => {
  if (req.method === "OPTIONS") return new Response(null, {headers:cors});
  if (req.method !== "POST") return json({ok:false,error:"METHOD_NOT_ALLOWED"},405);

  // O aplicativo utiliza uma chave guardada SOMENTE nos segredos do servidor.
  // Sem ela, a função deve recusar todos os pedidos, inclusive os testes.
  const shared = Deno.env.get("NFS_EMAIL_API_TOKEN") || "";
  const supplied = req.headers.get("x-nfs-notification-token") || "";
  if (shared.length < 32 || supplied.length < 32 || !secureMatch(shared,supplied)) {
    return json({ok:false,error:"AUTH_REQUIRED"},401);
  }
  let data: {mode?: string};
  try { data=await req.json(); }
  catch { return json({ok:false,error:"JSON_INVALIDO"},400); }
  const mode = data?.mode === "PRODUCAO" ? "PRODUCAO" : data?.mode === "TESTE" ? "TESTE" : "";
  if (!mode) return json({ok:false,error:"MODO_INVALIDO"},400);
  if (mode === "PRODUCAO" && Deno.env.get("NFS_EMAIL_PRODUCTION_ENABLED") !== "true") {
    return json({ok:true,data:{status:"PRODUCAO_DESATIVADA"}});
  }

  const endpointRaw = (Deno.env.get("NFS_EMAIL_WORKFLOW_URL") || "").trim();
  const url = authorizedEndpoint(endpointRaw);
  if (!url) return json({ok:true,data:{status:"WEBHOOK_NAO_CONFIGURADO"}});
  const testAddress = (Deno.env.get("NFS_EMAIL_TEST_RECIPIENT") || "").trim();
  const productionTo = (Deno.env.get("NFS_EMAIL_PROD_TO") || "").trim();
  const productionCc = (Deno.env.get("NFS_EMAIL_PROD_CC") || "").trim();
  const to = mode === "TESTE" ? testAddress : productionTo;
  const cc = mode === "TESTE" ? "" : productionCc;
  if ((mode === "TESTE" && !validEmail(to)) ||
      (mode === "PRODUCAO" &&
        (!to || to.split(";").some(s => !validEmail(s.trim())) ||
        (cc && cc.split(";").some(s => !validEmail(s.trim())))))) {
    return json({ok:true,data:{status:"DESTINATARIOS_NAO_CONFIGURADOS"}});
  }

  const supabaseUrl = Deno.env.get("SUPABASE_URL") || "";
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return json({ok:false,error:"SUPABASE_NAO_CONFIGURADO"},500);
  const admin = createClient(supabaseUrl, serviceKey, {
    auth:{persistSession:false,autoRefreshToken:false},
  });
  let claim: any;
  try {
    const claimed = await admin.rpc("nf_email_claim", {
      p_modo:mode, p_destinatarios:to, p_cc:cc,
    });
    if (claimed.error) throw Error("CLAIM:" + claimed.error.message);
    claim = claimed.data;
  } catch (error) {
    return json({ok:false,error:"FALHA_AO_CONSULTAR_PENDENCIAS",
      detail:String(error).slice(0,150)},500);
  }
  if (claim?.status !== "PRONTO") {
    return json({ok:true,data:{status:String(claim?.status || "SEM_DADOS")}});
  }

  const rows = (claim.items || []) as Item[];
  const test = mode === "TESTE";
  const subject = (test ? "[TESTE] " : "") +
    "SETTA | Cobrança de lançamento de NFs vencidas — " + isoDateBrazil(new Date());
  const body = buildHtml(rows,test);
  const payload = {
    to,cc,subject,html:body,kind:mode,
    notification_id:claim.id,version_token:claim.source_version,
  };
  // Nunca repetir automaticamente uma chamada cujo resultado é desconhecido.
  // Para falha de rede/timeout, marcar INCERTO e conferir os logs do fluxo.
  let status: "ACEITO"|"INCERTO"|"FALHA" = "INCERTO";
  let reason = "";
  try {
    const response = await fetch(url.toString(), {
      method:"POST",headers:{"Content-Type":"application/json"},
      body:JSON.stringify(payload),signal:AbortSignal.timeout(15000),
    });
    if (response.ok) status="ACEITO";
    else {
      status="FALHA";
      reason="WORKFLOW_HTTP_" + response.status;
    }
  } catch {
    status="INCERTO";
    reason="WORKFLOW_CONEXAO_OU_TIMEOUT";
  }
  const result = await admin.rpc("nf_email_finish",{
    p_id:claim.id,p_status:status,p_erro:reason || null,
  });
  if (result.error) {
    return json({ok:false,error:"FALHA_AO_SALVAR_AUDITORIA",id:claim.id},500);
  }
  return json({
    ok:status==="ACEITO",
    data:{
      status,mode,quantidade:rows.length,id:claim.id,
      message: status==="ACEITO" ?
        "Fluxo aceitou a mensagem. Confirme a entrega no e-mail de teste." :
        "Não foi possível confirmar o envio. Confira a execução do fluxo.",
    },
    ...(status === "ACEITO" ? {} : {error:reason}),
  }, status==="ACEITO" ? 200 : 502);
});
