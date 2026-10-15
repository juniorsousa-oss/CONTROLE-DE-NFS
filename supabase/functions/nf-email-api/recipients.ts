/** Validação dos dois endereços corporativos autorizados na homologação.
 * Origem: tabela privada nf_email_controle. Nunca aceitar lista do navegador.
 */
export function normalizeTestRecipients(value: unknown): string | null {
  if (typeof value !== "string" || value.length > 520) return null;
  const recipients = value.split(";").map((email) => email.trim().toLowerCase());
  if (recipients.length !== 2 || new Set(recipients).size !== 2) return null;
  if (!recipients.every((email) =>
    email.length <= 254 && /^[^\s@;]+@gruposetta\.com$/.test(email)
  )) return null;
  return recipients.join(";");
}
