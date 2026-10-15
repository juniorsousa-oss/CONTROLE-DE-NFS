import { simulationRows } from "./simulation.ts";
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
