import { normalizeTestRecipients } from "./recipients.ts";

function eq(actual: unknown, expected: unknown): void {
  if (actual !== expected) {
    throw Error(`Esperado ${JSON.stringify(expected)}; recebido ${JSON.stringify(actual)}`);
  }
}
Deno.test("homologação aceita dois e-mails corporativos e normaliza para auditoria", () => {
  eq(normalizeTestRecipients(" Pessoa.Um@gruposetta.com ; pessoa.dois@gruposetta.com "),
    "pessoa.um@gruposetta.com;pessoa.dois@gruposetta.com");
});
Deno.test("homologação bloqueia ausência, e-mail isolado e duplicidade", () => {
  for (const x of [null, "", "pessoa.um@gruposetta.com", "a@gruposetta.com;a@gruposetta.com",
    "A@gruposetta.com;a@gruposetta.com", "a@gruposetta.com;",
    "a@gruposetta.com;b@gruposetta.com;c@gruposetta.com"]) {
    eq(normalizeTestRecipients(x), null);
  }
});
Deno.test("homologação rejeita domínios externos e injeção de cabeçalho", () => {
  for (const x of [
    "a@gruposetta.com;b@externo.com",
    "a@gruposetta.com;b@gruposetta.com\nCc: vitima@externo.com",
    "a@gruposetta.com;b@gruposetta.com,vitima@externo.com",
    "a@gruposetta.com; b@gruposetta.com; ",
    "a@gruposetta.com;b@gruposetta.com".repeat(25),
  ]) eq(normalizeTestRecipients(x), null);
});
