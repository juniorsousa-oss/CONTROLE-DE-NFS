-- Biblioteca fiscal SETTA: armazenamento privado, sem leitura pública.
insert into storage.buckets(id,name,public,file_size_limit,allowed_mime_types)
values ('nf-xml-library','nf-xml-library',false,5242880,array['application/xml','text/xml','application/octet-stream']::text[])
on conflict (id) do update set public=false,file_size_limit=5242880,allowed_mime_types=excluded.allowed_mime_types;

create table if not exists public.nf_xml_permissoes (
 user_id uuid primary key references public.operahub_users(id) on delete cascade,
 perfil text not null check (perfil in ('OPERADOR','ADMIN')),
 concedido_por uuid,
 concedido_em timestamptz not null default now()
);
create table if not exists public.nf_xml_sessoes (
 token uuid primary key,
 user_id uuid not null references public.operahub_users(id) on delete cascade,
 expira_em timestamptz not null,
 criado_em timestamptz not null default now()
);
create index if not exists nf_xml_sessoes_expira_idx on public.nf_xml_sessoes(expira_em);

create table if not exists public.nf_xml_documentos (
 id uuid primary key default gen_random_uuid(),
 tipo text not null check (tipo in ('NFE','CTE')),
 chave text not null unique check (chave ~ '^[0-9]{44}$'),
 numero text not null,
 cnpj_emitente text not null,
 cnpj_destinatario text not null default '',
 status_fiscal text not null default '',
 refs_nfe jsonb not null default '[]'::jsonb check (jsonb_typeof(refs_nfe)='array'),
 arquivo_nome text not null,
 storage_path text not null unique,
 sha256 text not null check (sha256 ~ '^[0-9a-f]{64}$'),
 tamanho_bytes integer not null check(tamanho_bytes>0 and tamanho_bytes<=5242880),
 origem text not null check (origem in ('MANUAL','API')),
 importado_por uuid references public.operahub_users(id),
 importado_em timestamptz not null default now()
);
create index if not exists nf_xml_docs_numero on public.nf_xml_documentos(tipo,numero);
create index if not exists nf_xml_docs_emitente on public.nf_xml_documentos(cnpj_emitente);
create index if not exists nf_xml_docs_data on public.nf_xml_documentos(importado_em desc);
create index if not exists nf_xml_docs_refs on public.nf_xml_documentos using gin(refs_nfe);

create table if not exists public.nf_xml_importacoes (
 id bigint generated always as identity primary key,
 documento_id uuid references public.nf_xml_documentos(id),
 arquivo_nome text not null,
 resultado text not null check(resultado in ('INCLUIDO','DUPLICADO','CONFLITO','INVALIDO')),
 mensagem text not null default '',
 origem text not null check(origem in ('MANUAL','API')),
 usuario_id uuid references public.operahub_users(id),
 criado_em timestamptz not null default now()
);
create index if not exists nf_xml_importacoes_data on public.nf_xml_importacoes(criado_em desc);

alter table public.nf_xml_permissoes enable row level security;
alter table public.nf_xml_sessoes enable row level security;
alter table public.nf_xml_documentos enable row level security;
alter table public.nf_xml_importacoes enable row level security;
revoke all on public.nf_xml_permissoes,public.nf_xml_sessoes,public.nf_xml_documentos,public.nf_xml_importacoes from public,anon,authenticated;
grant select,insert,update,delete on public.nf_xml_permissoes,public.nf_xml_sessoes to service_role;
grant select,insert,update on public.nf_xml_documentos,public.nf_xml_importacoes to service_role;
grant usage,select on sequence public.nf_xml_importacoes_id_seq to service_role;

-- Sem políticas para anon/authenticated em storage.objects; somente backend service_role tem acesso.
