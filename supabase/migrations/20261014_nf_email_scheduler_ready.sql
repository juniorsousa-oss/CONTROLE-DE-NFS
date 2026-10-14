-- Preparar o disparo periódico via pg_cron + pg_net.
-- NÃO agenda o job, não habilita produção e não envia e-mail nesta migração.
-- A ativação só ocorrerá após teste e confirmação do operador.
-- O segredo NFS_EMAIL_API_TOKEN deve ficar no Supabase Vault.

create or replace function public.nf_email_pulse()
returns bigint language plpgsql security definer
set search_path = public, pg_temp
as $$
declare
  v_token text;
  v_request bigint;
begin
  if not exists(
    select 1 from public.nf_email_controle
    where singleton=true and producao_ativa=true
  ) then
    return null;
  end if;

  select decrypted_secret into v_token
  from vault.decrypted_secrets
  where name = 'NFS_EMAIL_API_TOKEN'
  limit 1;

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
$$;
revoke execute on function public.nf_email_pulse() from public,anon,authenticated;
grant execute on function public.nf_email_pulse() to service_role;
