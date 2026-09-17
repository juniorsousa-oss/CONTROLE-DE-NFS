-- Estrutura planejada para a próxima etapa.
-- Nenhum PDF é armazenado no Supabase: somente metadados, fornecedores e configurações.

create extension if not exists pgcrypto;

create table if not exists public.nf_fornecedores (
  id uuid primary key default gen_random_uuid(),
  cnpj text not null unique,
  nome_padrao text not null,
  aliases text default '',
  ativo boolean not null default true,
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

create table if not exists public.nf_processamentos (
  id uuid primary key default gen_random_uuid(),
  lote_id text not null,
  arquivo_original text not null,
  arquivo_final text not null,
  tipo_documento text not null default 'NF-e',
  chave_nfe text,
  numero_nf text,
  serie text,
  cnpj_fornecedor text,
  fornecedor_padrao text,
  vencimento date,
  metodo_fornecedor text,
  confianca integer,
  status text not null default 'PROCESSADO',
  operador text,
  processado_em timestamptz not null default now()
);

create index if not exists nf_processamentos_lote_idx on public.nf_processamentos(lote_id);
create index if not exists nf_processamentos_nf_idx on public.nf_processamentos(numero_nf);
create index if not exists nf_processamentos_cnpj_idx on public.nf_processamentos(cnpj_fornecedor);

create table if not exists public.nf_configuracoes (
  chave text primary key,
  valor jsonb not null,
  atualizado_em timestamptz not null default now()
);
