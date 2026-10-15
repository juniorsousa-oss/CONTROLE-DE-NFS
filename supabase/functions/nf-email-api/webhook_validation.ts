/** Analisa somente o formato do webhook, sem revelar URL ou assinatura. */
export type WorkflowCheck = {url: URL | null; status: string};
export function checkWorkflowUrl(raw: string): WorkflowCheck {
  let input = (raw || "").trim();
  if (!input) return {url:null,status:"WEBHOOK_SEGREDO_AUSENTE"};
  // Alguns painéis inserem aspas ao copiar a configuração TOML.
  if (input.length >= 2 &&
      ((input.startsWith('"') && input.endsWith('"')) ||
       (input.startsWith("'") && input.endsWith("'")))) {
    input = input.slice(1,-1).trim();
  }
  let url: URL;
  try { url = new URL(input); }
  catch { return {url:null,status:"WEBHOOK_URL_INVALIDA"}; }

  if (url.protocol !== "https:" || url.username || url.password)
    return {url:null,status:"WEBHOOK_URL_INVALIDA"};
  const suffixes = ["logic.azure.com","powerautomate.com","powerplatform.com"];
  if (!suffixes.some(h => url.hostname === h || url.hostname.endsWith("." + h)))
    return {url:null,status:"WEBHOOK_DOMINIO_NAO_PERMITIDO"};
  // Evita cadastrar por engano o link da tela de edição do Power Automate.
  if (!/\/triggers\/[^/]+\/paths\/invoke\/?$/i.test(url.pathname))
    return {url:null,status:"WEBHOOK_NAO_E_URL_HTTP_DO_GATILHO"};
  // O fluxo atual aceita chamadas anônimas por URL assinada.
  if (!url.searchParams.get("sig"))
    return {url:null,status:"WEBHOOK_URL_SEM_ASSINATURA"};
  return {url,status:"CONFIGURADO"};
}
