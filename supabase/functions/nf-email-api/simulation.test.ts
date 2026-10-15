import { simulationRows, realisticSimulationRows } from "./simulation.ts";
Deno.test("simulação deve conter apenas valores fictícios reconhecíveis", () => {
  const rows = simulationRows();
  if (rows.length !== 1) throw Error("A simulação deve conter exatamente uma linha.");
  const row = rows[0];
  if (!row.id.startsWith("SIMULACAO") || !row.nf.startsWith("SIMULACAO") ||
      !row.fornecedor.includes("FICTICIO") ||
      !row.arquivo.includes("NAO EXISTE")) {
    throw Error("A simulação deve estar claramente identificada.");
  }
});

Deno.test("prévia realista deve manter seis campos fiscais, com dados inteiramente fictícios", () => {
  const rows = realisticSimulationRows(new Date("2026-10-15T15:00:00Z"));
  if (rows.length !== 2) throw Error("A prévia visual exige duas NFs fictícias.");
  const expected = ["id", "nf", "fornecedor", "natureza", "enviado_em", "arquivo", "dias_atraso"];
  for (const row of rows) {
    if (JSON.stringify(Object.keys(row)) !== JSON.stringify(expected))
      throw Error("Os campos da prévia devem acompanhar o modelo de produção.");
    if (!row.id.startsWith("HOMOLOGACAO-EXEMPLO") ||
        !row.nf.startsWith("EXEMPLO-") ||
        !row.fornecedor.includes("FICTÍCIO") ||
        !row.arquivo.startsWith("NF_EXEMPLO_") ||
        row.natureza !== "COMPRA DE MATERIA PRIMA" ||
        !Number.isInteger(row.dias_atraso) || row.dias_atraso <= 0 ||
        !/\d{2}\/\d{2}\/\d{4} \d{2}:\d{2}/.test(row.enviado_em)) {
      throw Error("Prévia não é segura ou não reproduz a tabela operacional.");
    }
  }
});

Deno.test("datas de demonstração respeitam sábado/domingo e a carência de 24h", () => {
  const quinta = realisticSimulationRows(new Date("2026-10-15T19:19:00Z"));
  if (quinta[0].enviado_em !== "12/10/2026 16:19" ||
      quinta[1].enviado_em !== "13/10/2026 16:19" ||
      quinta[0].dias_atraso !== 2 || quinta[1].dias_atraso !== 1)
    throw Error("Exemplo não acompanha a regra de dias úteis em quinta-feira");
  const segunda = realisticSimulationRows(new Date("2026-10-19T19:19:00Z"));
  if (segunda[0].enviado_em !== "14/10/2026 16:19" ||
      segunda[1].enviado_em !== "15/10/2026 16:19")
    throw Error("Exemplo contabilizou sábado/domingo indevidamente");
});
