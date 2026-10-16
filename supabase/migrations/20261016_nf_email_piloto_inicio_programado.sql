-- Bloqueio de execução antes do início agendado, com fuso gravado em timestamptz.
-- Seguro mesmo quando piloto_ativo=true e a janela estiver no futuro.
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
