/** Modelo visual compartilhado pelos e-mails de produção e homologação.
 * Tabelas/estilos inline para Outlook web, desktop e clientes mobile.
 * NUNCA muda destinatários, regras de cobrança ou fluxo de disparo.
 */
export type EmailRow = {
  nf: string; fornecedor: string; natureza: string; enviado_em: string;
  dias_atraso: number; arquivo: string;
};
export type MailStyle = {
  testMode: boolean; simulated: boolean; realistic: boolean; dateLabel: string;
  pilotStatus?: string;
};
const esc = (s: unknown) => String(s ?? "").replaceAll("&", "&amp;")
  .replaceAll("<", "&lt;").replaceAll(">", "&gt;")
  .replaceAll('"', "&quot;").replaceAll("'", "&#39;");

export function renderSettaEmail(rows: EmailRow[], opts: MailStyle): string {
  const white = "#ffffff", light = "#dce8f6", line = "#425875";
  const headings = ["NF", "FORNECEDOR", "NATUREZA", "DATA DE ENVIO", "DIAS DE ATRASO", "NOME DO ARQUIVO"];
  const headerCells = headings.map((h) =>
    '<th bgcolor="#263f60" scope="col" style="padding:12px 10px;border-bottom:2px solid #5a7798;' +
    'background:#263f60;color:#ffffff;font:700 11px Arial,sans-serif;text-align:left;letter-spacing:.3px;">' + esc(h) + "</th>"
  ).join("");
  const rowsHtml = rows.map((r,i) => {
    const bg = i % 2 ? "#1c314e" : "#152943";
    const delay = Math.max(0, Math.floor(Number(r.dias_atraso) || 0));
    const cells = [
      '<strong style="font-weight:700;color:#ffffff;">' + esc(r.nf) + '</strong>',
      esc(r.fornecedor), esc(r.natureza), esc(r.enviado_em),
      '<span style="display:inline-block;padding:4px 9px;border-radius:10px;background:#8c3d1a;' +
        'color:#ffffff;font-weight:700;white-space:nowrap;">' + delay + '</span>',
      esc(r.arquivo),
    ];
    return '<tr bgcolor="' + bg + '">' + cells.map((v,j) =>
      '<td bgcolor="' + bg + '" style="padding:13px 10px;background:' + bg +
      ';border-bottom:1px solid ' + line + ';color:#ffffff;font:12px/1.55 Arial,sans-serif;' +
      'vertical-align:top;overflow-wrap:anywhere;word-break:break-word;' +
      (j === 3 ? 'white-space:nowrap;' : '') + '">' + v + '</td>'
    ).join("") + '</tr>';
  }).join("");
  const warning = opts.realistic
    ? "HOMOLOGAÇÃO — DADOS FICTÍCIOS. EXEMPLO DO E-MAIL REAL. NÃO REALIZAR COBRANÇA OU LANÇAMENTO."
    : opts.simulated
      ? "SIMULAÇÃO / HOMOLOGAÇÃO — DADOS FICTÍCIOS. NÃO REALIZAR COBRANÇA OU LANÇAMENTO."
      : opts.testMode ? "TESTE / HOMOLOGAÇÃO — Não representa uma cobrança real." : "";
  const notice = warning ?
    '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 22px 0;">' +
    '<tr><td bgcolor="#472932" style="background:#472932;padding:13px 16px;border-left:4px solid #fb7185;' +
    'color:#ffffff;font:700 12px/1.5 Arial,sans-serif;">' + esc(warning) + '</td></tr></table>'
    : "";
  const awaiting = opts.pilotStatus === "AGUARDANDO_STSUP01";
  const noIssues = opts.pilotStatus === "SEM_PENDENCIAS";
  const intro = awaiting
    ? "Mensagem automática de teste: aguardando uma atualização válida do STSUP01 para consultar os lançamentos. A ausência de NFs nesta mensagem NÃO comprova que não existem pendências."
    : noIssues
      ? "Verificação do STSUP01 atualizado concluída: nenhuma NF de compra de matéria-prima com lançamento vencido e pendente foi identificada nesta consulta."
      : opts.simulated
        ? "Mensagem fictícia para validar a integração SETTA → Power Automate → Outlook. Nenhuma nota fiscal real foi utilizada."
        : 'Segue a relação de <strong style="color:#ffffff;">' + rows.length +
          ' NF(s)</strong> de compra de matéria-prima com prazo de lançamento vencido, sem confirmação de lançamento.';
  const closing = awaiting
    ? "Aguardamos a próxima atualização do STSUP01. Nenhuma cobrança foi gerada nesta verificação."
    : noIssues
      ? "Nenhuma tratativa de lançamento é necessária com base nesta atualização."
      : opts.simulated
        ? '<strong>Não tomar providências:</strong> este e-mail é exclusivamente um teste de entrega e formatação.'
        : 'Solicitamos verificar os lançamentos pendentes e providenciar a regularização.';
  const emptyBlock = !rows.length
    ? '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="margin:0 0 22px;">' +
      '<tr><td bgcolor="#233d5c" style="padding:22px 16px;border:1px solid #425875;background:#233d5c;' +
      'color:#ffffff;font:700 14px/1.6 Arial,sans-serif;">' +
      (awaiting ? "Atualização do STSUP01 pendente" : "Nenhuma NF vencida elegível") +
      '</td></tr></table>' : "";

  return '<!doctype html><html lang="pt-BR"><head><meta charset="utf-8">' +
    '<meta name="viewport" content="width=device-width, initial-scale=1">' +
    '<meta name="color-scheme" content="dark"><meta name="supported-color-schemes" content="dark">' +
    '<style>@media screen and (max-width:640px){.shell-pad{padding:10px!important}' +
      '.pad-main{padding:20px 14px!important}.head-pad{padding:22px 16px!important}' +
      '.email-title{font-size:21px!important}.records-table th,.records-table td{padding:8px 6px!important;' +
      'font-size:11px!important}.summary-label{font-size:12px!important}}</style>' +
    '</head><body bgcolor="#0d192b" style="margin:0;padding:0;background:#0d192b;color:' + white +
      ';font-family:Arial,Helvetica,sans-serif;">' +
    '<div style="display:none!important;font-size:1px;color:#0d192b;line-height:1px;max-height:0;' +
    'max-width:0;opacity:0;overflow:hidden;">Controle de NFs Almoxarifado | SETTA — ' +
    esc(rows.length) + ' NF(s) em acompanhamento.</div>' +
    '<table role="presentation" width="100%" cellspacing="0" cellpadding="0" bgcolor="#0d192b"' +
    ' style="width:100%;background:#0d192b;border-collapse:collapse;">' +
    '<tr><td class="shell-pad" align="center" style="padding:26px 18px;">' +
    '<table role="presentation" width="920" cellspacing="0" cellpadding="0" bgcolor="#162a45"' +
    ' style="width:100%;max-width:920px;border-collapse:collapse;border:1px solid #3a5171;">' +
    '<tr><td class="head-pad" bgcolor="#1c3553" style="padding:27px 32px 25px;' +
    'border-top:5px solid #e54545;background:#1c3553;color:#ffffff;">' +
    '<table role="presentation" width="100%" cellspacing="0" cellpadding="0"><tr>' +
    '<td style="color:#ffffff;font:800 22px Arial,sans-serif;letter-spacing:1.5px;">SETTA</td>' +
    '<td align="right" style="color:#ffffff;font:700 11px Arial,sans-serif;letter-spacing:.6px;">ALMOXARIFADO · CONTROLE DE NFs</td>' +
    '</tr></table>' +
    '<h1 class="email-title" style="margin:23px 0 8px;color:#ffffff;' +
    'font:700 24px/1.3 Arial,sans-serif;">Acompanhamento de lançamento de NFs</h1>' +
    '<p style="margin:0;color:' + light + ';font:13px/1.5 Arial,sans-serif;">' +
    'Referência: ' + esc(opts.dateLabel) + '</p>' +
    '</td></tr>' +
    '<tr><td class="pad-main" bgcolor="#162a45" style="padding:28px 32px 30px;' +
    'background:#162a45;color:#ffffff;">' +
    notice +
    '<p style="margin:0 0 15px;color:#ffffff;font:14px/1.6 Arial,sans-serif;">Prezados,</p>' +
    '<p style="margin:0 0 23px;color:#ffffff;font:14px/1.75 Arial,sans-serif;">' + intro + '</p>' +
    '<table role="presentation" width="100%" cellpadding="0" cellspacing="0"' +
    ' style="margin:0 0 22px;border-collapse:collapse;">' +
    '<tr><td bgcolor="#233d5c" style="padding:15px 19px;border-left:4px solid #e54545;' +
    'background:#233d5c;color:#ffffff;">' +
    '<span class="summary-label" style="color:#ffffff;font:700 12px Arial,sans-serif;">' +
    'NOTAS FISCAIS EM ACOMPANHAMENTO&nbsp;&nbsp;</span>' +
    '<span style="color:#ffffff;font:700 22px Arial,sans-serif;">' + rows.length + '</span>' +
    '</td></tr></table>' +
    (rows.length
      ? '<table class="records-table" role="table" width="100%" cellpadding="0" cellspacing="0"' +
        ' style="width:100%;border-collapse:collapse;border:1px solid #425875;table-layout:auto;">' +
        '<thead><tr>' + headerCells + '</tr></thead>' +
        '<tbody>' + rowsHtml + '</tbody></table>'
      : emptyBlock) +
    '<p style="margin:26px 0 24px;color:#ffffff;font:14px/1.7 Arial,sans-serif;">' +
    closing + '</p>' +
    '<p style="margin:0;color:#ffffff;font:14px/1.7 Arial,sans-serif;">Atenciosamente,<br>' +
    '<strong style="color:#ffffff;">Controle de NFs Almoxarifado | SETTA</strong></p>' +
    '</td></tr>' +
    '<tr><td bgcolor="#0f2035" style="padding:16px 32px;background:#0f2035;' +
    'border-top:1px solid #3a5171;color:#ffffff;font:12px/1.5 Arial,sans-serif;">' +
    'SETTA · Acompanhamento operacional de notas fiscais</td></tr>' +
    '</table></td></tr></table></body></html>';
}
