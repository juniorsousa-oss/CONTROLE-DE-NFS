import "jsr:@supabase/functions-js/edge-runtime.d.ts";
import { createClient } from "jsr:@supabase/supabase-js@2";
import { normalizeTestRecipients } from "./recipients.ts";
import { simulationRows, realisticSimulationRows } from "./simulation.ts";
import { checkWorkflowUrl } from "./webhook_validation.ts";

type Item = {
  id: string;
  nf: string;
  fornecedor: string;
  natureza: string;
  enviado_em: string;
  arquivo: string;
  dias_atraso: number;
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
function buildHtml(rows: Item[], testMode: boolean, simulated=false, realistic=false): string {
  const headers = ["NF", "FORNECEDOR", "NATUREZA", "DATA DE ENVIO", "DIAS DE ATRASO", "NOME DO ARQUIVO"];
  const th = headers.map(h => '<th bgcolor="#2b415b" style="padding:10px;border:1px solid #73859a;text-align:left;background:#2b415b;color:#ffffff;">' + h + '</th>').join("");
  const trs = rows.map((row, i) => {
    const fields = [row.nf, row.fornecedor, row.natureza, row.enviado_em, String(row.dias_atraso ?? 0), row.arquivo];
    const shade = i % 2 ? "#273d54" : "#182b40";
    const cells = fields.map(value => '<td bgcolor="' + shade +
      '" style="padding:10px;border:1px solid #73859a;vertical-align:top;background:' +
      shade + ';color:#ffffff;">' + escaped(value || "") + "</td>").join("");
    return '<tr bgcolor="' + shade + '">' + cells + "</tr>";
  }).join("");
  const prefix = realistic
    ? '<p style="color:#b91c1c;font-weight:bold;border:1px solid #f3b3b3;padding:10px;">[HOMOLOGAÇÃO / DADOS FICTÍCIOS] EXEMPLO DO E-MAIL REAL. NÃO REALIZAR COBRANÇA OU LANÇAMENTO.</p>'
    : simulated
      ? '<p style="color:#b91c1c;font-weight:bold;">[SIMULAÇÃO / HOMOLOGAÇÃO] DADOS 100% FICTÍCIOS. NÃO REALIZAR COBRANÇA OU LANÇAMENTO.</p>'
      : testMode
      ? '<p style="color:#a16207;font-weight:bold;">[TESTE / HOMOLOGAÇÃO] Não representa uma cobrança real.</p>'
      : "";
  const intro = simulated
    ? '<p>Mensagem fictícia para validar a integração SETTA → Power Automate → Outlook. Nenhuma nota fiscal real foi utilizada.</p>'
    : '<p>Segue a relação de <strong>' + rows.length +
      ' NF(s)</strong> de compra de matéria-prima com prazo de lançamento vencido, ' +
      'sem confirmação de lançamento.</p>';
  const closing = simulated
    ? '<p><strong>Não tomar providências:</strong> este e-mail é exclusivamente um teste de entrega e formatação.</p>'
    : '<p>Solicitamos verificar os lançamentos pendentes e providenciar a regularização.</p>';
  const whiteText = (content: string) => content.replaceAll("<p>", '<p style="color:#ffffff;">');
  return '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8"></head>' +
    '<body style="margin:0;padding:0;font:14px Arial,sans-serif;background:#112238;color:#ffffff;line-height:1.6;">' +
    '<table role="presentation" cellpadding="0" cellspacing="0" width="100%" bgcolor="#112238" style="background:#112238;color:#ffffff;">' +
    '<tr><td bgcolor="#112238" style="padding:20px;background:#112238;color:#ffffff;">' +
    prefix + '<p style="color:#ffffff;">Prezados,</p>' + whiteText(intro) +
    '<table role="table" cellpadding="0" cellspacing="0" style="border-collapse:collapse;width:100%;font:13px Arial,sans-serif;color:#ffffff;">' +
    "<thead><tr>" + th + "</tr></thead><tbody>" + trs + "</tbody></table>" +
    whiteText(closing) +
    '<p style="color:#ffffff;">Atenciosamente,<br>Controle de NFs Almoxarifado | SETTA</p>' +
    "</td></tr></table></body></html>";
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
  const mode = data?.mode === "PRODUCAO" ? "PRODUCAO"
    : data?.mode === "TESTE" ? "TESTE"
    : data?.mode === "SIMULACAO" ? "SIMULACAO"
    : data?.mode === "PREVIA_REALISTA" ? "PREVIA_REALISTA" : "";
  if (!mode) return json({ok:false,error:"MODO_INVALIDO"},400);
  if (mode === "PRODUCAO" && Deno.env.get("NFS_EMAIL_PRODUCTION_ENABLED") !== "true") {
    return json({ok:true,data:{status:"PRODUCAO_DESATIVADA"}});
  }

  const endpointStatus = checkWorkflowUrl(Deno.env.get("NFS_EMAIL_WORKFLOW_URL") || "");
  const url = endpointStatus.url;
  // Nunca devolver URL, assinatura, domínio ou partes da credencial.
  if (!url) return json({ok:true,data:{status:endpointStatus.status}});

  const supabaseUrl = Deno.env.get("SUPABASE_URL") || "";
  const serviceKey = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") || "";
  if (!supabaseUrl || !serviceKey) return json({ok:false,error:"SUPABASE_NAO_CONFIGURADO"},500);
  const admin = createClient(supabaseUrl, serviceKey, {
    auth:{persistSession:false,autoRefreshToken:false},
  });

  // Endereço de homologação configurado no banco por administração.
  // Não é recebido no JSON, na interface nem como cabeçalho do solicitante.
  const testConfig = mode !== "PRODUCAO"
    ? await admin.from("nf_email_controle").select("destinatario_teste")
      .eq("singleton",true).maybeSingle()
    : null;
  if (testConfig?.error) return json({ok:false,error:"CONFIG_TESTE_INDISPONIVEL"},500);
  const testAddress = normalizeTestRecipients(testConfig?.data?.destinatario_teste) || "";
  const productionTo = (Deno.env.get("NFS_EMAIL_PROD_TO") || "").trim();
  const productionCc = (Deno.env.get("NFS_EMAIL_PROD_CC") || "").trim();
  const to = mode !== "PRODUCAO" ? testAddress : productionTo;
  const cc = mode !== "PRODUCAO" ? "" : productionCc;
  if ((mode !== "PRODUCAO" && !testAddress) ||
      (mode === "PRODUCAO" &&
        (!to || to.split(";").some(s => !validEmail(s.trim())) ||
        (cc && cc.split(";").some(s => !validEmail(s.trim())))))) {
    return json({ok:true,data:{status:"DESTINATARIOS_NAO_CONFIGURADOS"}});
  }
  let claim: any;
  try {
    const claimed = mode === "SIMULACAO" || mode === "PREVIA_REALISTA"
      ? await admin.rpc("nf_email_claim_simulation", { p_destinatarios:to })
      : await admin.rpc("nf_email_claim", {
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

  const simulated = mode === "SIMULACAO";
  const realistic = mode === "PREVIA_REALISTA";
  const rows = realistic ? realisticSimulationRows()
    : simulated ? simulationRows() : (claim.items || []) as Item[];
  const test = mode !== "PRODUCAO";
  const normalSubject = "SETTA | Acompanhamento de lançamento de NFs vencidas — " +
    isoDateBrazil(new Date());
  const subject = realistic
    ? normalSubject + " [HOMOLOGAÇÃO — DADOS FICTÍCIOS]"
    : simulated
      ? "[SIMULAÇÃO / NÃO COBRAR] SETTA | Teste de notificação de NFs — " + isoDateBrazil(new Date())
      : (test ? "[TESTE] " : "") + normalSubject;
  // A prévia utiliza o MESMO texto, tabela e estilo da cobrança de produção;
  // somente o aviso superior e o sufixo do assunto a distinguem.
  const body = buildHtml(rows,realistic ? false : test,simulated,realistic);
  // Envelope compatível com o gatilho padrão de webhook do Teams
  // (sem conector HTTP Premium). O fluxo pode usar html/subject nas
  // ações do Outlook, sem publicar mensagem em chat/canal.
  const payload = {
    type:"message",attachments:[],
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
