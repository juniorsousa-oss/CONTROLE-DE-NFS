# Calendário de dias úteis — Cobranças NF-e SETTA

Desde 23/11/2026, o motor de prazo e a cobrança automática consideram fins de semana e feriados oficiais, adotando **Patos de Minas/MG** como município de referência.

## Abrangência

- Nacionais fixos: 1º/jan, 21/abr (também Data Magna MG), 1º/mai, 7/set, 12/out, 2/nov, 15/nov, 20/nov e 25/dez.
- Móvel: Paixão de Cristo (2 dias antes da Páscoa).
- Municipais Patos de Minas: 24/mai, Corpus Christi (60 dias após a Páscoa), 13/jun e 15/ago.
- Pontos facultativos e emendas não são ignorados por padrão. Fechamentos específicos da SETTA podem ser cadastrados no calendário adicional.

## Funcionamento

1. **Início do prazo**: se o documento foi enviado em feriado, sábado, domingo ou fora do expediente de início (seg-qui 7–18h; sexta 7–16h), o início vai para as 7h do próximo dia útil.
2. **Prazo de 24 horas**: após o início, as horas de dias úteis correm continuamente, inclusive à noite; sábados, domingos e feriados não consomem prazo.
3. **Atraso**: só contam horas de dias úteis depois do vencimento, arredondando frações positivas para um dia.
4. **E-mails automáticos**: os gatilhos de produção/piloto e as funções de reserva de envio consultam `public.nf_eh_dia_util(data_local)`. Nos dias bloqueados, não enviam nem reservam cobrança. Os testes manuais continuam disponíveis.
5. **Limites e auditoria**: os limites existentes e a idempotência por versão do STSUP01 permanecem.

## Configuração excepcional

Tabela restrita: `public.nf_feriados_adicionais` (`data`, `descricao`, `ativo`). Somente administração autorizada deve alterar. Exemplo de fechamento específico:
```sql
insert into public.nf_feriados_adicionais (data, descricao, ativo)
values ('2026-12-31', 'Fechamento operacional SETTA', true)
on conflict (data) do update set
  descricao=excluded.descricao, ativo=excluded.ativo;
```
A alteração passa a valer no banco imediatamente, sem reprocessar notificações já enviadas. A tela Streamlit usa o calendário oficial embutido; fechamentos excepcionais ainda exigem sincronização no cliente para que a prévia também os mostre.

## Validação

Consultar `select public.nf_eh_dia_util('2026-11-20');` (false) e `select public.nf_eh_dia_util('2026-11-23');` (true).

Testes Python: `python -m unittest discover -s tests -p 'test_nf_launch_deadline.py'`.

**Atenção:** históricos de cobranças anteriores à correção são mantidos para auditoria, sem envio retroativo automático.

Fontes oficiais: calendário nacional; feriados municipais de Patos de Minas (Portaria 2.040/2025, Câmara Municipal) e legislação citada.
