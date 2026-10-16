/** Modelo leve de e-mail: referência visual SETTA, Outlook e mobile.
 * Somente apresentação; não altera prazos, elegibilidade ou destinatários.
 */
export type EmailRow = {
  nf:string; fornecedor:string; natureza:string; enviado_em:string;
  dias_atraso:number; arquivo:string;
};
export type MailStyle = {
  testMode:boolean; simulated:boolean; realistic:boolean; dateLabel:string;
  pilotStatus?:string;
};
const escapeHtml = (s: unknown) => String(s ?? "").replaceAll("&", "&amp;")
  .replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;")
  .replaceAll("'","&#39;");

export function renderSettaEmail(rows:EmailRow[], opts:MailStyle):string {
  const columns=["NF","FORNECEDOR","NATUREZA","DATA DE ENVIO","DIAS DE ATRASO","NOME DO ARQUIVO"];
  const headers=columns.map(name=>
    '<th scope="col" bgcolor="#efeded" style="border:1px solid #d9d9d9;padding:10px 12px;' +
    'background:#efeded;color:#252a30;font:700 13px/1.4 Arial,Helvetica,sans-serif;' +
    'text-align:left;">' + escapeHtml(name) + '</th>'
  ).join("");
  const bodyRows=rows.map((r,i)=>{
    const bg=i%2===0?"#ffffff":"#faf7f6";
    const delay=Math.max(0,Math.floor(Number(r.dias_atraso)||0));
    const values=[r.nf,r.fornecedor,r.natureza,r.enviado_em,String(delay),r.arquivo];
    return '<tr bgcolor="' + bg + '">' + values.map(value =>
      '<td bgcolor="' + bg + '" style="border:1px solid #d9d9d9;padding:10px 12px;' +
      'background:' + bg + ';color:#2b2d33;font:14px/1.5 Arial,Helvetica,sans-serif;' +
      'vertical-align:top;overflow-wrap:anywhere;word-break:break-word;">' +
      escapeHtml(value) + '</td>'
    ).join("") + '</tr>';
  }).join("");
  const warning=opts.realistic
    ? "[HOMOLOGAÇÃO / DADOS FICTÍCIOS] EXEMPLO DO E-MAIL REAL. NÃO REALIZAR COBRANÇA OU LANÇAMENTO."
    : opts.simulated
      ? "[SIMULAÇÃO / HOMOLOGAÇÃO] DADOS FICTÍCIOS. NÃO REALIZAR COBRANÇA OU LANÇAMENTO."
      : opts.testMode ? "[TESTE / HOMOLOGAÇÃO] NÃO REPRESENTA UMA COBRANÇA REAL." : "";
  const warningHtml=warning
    ? '<p style="margin:0 0 24px;padding:14px;border:1px solid #e6b7b7;' +
      'color:#a82929;background:#ffffff;font:700 14px/1.5 Arial,Helvetica,sans-serif;">' +
      escapeHtml(warning) + '</p>'
    : "";
  const awaiting=opts.pilotStatus==="AGUARDANDO_STSUP01";
  const noIssues=opts.pilotStatus==="SEM_PENDENCIAS";
  const intro=awaiting
    ? "Mensagem automática de teste: aguardando uma atualização válida do STSUP01 para consultar os lançamentos. A ausência de NFs nesta mensagem NÃO comprova que não existem pendências."
    : noIssues
      ? "Verificação do STSUP01 atualizado concluída: nenhuma NF de compra de matéria-prima com lançamento vencido e pendente foi identificada nesta consulta."
      : opts.simulated
        ? "Mensagem fictícia para validar a integração SETTA → Power Automate → Outlook. Nenhuma nota fiscal real foi utilizada."
        : 'Segue a relação de <strong>' + rows.length +
          ' NF(s)</strong> de compra de matéria-prima com prazo de lançamento vencido, sem confirmação de lançamento.';
  const closing=awaiting
    ? "Aguardamos a próxima atualização do STSUP01. Nenhuma cobrança foi gerada nesta verificação."
    : noIssues
      ? "Nenhuma tratativa de lançamento é necessária com base nesta atualização."
      : opts.simulated
        ? "<strong>Não tomar providências:</strong> este e-mail é exclusivamente um teste de entrega e formatação."
        : "Solicitamos verificar os lançamentos pendentes e providenciar a regularização.";
  const tableHtml=rows.length
    ? '<table role="table" width="100%" cellpadding="0" cellspacing="0" ' +
      'style="width:100%;border-collapse:collapse;margin:0 0 22px;' +
      'font:14px Arial,Helvetica,sans-serif;"><thead><tr>' + headers +
      '</tr></thead><tbody>' + bodyRows + '</tbody></table>'
    : '<p style="margin:0 0 22px;color:#292d32;font:700 14px/1.6 Arial,Helvetica,sans-serif;">' +
      (awaiting ? "Atualização do STSUP01 pendente" : "Nenhuma NF vencida elegível") + '</p>';

  return '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width,initial-scale=1">' +
    '</head><body bgcolor="#ffffff" style="margin:0;padding:0;background:#ffffff;' +
    'color:#292d32;font:14px/1.6 Arial,Helvetica,sans-serif;">' +
    '<div style="padding:24px 16px;max-width:100%;box-sizing:border-box;' +
    'color:#292d32;background:#ffffff;">' +
    warningHtml +
    '<p style="margin:0 0 20px;color:#292d32;font:14px/1.6 Arial,Helvetica,sans-serif;">Prezados,</p>' +
    '<p style="margin:0 0 22px;color:#292d32;font:14px/1.6 Arial,Helvetica,sans-serif;">' + intro + '</p>' +
    tableHtml +
    '<p style="margin:0 0 24px;color:#292d32;font:14px/1.6 Arial,Helvetica,sans-serif;">' + closing + '</p>' +
    '<p style="margin:0;color:#292d32;font:14px/1.6 Arial,Helvetica,sans-serif;">' +
    'Atenciosamente,<br>Controle de NFs Almoxarifado | SETTA</p>' +
    '</div></body></html>';
}
