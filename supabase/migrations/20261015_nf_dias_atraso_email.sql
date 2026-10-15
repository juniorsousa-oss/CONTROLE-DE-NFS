-- Regra única de dias úteis vencidos (24h equivalentes, fração sobe).
-- Exclui sábado e domingo, sem excluir feriados, conforme a política existente.
create or replace function public.nf_dias_atraso_uteis(
  p_vencimento timestamptz, p_referencia timestamptz default now()
) returns integer language sql stable set search_path = public, pg_temp as $$
  select case when p_vencimento is null or p_referencia is null
      or p_referencia <= p_vencimento then 0
  else coalesce((
    select ceil(
      sum(
        case when extract(isodow from dia) < 6
        then greatest(extract(epoch from (
          least(p_referencia at time zone 'America/Sao_Paulo', dia + interval '1 day')
          - greatest(p_vencimento at time zone 'America/Sao_Paulo', dia)
        )), 0)
        else 0 end
      ) / 86400.0
    )::integer
    from generate_series(
      date_trunc('day',p_vencimento at time zone 'America/Sao_Paulo'),
      date_trunc('day',p_referencia at time zone 'America/Sao_Paulo'),
      interval '1 day'
    ) as dias(dia)
  ),0)
  end;
$$;
revoke all on function public.nf_dias_atraso_uteis(timestamptz,timestamptz) from public,anon,authenticated;
grant execute on function public.nf_dias_atraso_uteis(timestamptz,timestamptz) to service_role;

create or replace function public.nf_email_claim(p_modo text, p_destinatarios text, p_cc text default '')
returns jsonb language plpgsql security definer set search_path = public, pg_temp
as $$
declare
  v_sync record;
  v_config record;
  v_dia date := (now() at time zone 'America/Sao_Paulo')::date;
  v_quant integer;
  v_items jsonb;
  v_ids jsonb;
  v_id uuid;
  v_limit integer;
begin
  if p_modo not in ('TESTE','PRODUCAO') then
    raise exception 'MODO_INVALIDO';
  end if;
  if length(trim(coalesce(p_destinatarios,''))) < 6 then
    raise exception 'DESTINATARIO_NAO_CONFIGURADO';
  end if;
  perform pg_advisory_xact_lock(hashtext('nf_email_notificacoes'));
  select version_token, status, synced_at
    into v_sync from public.setta_consumer_sync_state
    where consumer_key='controle_nfs' and source_key='nf';
  if not found or v_sync.status <> 'ATUALIZADO' then
    return jsonb_build_object('status','SEM_STSUP01_VALIDO');
  end if;
  select * into v_config from public.nf_email_controle where singleton=true;
  if p_modo = 'PRODUCAO' then
    if not coalesce(v_config.producao_ativa,false) then
      return jsonb_build_object('status','PRODUCAO_DESATIVADA');
    end if;
    if v_sync.version_token = v_config.versao_baseline then
      return jsonb_build_object('status','AGUARDANDO_NOVA_VERSAO');
    end if;
    if exists(
      select 1 from public.nf_email_notificacoes
      where modo='PRODUCAO' and source_version=v_sync.version_token
    ) then
      return jsonb_build_object('status','VERSAO_JA_PROCESSADA');
    end if;
  end if;
  v_limit := case when p_modo='TESTE' then 4 else 2 end;
  if (select count(*) from public.nf_email_notificacoes
      where modo=p_modo and data_local=v_dia) >= v_limit then
    return jsonb_build_object('status','LIMITE_DIARIO');
  end if;
  with elegiveis as (
    select p.id,p.numero_nf,p.fornecedor_padrao,p.natureza,p.enviado_em,
      coalesce(nullif(p.arquivo_final,''),p.arquivo_original) as arquivo,
      public.nf_dias_atraso_uteis(public.nf_prazo_vencimento_24h(p.enviado_em),now()) as dias_atraso
    from public.nf_processamentos p
    where p.enviado_em is not null
      and p.lancamento_verificado_em is not null
      and p.lancado_em is null
      and not coalesce(p.lancamento_conferencia_pendente,false)
      and public.nf_prazo_natureza_elegivel(p.tipo_documento,p.natureza)
      and p.lancamento_verificado_em > public.nf_prazo_vencimento_24h(p.enviado_em)
      and now() > public.nf_prazo_vencimento_24h(p.enviado_em)
  )
  select count(*),
   coalesce(jsonb_agg(jsonb_build_object(
     'id', id::text,
     'nf', coalesce(numero_nf,''),
     'fornecedor',coalesce(fornecedor_padrao,''),
     'natureza', coalesce(natureza,''),
     'enviado_em',to_char(enviado_em at time zone 'America/Sao_Paulo','DD/MM/YYYY HH24:MI'),
     'arquivo',coalesce(arquivo,''),
     'dias_atraso', coalesce(dias_atraso,0)
   ) order by numero_nf,fornecedor_padrao), '[]'::jsonb),
   coalesce(jsonb_agg(to_jsonb(id::text) order by id), '[]'::jsonb)
  into v_quant,v_items,v_ids from elegiveis;
  if v_quant=0 then
    return jsonb_build_object('status','SEM_PENDENCIAS');
  end if;
  if v_quant>500 then
    return jsonb_build_object('status','EXCESSO_REGISTROS','quantidade',v_quant);
  end if;
  insert into public.nf_email_notificacoes
    (modo,source_version,data_local,status,destinatarios,cc,qtd_nfs,nf_ids)
  values
    (p_modo,v_sync.version_token,v_dia,'EM_PROCESSAMENTO',
     p_destinatarios,coalesce(p_cc,''),v_quant,v_ids)
  returning id into v_id;
  return jsonb_build_object(
    'status','PRONTO','id',v_id,'source_version',v_sync.version_token,
    'quantidade',v_quant,'items',v_items,'data_local',v_dia
  );
end;
$$;
revoke execute on function public.nf_email_claim(text,text,text) from public,anon,authenticated;
grant execute on function public.nf_email_claim(text,text,text) to service_role;

