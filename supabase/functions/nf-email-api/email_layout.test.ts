import {renderSettaEmail} from "./email_layout.ts";
import {realisticSimulationRows,simulationRows} from "./simulation.ts";

Deno.test("Modelo simples semelhante à referência, com seis colunas e texto aprovado",()=>{
  const html=renderSettaEmail(realisticSimulationRows(new Date("2026-10-15T19:19:00Z")),{
    testMode:false,simulated:false,realistic:true,dateLabel:"15/10/2026"
  });
  for(const term of [
    'bgcolor="#ffffff"','bgcolor="#efeded"','color:#292d32',
    '[HOMOLOGAÇÃO / DADOS FICTÍCIOS]','color:#a82929',
    "Segue a relação de <strong>2 NF(s)</strong> de compra de matéria-prima",
    "sem confirmação de lançamento.","DIAS DE ATRASO",
    "FORNECEDOR","DATA DE ENVIO","NOME DO ARQUIVO",
    "EXEMPLO-001234","Solicitamos verificar os lançamentos pendentes",
    "Controle de NFs Almoxarifado | SETTA"
  ]) if(!html.includes(term)) throw Error("Texto ou estilo ausente: "+term);
  for(const decoration of [
    "NOTAS FISCAIS EM ACOMPANHAMENTO",'<h1',
    'background:#162a45','font:800 22px','color:#ffffff',
    "ALMOXARIFADO · CONTROLE DE NFs"
  ]) if(html.includes(decoration)) throw Error("Visual carregado permaneceu: "+decoration);
  if(html.includes("sem confirmação no STSUP01 atualizado."))
    throw Error("Texto antigo reapareceu");
  if(html.includes("<script")) throw Error("E-mail não pode ter JS");
});
Deno.test("Avisos de homologação isolados: produção sem alerta",()=>{
  const cfg={testMode:false,simulated:false,realistic:false,dateLabel:"15/10/2026"};
  const prod=renderSettaEmail(simulationRows(),cfg);
  const tech=renderSettaEmail(simulationRows(),{...cfg,testMode:true,simulated:true});
  if(prod.includes("NÃO REALIZAR COBRANÇA") || !tech.includes("NÃO REALIZAR COBRANÇA"))
    throw Error("Aviso de homologação não está isolado");
});
Deno.test("Dados externos são escapados no HTML",()=>{
  const row={...simulationRows()[0],fornecedor:'<img src=x onerror=alert(1)> & LTDA'};
  const html=renderSettaEmail([row],{testMode:false,simulated:false,realistic:false,dateLabel:"15/10/2026"});
  if(html.includes("<img ") || !html.includes("&lt;img") || !html.includes("&amp; LTDA"))
    throw Error("Faltou escape de conteúdo externo");
});
Deno.test("Piloto vazio diferencia STSUP01 não atualizado de zero pendências",()=>{
  const cfg={testMode:false,simulated:false,realistic:false,dateLabel:"19/10/2026"};
  const none=renderSettaEmail([],{...cfg,pilotStatus:"SEM_PENDENCIAS"});
  const waiting=renderSettaEmail([],{...cfg,pilotStatus:"AGUARDANDO_STSUP01"});
  if(!none.includes("nenhuma NF de compra de matéria-prima") ||
      !none.includes("Nenhuma NF vencida elegível") ||
      none.includes("Solicitamos verificar os lançamentos pendentes") ||
      !waiting.includes("NÃO comprova que não existem pendências") ||
      !waiting.includes("Atualização do STSUP01 pendente") ||
      waiting.includes("Nenhuma NF vencida elegível") ||
      waiting.includes("Solicitamos verificar os lançamentos pendentes"))
    throw Error("E-mail vazio com informação incorreta");
  for(const html of [none,waiting])
    if(!html.includes('bgcolor="#ffffff"') || html.includes("<tbody>"))
      throw Error("Layout do aviso de zero pendências incorreto");
});
