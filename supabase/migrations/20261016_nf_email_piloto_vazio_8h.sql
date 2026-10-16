-- Ajuste exclusivo do PILOTO: 08h + segunda mensagem por versão nova.
-- Em produção, nenhuma mensagem vazia é autorizada.

create or replace function public.nf_email_piloto_claim(
  p_destinatarios text, p_cc text default ''
) returns jsonb language plpgsql security definer set search_path=public,pg_temp
as $$
declare
  v_sync record;
  v_config record;
  v_date date := (now() at time zone 'America/Sao_Paulo')::date;
  v_time time := (now() at time zone 'America/Sao_Paulo')::time;
  v_dow integer := extract(isodow from now() at time zone 'America/Sao_Paulo');
  v_count integer;
  v_last_sent timestamptz;
  v_fresh boolean := false;
  v_version text;
  v_reason text;
  v_quant integer := 0;
  v_items jsonb := '[]'::jsonb;
  v_ids jsonb := '[]'::jsonb;
  v_id uuid;
begin
  if length(trim(coalesce(p_destinatarios,''))) < 6 then
    return jsonb_build_object('status','DESTINATARIOS_NAO_CONFIGURADOS');
  end if;
  perform pg_advisory_xact_lock(hashtext('nf_email_notificacoes'));
  select * into v_config from public.nf_email_controle where singleton=true;
  if not found or not v_config.piloto_ativo or v_config.producao_ativa
    or v_config.piloto_inicio is null or v_config.piloto_ate is null
    or now()<v_config.piloto_inicio or now()>=v_config.piloto_ate
  then return jsonb_build_object('status','PILOTO_INATIVO'); end if;
  if v_dow>5 or v_time < time '08:00' or v_time > time '18:00'
  then return jsonb_build_object('status','FORA_JANELA'); end if;
  select count(*), max(iniciado_em) into v_count,v_last_sent
  from public.nf_email_notificacoes
  where modo='PILOTO' and data_local=v_date;
  if v_count>=2 then return jsonb_build_object('status','LIMITE_DIARIO'); end if;
  select version_token,status,synced_at into v_sync
  from public.setta_consumer_sync_state
  where consumer_key='controle_nfs' and source_key='nf';
  v_fresh := coalesce(v_sync.status='ATUALIZADO'
     and v_sync.synced_at >= v_config.piloto_inicio
     and v_sync.synced_at <= now()
     and now()-v_sync.synced_at <= interval '24 hours'
     and v_sync.version_token is not null
     and v_sync.version_token <> v_config.piloto_baseline,false);
  if v_fresh and exists(
    select 1 from public.nf_email_notificacoes
    where modo='PILOTO' and source_version=v_sync.version_token
  ) then v_fresh:=false; end if;

  if v_count>0 then
    -- Segundo aviso: só se o STSUP01 recebeu uma versão inédita
    -- DEPOIS do primeiro envio do dia.
    if not v_fresh or v_sync.synced_at <= v_last_sent then
      return jsonb_build_object('status','AGUARDANDO_NOVA_VERSAO');
    end if;
  end if;

  if v_fresh then
    with elegiveis as (
      select p.id,p.numero_nf,p.fornecedor_padrao,p.natureza,p.enviado_em,
        coalesce(nullif(p.arquivo_final,''),p.arquivo_original) as arquivo,
        public.nf_dias_atraso_uteis(
          public.nf_prazo_vencimento_24h(p.enviado_em),now()
        ) as dias_atraso
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
        'id',id::text,
        'nf',coalesce(numero_nf,''),
        'fornecedor',coalesce(fornecedor_padrao,''),
        'natureza',coalesce(natureza,''),
        'enviado_em',to_char(enviado_em at time zone 'America/Sao_Paulo','DD/MM/YYYY HH24:MI'),
        'dias_atraso',coalesce(dias_atraso,0),
        'arquivo',coalesce(arquivo,'')
      ) order by numero_nf,fornecedor_padrao),'[]'::jsonb),
      coalesce(jsonb_agg(to_jsonb(id::text) order by id),'[]'::jsonb)
    into v_quant,v_items,v_ids from elegiveis;
    if v_quant>500 then return jsonb_build_object('status','EXCESSO_REGISTROS'); end if;
    v_version:=v_sync.version_token;
    v_reason:=case when v_quant=0 then 'SEM_PENDENCIAS'
      else 'COM_PENDENCIAS' end;
  else
    -- Sem fonte atualizada: não declarar que inexistem NFs.
    -- A mensagem sinalizará que o STSUP01 ainda precisa ser atualizado.
    v_version:='PILOTO-STATUS-'||to_char(v_date,'YYYY-MM-DD');
    v_reason:='AGUARDANDO_STSUP01';
  end if;

  insert into public.nf_email_notificacoes
    (modo,source_version,data_local,status,destinatarios,cc,qtd_nfs,nf_ids)
  values
    ('PILOTO',v_version,v_date,'EM_PROCESSAMENTO',
     p_destinatarios,coalesce(p_cc,''),v_quant,v_ids)
  returning id into v_id;

  return jsonb_build_object(
    'status','PRONTO','id',v_id,'source_version',v_version,
    'quantidade',v_quant,'items',v_items,'data_local',v_date,
    'tipo_piloto',v_reason
  );
end;
$$;
revoke all on function public.nf_email_piloto_claim(text,text) from public,anon,authenticated;
grant execute on function public.nf_email_piloto_claim(text,text) to service_role;

create or replace function public.nf_email_piloto_pulse()
returns bigint language plpgsql security definer
set search_path=public, pg_temp
as $$
declare
  v_token text;
  v_request bigint;
  v_sync record;
  v_controle record;
  v_hoje date := (now() at time zone 'America/Sao_Paulo')::date;
  v_hora time := (now() at time zone 'America/Sao_Paulo')::time;
  v_dia int := extract(isodow from (now() at time zone 'America/Sao_Paulo'));
begin
  select * into v_controle from public.nf_email_controle where singleton=true;
  if not found or not v_controle.piloto_ativo then return null; end if;

  if v_controle.piloto_ate is null or now()>=v_controle.piloto_ate then
    update public.nf_email_controle set piloto_ativo=false,alterado_em=now()
    where singleton=true and piloto_ativo=true;
    return null;
  end if;
  -- Programação futura: nunca executar o piloto antes do instante de início.
  if v_controle.piloto_inicio is null or now() < v_controle.piloto_inicio
  then return null; end if;
  -- Horário comercial, dias úteis. Um único cron por hora.
  if v_dia>5 or v_hora < time '08:00' or v_hora > time '18:00' then return null; end if;

  -- O primeiro e-mail de cada dia útil é enviado às 08h,
  -- ainda que a base não tenha sido atualizada ou não haja NFs elegíveis.
  -- Um segundo e-mail exige NOVA VERSÃO após o primeiro disparo.
  if (select count(*) from public.nf_email_notificacoes
      where modo='PILOTO' and data_local=v_hoje) >= 2 then return null; end if;

  if exists(select 1 from public.nf_email_notificacoes
            where modo='PILOTO' and data_local=v_hoje) then
    select version_token, status, synced_at into v_sync
    from public.setta_consumer_sync_state
    where consumer_key='controle_nfs' and source_key='nf';
    if not found or v_sync.status <> 'ATUALIZADO'
      or v_sync.version_token is null or v_sync.synced_at is null
      or v_sync.synced_at < v_controle.piloto_inicio
      or now()-v_sync.synced_at > interval '24 hours'
      or exists (
        select 1 from public.nf_email_notificacoes
        where modo='PILOTO' and source_version=v_sync.version_token
      ) or v_sync.synced_at <= (
        select max(iniciado_em) from public.nf_email_notificacoes
        where modo='PILOTO' and data_local=v_hoje
      )
    then return null; end if;
  end if;

  select decrypted_secret into v_token from vault.decrypted_secrets
  where name='NFS_EMAIL_API_TOKEN' limit 1;
  if v_token is null or length(v_token)<32 then return null; end if;

  select net.http_post(
    url => 'https://cuixazpxkvniqldmmnth.supabase.co/functions/v1/nf-email-api',
    body => '{"mode":"PILOTO"}'::jsonb,
    headers => jsonb_build_object(
      'Content-Type','application/json',
      'x-nfs-notification-token',v_token
    ),
    timeout_milliseconds => 20000
  ) into v_request;
  return v_request;
end;
$$;
