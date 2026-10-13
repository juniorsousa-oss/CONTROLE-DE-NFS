-- Controle de NFs SETTA — conferência de lançamento no STSUP01 pela TES da coluna AE.
-- Atualiza também registros antes considerados lançados que agora não confirmam
-- a validação completa, mas apenas depois da leitura de um relatório íntegro.

alter table public.nf_processamentos
  add column if not exists lancamento_conferencia_pendente boolean not null default false;

create or replace function public.nf_conciliar_lancamentos_v2(
  p_lancados text[],
  p_verificados text[],
  p_revisao text[]
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_verificados integer := 0;
  v_lancados integer := 0;
  v_revisao integer := 0;
begin
  -- Todas as NFs enviadas são reavaliadas contra o relatório completo.
  -- Em caso de erro de leitura, o aplicativo não deve chamar esta RPC.
  update public.nf_processamentos p
     set lancamento_verificado_em = now(),
         lancado_em = case
           when p.id::text = any(coalesce(p_lancados, array[]::text[]))
             then coalesce(p.lancado_em, now())
           else null
         end,
         lancamento_conferencia_pendente = (
           p.id::text = any(coalesce(p_revisao, array[]::text[]))
         )
   where p.id::text = any(coalesce(p_verificados, array[]::text[]))
     and upper(coalesce(p.tipo_documento, 'NF-e')) = 'NF-E'
     and p.enviado_em is not null;

  get diagnostics v_verificados = row_count;

  select count(*) into v_lancados
    from public.nf_processamentos p
   where p.id::text = any(coalesce(p_verificados, array[]::text[]))
     and p.id::text = any(coalesce(p_lancados, array[]::text[]))
     and p.lancado_em is not null and p.enviado_em is not null
     and upper(coalesce(p.tipo_documento, 'NF-e')) = 'NF-E';

  select count(*) into v_revisao
    from public.nf_processamentos p
   where p.id::text = any(coalesce(p_verificados, array[]::text[]))
     and p.lancamento_conferencia_pendente
     and p.enviado_em is not null
     and upper(coalesce(p.tipo_documento, 'NF-e')) = 'NF-E';

  return jsonb_build_object(
    'ok', true, 'verificados', v_verificados,
    'lancados', v_lancados, 'revisao', v_revisao
  );
end;
$$;

revoke all on function public.nf_conciliar_lancamentos_v2(text[], text[], text[]) from public;
grant execute on function public.nf_conciliar_lancamentos_v2(text[], text[], text[]) to anon, authenticated;
