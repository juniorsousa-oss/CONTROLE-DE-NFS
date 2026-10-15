/** Dados 100% sintéticos para teste end-to-end. Nenhum acesso ao banco fiscal. */
export type SimulationItem = {
  id: string; nf: string; fornecedor: string; natureza: string;
  enviado_em: string; arquivo: string; dias_atraso: number;
};
export function simulationRows(): SimulationItem[] {
  return [{
    id: "SIMULACAO-NAO-EXISTE",
    nf: "SIMULACAO-0001",
    fornecedor: "FORNECEDOR FICTICIO - HOMOLOGACAO",
    natureza: "COMPRA DE MATERIA PRIMA - EXEMPLO FICTICIO",
    enviado_em: "DATA FICTICIA",
    arquivo: "ARQUIVO FICTICIO - NAO EXISTE",
    dias_atraso: 0,
  }];
}

/** Homologação visual: dados de demonstração, formatados como a cobrança real.
 * Nunca utiliza NF-e real nem a tabela de processamentos.
 */
export function realisticSimulationRows(now = new Date()): SimulationItem[] {
  const format = (daysAgo: number) => new Intl.DateTimeFormat("pt-BR", {
    timeZone: "America/Sao_Paulo", day: "2-digit", month: "2-digit",
    year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(new Date(now.getTime() - daysAgo * 86400000)).replace(",", "");
  return [
    {
      id: "HOMOLOGACAO-EXEMPLO-0001", nf: "EXEMPLO-001234",
      fornecedor: "FORNECEDOR MODELO A LTDA (FICTÍCIO)",
      natureza: "COMPRA DE MATERIA PRIMA",
      enviado_em: format(3),
      arquivo: "NF_EXEMPLO_001234_FORNECEDOR_MODELO_A.pdf",
      dias_atraso: 5,
    },
    {
      id: "HOMOLOGACAO-EXEMPLO-0002", nf: "EXEMPLO-005678",
      fornecedor: "FORNECEDOR MODELO B LTDA (FICTÍCIO)",
      natureza: "COMPRA DE MATERIA PRIMA",
      enviado_em: format(2),
      arquivo: "NF_EXEMPLO_005678_FORNECEDOR_MODELO_B.pdf",
      dias_atraso: 4,
    },
  ];
}
