-- SETTA Controle de NFs: fila segura de notificações contábeis.
-- Sem envios em produção até ativação explícita, URL e remetente configurados.
create table if not exists public.nf_email_notificacoes (
  id uuid primary key default gen_random_uuid(),
  modo text not null check (modo in ('TESTE','PRODUCAO')),
  source_version text not null,
  data_local date not null,
  status text not null check (status in ('EM_PROCESSAMENTO','ACEITO','INCERTO','FALHA')),
  destinatarios text not null default '',
  cc text not null default '',
  qtd_nfs integer not null default 0,
  nf_ids jsonb not null default '[]'::jsonb,
  iniciado_em timestamptz not null default now(),
  finalizado_em timestamptz,
  erro text
);
create index if not exists nf_email_notificacoes_data_idx
  on public.nf_email_notificacoes(data_local, modo, iniciado_em desc);
create unique index if not exists nf_email_notificacoes_versao_producao_uniq
  on public.nf_email_notificacoes(source_version) where modo = 'PRODUCAO';
alter table public.nf_email_notificacoes enable row level security;
revoke all on public.nf_email_notificacoes from public, anon, authenticated;
grant select, insert, update on public.nf_email_notificacoes to service_role;

create table if not exists public.nf_email_controle (
  singleton boolean primary key default true check (singleton),
  producao_ativa boolean not null default false,
  versao_baseline text,
  alterado_em timestamptz not null default now()
);
alter table public.nf_email_controle enable row level security;
revoke all on public.nf_email_controle from public, anon, authenticated;
grant select on public.nf_email_controle to service_role;
insert into public.nf_email_controle(singleton,producao_ativa,versao_baseline)
select true,false,s.version_token
from public.setta_consumer_sync_state s
where s.consumer_key = 'controle_nfs' and s.source_key='nf'
on conflict (singleton) do nothing;

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
      coalesce(nullif(p.arquivo_final,''),p.arquivo_original) as arquivo
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
     'arquivo',coalesce(arquivo,'')
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

create or replace function public.nf_email_finish(
  p_id uuid,p_status text,p_erro text default null
)
returns boolean language plpgsql security definer set search_path = public, pg_temp
as $$
begin
  if p_status not in ('ACEITO','INCERTO','FALHA') then
    raise exception 'STATUS_INVALIDO';
  end if;
  update public.nf_email_notificacoes
     set status=p_status,finalizado_em=now(),erro=left(p_erro,500)
   where id=p_id and status='EM_PROCESSAMENTO';
  return found;
end;
$$;
revoke execute on function public.nf_email_finish(uuid,text,text) from public,anon,authenticated;
grant execute on function public.nf_email_finish(uuid,text,text) to service_role;
