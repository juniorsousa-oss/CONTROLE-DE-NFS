-- SETTA - NF-e: feriados, prazo de 24h e bloqueio de cobranças automáticas.
-- Aplicado em produção em 23/11/2026. Execute somente após existir a base
-- nf_email_controle, nf_email_notificacoes e nf_processamentos.
-- Referência municipal: Patos de Minas/MG.
-- Carnaval e pontos facultativos não são feriados automaticamente.

BEGIN;

create table if not exists public.nf_feriados_adicionais (
  data date primary key,
  descricao text not null,
  ativo boolean not null default true,
  criado_em timestamptz not null default now()
);
alter table public.nf_feriados_adicionais enable row level security;
revoke all on table public.nf_feriados_adicionais from anon, authenticated;

CREATE OR REPLACE FUNCTION public.nf_data_pascoa(p_ano integer)
 RETURNS date
 LANGUAGE plpgsql
 IMMUTABLE
 SET search_path TO 'pg_catalog'
AS $function$
declare
  a int; b int; c int; d int; e int; f int; g int; h int;
  i int; k int; l int; m int; base int;
begin
  if p_ano not between 1583 and 9999 then return null; end if;
  a := p_ano % 19;
  b := p_ano / 100;
  c := p_ano % 100;
  d := b / 4;
  e := b % 4;
  f := (b + 8) / 25;
  g := (b - f + 1) / 3;
  h := (19*a + b - d - g + 15) % 30;
  i := c / 4;
  k := c % 4;
  l := (32 + 2*e + 2*i - h - k) % 7;
  m := (a + 11*h + 22*l) / 451;
  base := h + l - 7*m + 114;
  return make_date(p_ano, base / 31, (base % 31) + 1);
end;
$function$;

CREATE OR REPLACE FUNCTION public.nf_eh_dia_util(p_data date)
 RETURNS boolean
 LANGUAGE sql
 STABLE SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
  select p_data is not null
    and extract(isodow from p_data) between 1 and 5
    and to_char(p_data, 'MM-DD') not in (
      '01-01','04-21','05-01','09-07','10-12','11-02','11-15','11-20','12-25',
      '05-24','06-13','08-15'
    )
    and p_data <> (public.nf_data_pascoa(extract(year from p_data)::int) - 2)
    and p_data <> (public.nf_data_pascoa(extract(year from p_data)::int) + 60)
    and not exists (
      select 1 from public.nf_feriados_adicionais f
      where f.data = p_data and f.ativo
    );
$function$;

CREATE OR REPLACE FUNCTION public.nf_prazo_vencimento_24h(p_enviado_em timestamp with time zone)
 RETURNS timestamp with time zone
 LANGUAGE plpgsql
 STABLE
 SET search_path TO 'public', 'pg_temp'
AS $function$
declare
  v_data timestamp;
  v_limite time;
  v_proxima timestamp;
  v_restante interval := interval '24 hours';
begin
  if p_enviado_em is null then return null; end if;
  v_data := p_enviado_em at time zone 'America/Sao_Paulo';
  -- O inicio so ocorre na janela da empresa e em dia util.
  loop
    if not public.nf_eh_dia_util(v_data::date) then
      v_data := date_trunc('day',v_data) + interval '1 day 7 hours';
      continue;
    end if;
    if v_data::time < time '07:00' then
      v_data := date_trunc('day',v_data) + interval '7 hours';
      exit;
    end if;
    v_limite := case when extract(isodow from v_data)=5
                then time '16:00' else time '18:00' end;
    if v_data::time > v_limite then
      v_data := date_trunc('day',v_data) + interval '1 day 7 hours';
      continue;
    end if;
    exit;
  end loop;
  -- Contagem de 24 horas corridas dentro dos dias uteis,
  -- sem pausar a noite; fim de semana e feriados nao consomem o prazo.
  loop
    if not public.nf_eh_dia_util(v_data::date) then
      v_data := date_trunc('day',v_data) + interval '1 day';
      continue;
    end if;
    v_proxima := date_trunc('day',v_data) + interval '1 day';
    if v_restante < (v_proxima - v_data) then
      v_data := v_data + v_restante;
      exit;
    end if;
    v_restante := v_restante - (v_proxima - v_data);
    v_data := v_proxima;
    if v_restante = interval '0' then
      while not public.nf_eh_dia_util(v_data::date) loop
        v_data := date_trunc('day',v_data) + interval '1 day';
      end loop;
      exit;
    end if;
  end loop;
  return v_data at time zone 'America/Sao_Paulo';
end;
$function$;

CREATE OR REPLACE FUNCTION public.nf_dias_atraso_uteis(p_vencimento timestamp with time zone, p_referencia timestamp with time zone DEFAULT now())
 RETURNS integer
 LANGUAGE sql
 STABLE
 SET search_path TO 'public', 'pg_temp'
AS $function$
  select case when p_vencimento is null or p_referencia is null
     or p_referencia <= p_vencimento then 0
  else coalesce((
    select ceil(sum(
      case when public.nf_eh_dia_util(dia::date)
      then greatest(extract(epoch from (
        least(p_referencia at time zone 'America/Sao_Paulo', dia + interval '1 day')
        - greatest(p_vencimento at time zone 'America/Sao_Paulo', dia)
      )), 0)
      else 0 end
    ) / 86400.0)::integer
    from generate_series(
      date_trunc('day', p_vencimento at time zone 'America/Sao_Paulo'),
      date_trunc('day', p_referencia at time zone 'America/Sao_Paulo'),
      interval '1 day'
    ) as dias(dia)
  ), 0)
  end;
$function$;

CREATE OR REPLACE FUNCTION public.nf_email_claim(p_modo text, p_destinatarios text, p_cc text DEFAULT ''::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
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
  if p_modo = 'PRODUCAO' and not public.nf_eh_dia_util(v_dia) then
    return jsonb_build_object('status','FERIADO_OU_FIM_DE_SEMANA');
  end if;
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
    -- Produção somente após uma nova carga válida, posterior à ativação.
    if v_config.producao_inicio is null
       or v_sync.synced_at is null
       or v_sync.synced_at <= v_config.producao_inicio
       or now() - v_sync.synced_at > interval '24 hours'
    then
      return jsonb_build_object('status','AGUARDANDO_STSUP01_ATUALIZADO');
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
$function$;

CREATE OR REPLACE FUNCTION public.nf_email_piloto_claim(p_destinatarios text, p_cc text DEFAULT ''::text)
 RETURNS jsonb
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
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
  if not public.nf_eh_dia_util(v_date) then
    return jsonb_build_object('status','FERIADO_OU_FIM_DE_SEMANA');
  end if;
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
$function$;

CREATE OR REPLACE FUNCTION public.nf_email_pulse()
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
declare
  v_token text;
  v_request bigint;
  v_local timestamp := now() at time zone 'America/Sao_Paulo';
  v_sync record;
  v_cfg record;
begin
  if not public.nf_eh_dia_util(v_local::date) then return null; end if;
  if extract(isodow from v_local)>5 or v_local::time<time '07:00'
     or v_local::time>time '18:00'
  then return null; end if;

  select * into v_cfg from public.nf_email_controle where singleton=true;
  if not found or not v_cfg.producao_ativa or v_cfg.producao_inicio is null
  then return null; end if;

  select version_token,status,synced_at into v_sync
  from public.setta_consumer_sync_state
  where consumer_key='controle_nfs' and source_key='nf';

  if not found or v_sync.status <> 'ATUALIZADO'
     or v_sync.synced_at is null
     or v_sync.synced_at <= v_cfg.producao_inicio
     or now()-v_sync.synced_at > interval '24 hours'
     or v_sync.version_token=v_cfg.versao_baseline
  then return null; end if;

  if exists(
    select 1 from public.nf_email_notificacoes
    where modo='PRODUCAO' and source_version=v_sync.version_token
  ) then return null; end if;

  if (select count(*) from public.nf_email_notificacoes
      where modo='PRODUCAO'
      and data_local=v_local::date) >= 2
  then return null; end if;

  -- Não chamar o Power Automate com lista vazia.
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

  select decrypted_secret into v_token
  from vault.decrypted_secrets
  where name='NFS_EMAIL_API_TOKEN' limit 1;

  if v_token is null or length(v_token)<32 then return null; end if;

  select net.http_post(
    url => 'https://cuixazpxkvniqldmmnth.supabase.co/functions/v1/nf-email-api',
    body => '{"mode":"PRODUCAO"}'::jsonb,
    headers => jsonb_build_object(
      'Content-Type','application/json',
      'x-nfs-notification-token',v_token
    ),
    timeout_milliseconds => 20000
  ) into v_request;
  return v_request;
end;
$function$;

CREATE OR REPLACE FUNCTION public.nf_email_piloto_pulse()
 RETURNS bigint
 LANGUAGE plpgsql
 SECURITY DEFINER
 SET search_path TO 'public', 'pg_temp'
AS $function$
declare
  v_token text;
  v_request bigint;
  v_sync record;
  v_controle record;
  v_hoje date := (now() at time zone 'America/Sao_Paulo')::date;
  v_hora time := (now() at time zone 'America/Sao_Paulo')::time;
  v_dia int := extract(isodow from (now() at time zone 'America/Sao_Paulo'));
begin
  if not public.nf_eh_dia_util(v_hoje) then return null; end if;
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
$function$;

comment on function public.nf_eh_dia_util(date) is
'Calendario SETTA para cobrancas de NF: sab/dom + feriados nacionais, Data Magna MG e municipais de Patos de Minas; pontos facultativos nao entram sem cadastro explicito.';

COMMIT;

-- Verificação sem envio de e-mail:
-- select public.nf_eh_dia_util('2026-11-20'); -- false
-- select public.nf_eh_dia_util('2026-11-23'); -- true
