-- Acesso não interativo do Streamlit à biblioteca fiscal privada.
-- O token em texto claro permanece exclusivamente nos Secrets do Streamlit.
create table if not exists public.nf_xml_app_tokens (
 app_id text primary key,
 token_sha256 text not null check (token_sha256 ~ '^[0-9a-f]{64}$'),
 ativo boolean not null default true,
 criado_em timestamptz not null default now()
);
alter table public.nf_xml_app_tokens enable row level security;
revoke all on table public.nf_xml_app_tokens from public,anon,authenticated;
grant select,insert,update on table public.nf_xml_app_tokens to service_role;
