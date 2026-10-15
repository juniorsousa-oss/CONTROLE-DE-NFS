-- Piloto de acompanhamento automático de NFs por 48 horas.
-- Estado inicial DESLIGADO. Não dispara sem credencial em Vault e ativação explícita.
alter table public.nf_email_controle
  add column if not exists piloto_ativo boolean not null default false,
  add column if not exists piloto_inicio timestamptz,
  add column if not exists piloto_ate timestamptz,
  add column if not exists piloto_baseline text;

alter table public.nf_email_notificacoes
  drop constraint if exists nf_email_notificacoes_modo_check;
alter table public.nf_email_notificacoes
  add constraint nf_email_notificacoes_modo_check
  check (modo in ('TESTE','PRODUCAO','PILOTO'));

create unique index if not exists nf_email_notificacoes_versao_piloto_uniq
  on public.nf_email_notificacoes(source_version) where modo='PILOTO';

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
  if p_modo not in ('TESTE','PRODUCAO','PILOTO') then
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
  -- Em piloto, somente versões novas do STSUP01, depois da ativação,
  -- dentro da janela de 48h e sem base desatualizada.
  if p_modo='PILOTO' then
    if not coalesce(v_config.piloto_ativo,false)
       or v_config.piloto_inicio is null
       or v_config.piloto_ate is null
       or now() < v_config.piloto_inicio
       or now() >= v_config.piloto_ate
    then
      return jsonb_build_object('status','PILOTO_INATIVO');
    end if;
    if v_sync.version_token=v_config.piloto_baseline
       or v_sync.synced_at < v_config.piloto_inicio
    then
      return jsonb_build_object('status','AGUARDANDO_NOVA_VERSAO');
    end if;
    if v_sync.synced_at is null or now()-v_sync.synced_at > interval '24 hours' then
      return jsonb_build_object('status','STSUP01_DESATUALIZADO');
    end if;
    if exists(
      select 1 from public.nf_email_notificacoes
      where modo='PILOTO' and source_version=v_sync.version_token
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


-- Uma única porta administrativa para iniciar a janela, nunca por clientes/anon.
create or replace function public.nf_email_piloto_ativar()
returns jsonb language plpgsql security definer set search_path=public, pg_temp
as $$
declare
  v_token_disponivel boolean;
  v_base text;
  v_destinatarios text;
  v_inicio timestamptz := now();
begin
  if exists (select 1 from public.nf_email_controle where singleton and producao_ativa)
  then return jsonb_build_object('status','PRODUCAO_ATIVA'); end if;

  select exists(
    select 1 from vault.decrypted_secrets
    where name='NFS_EMAIL_API_TOKEN' and length(decrypted_secret)>=32
  ) into v_token_disponivel;
  if not v_token_disponivel
  then return jsonb_build_object('status','AGUARDANDO_TOKEN_NO_VAULT'); end if;

  select version_token into v_base
  from public.setta_consumer_sync_state
  where consumer_key='controle_nfs' and source_key='nf' and status='ATUALIZADO';
  if v_base is null
  then return jsonb_build_object('status','SEM_STSUP01_VALIDO'); end if;

  select destinatario_teste into v_destinatarios
  from public.nf_email_controle where singleton;
  if coalesce(length(btrim(v_destinatarios)),0) < 6
  then return jsonb_build_object('status','DESTINATARIOS_NAO_CONFIGURADOS'); end if;

  update public.nf_email_controle set
    piloto_ativo=true,
    piloto_inicio=v_inicio,
    piloto_ate=v_inicio+interval '48 hours',
    piloto_baseline=v_base,
    alterado_em=now()
  where singleton=true;
  return jsonb_build_object(
    'status','PILOTO_ATIVO',
    'inicio',v_inicio,
    'fim',v_inicio+interval '48 hours',
    'primeira_versao_ignorada',v_base
  );
end;
$$;
revoke all on function public.nf_email_piloto_ativar() from public,anon,authenticated;
-- Apenas administrador do banco pode ativar; nem service_role pode alterar o período.
revoke all on function public.nf_email_piloto_ativar() from service_role;

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
  -- Horário comercial, dias úteis. Um único cron por hora.
  if v_dia>5 or v_hora < time '07:00' or v_hora > time '18:00' then return null; end if;

  select version_token,status,synced_at into v_sync
  from public.setta_consumer_sync_state
  where consumer_key='controle_nfs' and source_key='nf';
  if not found or v_sync.status <> 'ATUALIZADO'
     or v_sync.synced_at is null
     or now()-v_sync.synced_at > interval '24 hours'
     or v_sync.synced_at < v_controle.piloto_inicio
     or v_sync.version_token=v_controle.piloto_baseline
  then return null; end if;

  if exists(
    select 1 from public.nf_email_notificacoes
    where modo='PILOTO' and source_version=v_sync.version_token
  ) then return null; end if;
  if (select count(*) from public.nf_email_notificacoes
      where modo='PILOTO' and data_local=v_hoje) >= 2 then return null; end if;

  -- Zero NFs vencidas -> NÃO acionar a API, NÃO gerar e-mail e NÃO
  -- consumir o limite. Usar exatamente a mesma elegibilidade da fila.
  if not exists(
    select 1 from public.nf_processamentos p
    where p.enviado_em is not null
      and p.lancamento_verificado_em is not null
      and p.lancado_em is null
      and not coalesce(p.lancamento_conferencia_pendente,false)
      and public.nf_prazo_natureza_elegivel(p.tipo_documento,p.natureza)
      and p.lancamento_verificado_em > public.nf_prazo_vencimento_24h(p.enviado_em)
      and now() > public.nf_prazo_vencimento_24h(p.enviado_em)
  ) then return null; end if;

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
revoke all on function public.nf_email_piloto_pulse() from public,anon,authenticated;
grant execute on function public.nf_email_piloto_pulse() to service_role;

-- Cron seguro: verifica a janela e expira o piloto automaticamente.
-- Agendamento desligado até a etapa final (token do Vault validado).
