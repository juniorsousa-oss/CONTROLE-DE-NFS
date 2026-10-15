import { renderSettaEmail } from "./email_layout.ts";
import { realisticSimulationRows, simulationRows } from "./simulation.ts";

Deno.test("Layout corporativo mantém texto aprovado, colunas e assinatura", () => {
  const html = renderSettaEmail(realisticSimulationRows(new Date("2026-10-15T19:19:00Z")),{
    testMode:false,simulated:false,realistic:true,dateLabel:"15/10/2026"
  });
  for (const term of [
    "Acompanhamento de lançamento de NFs",
    "ALMOXARIFADO · CONTROLE DE NFs",
    "Segue a relação de <strong style=\"color:#ffffff;\">2 NF(s)</strong> de compra de matéria-prima",
    "sem confirmação de lançamento.",
    "Solicitamos verificar os lançamentos pendentes e providenciar a regularização.",
    "Controle de NFs Almoxarifado | SETTA",
    "DIAS DE ATRASO",
    "EXEMPLO-001234",
    "HOMOLOGAÇÃO — DADOS FICTÍCIOS",
    'max-width:920px',
    "word-break:break-word",
    "color:#ffffff",
  ]) {
    if (!html.includes(term)) throw Error("Falta conteúdo ou estilo: " + term);
  }
  if (html.includes("sem confirmação no STSUP01 atualizado."))
    throw Error("A frase antiga reapareceu.");
  if (html.includes("<script")) throw Error("E-mail não pode ter JS executável");
});
Deno.test("Homologação e modo técnico têm aviso, produção não mostra banner", () => {
  const rows = simulationRows();
  const cfg = {testMode:false,simulated:false,realistic:false,dateLabel:"15/10/2026"};
  const prod = renderSettaEmail(rows,cfg);
  const tech = renderSettaEmail(rows,{...cfg,testMode:true,simulated:true});
  if (prod.includes("NÃO REALIZAR COBRANÇA") || !tech.includes("NÃO REALIZAR COBRANÇA"))
    throw Error("Aviso de homologação não está isolado.");
});
Deno.test("O layout HTML escapa conteúdo de dados externos", () => {
  const row = {...simulationRows()[0], fornecedor:'<img src=x onerror=alert(1)> & LTDA'};
  const html=renderSettaEmail([row],{testMode:false,simulated:false,realistic:false,dateLabel:"15/10/2026"});
  if (html.includes("<img ") || !html.includes("&lt;img") || !html.includes("&amp; LTDA"))
    throw Error("HTML não escapou campos do fornecedor");
});
