-- Simulação isolada: não altera NF, não necessita de STSUP01 nem ativa produção.
-- Usa somente modo TESTE no histórico, com source_version marcada SIMULACAO:.
-- Consome o mesmo teto diário de quatro testes (simulação + homologação).
create or replace function public.nf_email_claim_simulation(p_destinatarios text)
returns jsonb language plpgsql security definer
set search_path = public, pg_temp
as $$
declare
  v_control record;
  v_id uuid := gen_random_uuid();
  v_date date := (now() at time zone 'America/Sao_Paulo')::date;
begin
  perform pg_advisory_xact_lock(hashtext('nf_email_notificacoes'));
  select destinatario_teste, producao_ativa
    into v_control from public.nf_email_controle
    where singleton=true;
  if not found or coalesce(v_control.producao_ativa,false) then
    return jsonb_build_object('status','SIMULACAO_BLOQUEADA');
  end if;
  if coalesce(p_destinatarios,'') = ''
     or p_destinatarios <> v_control.destinatario_teste
     or array_length(string_to_array(p_destinatarios,';'),1) <> 2 then
    return jsonb_build_object('status','DESTINATARIOS_NAO_CONFIGURADOS');
  end if;
  if (select count(*) from public.nf_email_notificacoes
      where modo='TESTE' and data_local=v_date) >= 4 then
    return jsonb_build_object('status','LIMITE_DIARIO');
  end if;
  insert into public.nf_email_notificacoes
    (id,modo,source_version,data_local,status,destinatarios,cc,qtd_nfs,nf_ids)
  values
    (v_id,'TESTE','SIMULACAO:'||v_id::text,v_date,'EM_PROCESSAMENTO',
     p_destinatarios,'',0,'[]'::jsonb);
  return jsonb_build_object(
    'status','PRONTO','id',v_id,
    'source_version','SIMULACAO:'||v_id::text,
    'quantidade',0,'items','[]'::jsonb,'data_local',v_date
  );
end;
$$;
revoke all on function public.nf_email_claim_simulation(text)
  from public, anon, authenticated;
grant execute on function public.nf_email_claim_simulation(text) to service_role;
