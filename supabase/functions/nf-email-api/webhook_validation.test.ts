import { checkWorkflowUrl } from "./webhook_validation.ts";

const valid = "https://default123.environment.api.powerplatform.com:443/powerautomate/automations/direct/cu/01/workflows/abc/triggers/manual/paths/invoke?api-version=1&sp=%2Ftriggers%2Fmanual%2Frun&sv=1.0&sig=FAKE_TEST_SIG";
Deno.test("reconhece webhook do Teams e aspas opcionais", () => {
  for (const input of [valid, '  "'+valid+'"  ', "'"+valid+"'"]) {
    const result=checkWorkflowUrl(input);
    if (result.status !== "CONFIGURADO" || result.url?.searchParams.get("sig") !== "FAKE_TEST_SIG")
      throw Error("Rejeitou uma URL de webhook válida de teste");
  }
});
Deno.test("distingue falta, URL incorreta, domínio e assinatura sem expor dados", () => {
  const cases: [string,string][] = [
    ["","WEBHOOK_SEGREDO_AUSENTE"],
    ["my-secret-value","WEBHOOK_URL_INVALIDA"],
    ["https://example.com/triggers/manual/paths/invoke?sig=test","WEBHOOK_DOMINIO_NAO_PERMITIDO"],
    ["https://make.powerautomate.com/environments/default/flows/test","WEBHOOK_NAO_E_URL_HTTP_DO_GATILHO"],
    ["https://default123.environment.api.powerplatform.com/powerautomate/automations/direct/cu/01/workflows/abc/triggers/manual/paths/invoke","WEBHOOK_URL_SEM_ASSINATURA"],
    ["http://default123.environment.api.powerplatform.com/triggers/manual/paths/invoke?sig=test","WEBHOOK_URL_INVALIDA"],
  ];
  for (const [input,expected] of cases) {
    const result=checkWorkflowUrl(input);
    if (result.url !== null || result.status !== expected)
      throw Error("Diagnóstico incorreto: " + result.status);
    if (result.status.includes("sig=test")) throw Error("Assinatura exposta");
  }
});
