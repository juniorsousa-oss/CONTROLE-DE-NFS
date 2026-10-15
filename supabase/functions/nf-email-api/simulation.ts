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
  // Datas sintéticas baseadas no calendário brasileiro. Retroceder 3 e 2
  // dias úteis, respectivamente, resulta em 2 e 1 dias de atraso APÓS
  // o prazo inicial de 24h; sem contar sábados ou domingos.
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Sao_Paulo", year: "numeric", month: "2-digit",
    day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23",
  }).formatToParts(now);
  const values = Object.fromEntries(parts.map(p => [p.type, p.value]));
  const anchor = new Date(Date.UTC(
    Number(values.year), Number(values.month) - 1, Number(values.day),
    Number(values.hour), Number(values.minute),
  ));
  function previousWorkingDay(date: Date): Date {
    do { date.setUTCDate(date.getUTCDate() - 1); }
    while ([0,6].includes(date.getUTCDay()));
    return date;
  }
  function dateBeforeBusinessDays(days: number): string {
    const value = new Date(anchor);
    // Se a consulta ocorrer em fim de semana, o relógio está congelado
    // desde sexta-feira: ajustar a referência para o último dia elegível.
    while ([0,6].includes(value.getUTCDay())) previousWorkingDay(value);
    for (let i = 0; i < days; i++) previousWorkingDay(value);
    const two = (n: number) => String(n).padStart(2, "0");
    return two(value.getUTCDate()) + "/" + two(value.getUTCMonth() + 1) +
      "/" + value.getUTCFullYear() + " " +
      two(value.getUTCHours()) + ":" + two(value.getUTCMinutes());
  }
  return [
    {
      id: "HOMOLOGACAO-EXEMPLO-0001", nf: "EXEMPLO-001234",
      fornecedor: "FORNECEDOR MODELO A LTDA (FICTÍCIO)",
      natureza: "COMPRA DE MATERIA PRIMA",
      enviado_em: dateBeforeBusinessDays(3),
      arquivo: "NF_EXEMPLO_001234_FORNECEDOR_MODELO_A.pdf",
      dias_atraso: 2,
    },
    {
      id: "HOMOLOGACAO-EXEMPLO-0002", nf: "EXEMPLO-005678",
      fornecedor: "FORNECEDOR MODELO B LTDA (FICTÍCIO)",
      natureza: "COMPRA DE MATERIA PRIMA",
      enviado_em: dateBeforeBusinessDays(2),
      arquivo: "NF_EXEMPLO_005678_FORNECEDOR_MODELO_B.pdf",
      dias_atraso: 1,
    },
  ];
}
