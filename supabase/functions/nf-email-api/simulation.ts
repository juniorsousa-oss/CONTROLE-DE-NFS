/** Dados 100% sintéticos para teste end-to-end. Nenhum acesso ao banco fiscal. */
export type SimulationItem = {
  id: string; nf: string; fornecedor: string; natureza: string;
  enviado_em: string; arquivo: string;
};
export function simulationRows(): SimulationItem[] {
  return [{
    id: "SIMULACAO-NAO-EXISTE",
    nf: "SIMULACAO-0001",
    fornecedor: "FORNECEDOR FICTICIO - HOMOLOGACAO",
    natureza: "COMPRA DE MATERIA PRIMA - EXEMPLO FICTICIO",
    enviado_em: "DATA FICTICIA",
    arquivo: "ARQUIVO FICTICIO - NAO EXISTE",
  }];
}
