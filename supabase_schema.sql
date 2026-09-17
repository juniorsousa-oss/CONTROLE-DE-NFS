-- CONTROLE DE NFs - SETTA
-- Nenhum PDF é armazenado no Supabase. Somente metadados, bases e configurações.

create extension if not exists pgcrypto;

create table if not exists public.nf_fornecedores (
  id uuid primary key default gen_random_uuid(),
  cnpj text not null unique,
  nome_padrao text not null,
  aliases text not null default '',
  ativo boolean not null default true,
  criado_em timestamptz not null default now(),
  atualizado_em timestamptz not null default now()
);

create table if not exists public.nf_fornecedor_importacoes (
  id uuid primary key default gen_random_uuid(),
  arquivo_nome text not null,
  total_linhas integer not null default 0,
  registros_validos integer not null default 0,
  registros_invalidos integer not null default 0,
  duplicados integer not null default 0,
  importado_em timestamptz not null default now()
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
  natureza text,
  prioridade_mrp boolean not null default false,
  pre_nota_status text,
  pre_nota_em date,
  metodo_fornecedor text,
  confianca integer,
  status text not null default 'PDF CRIADO',
  operador text,
  recebido_em timestamptz,
  pdf_criado_em timestamptz,
  enviado_em timestamptz,
  processado_em timestamptz not null default now()
);

create index if not exists nf_processamentos_lote_idx on public.nf_processamentos(lote_id);
create index if not exists nf_processamentos_nf_idx on public.nf_processamentos(numero_nf);
create index if not exists nf_processamentos_cnpj_idx on public.nf_processamentos(cnpj_fornecedor);
create index if not exists nf_processamentos_natureza_idx on public.nf_processamentos(natureza);
create index if not exists nf_processamentos_processado_idx on public.nf_processamentos(processado_em desc);

create table if not exists public.nf_configuracoes (
  chave text primary key,
  valor jsonb not null,
  atualizado_em timestamptz not null default now()
);

create table if not exists public.nf_pre_notas_atual (
  id uuid primary key default gen_random_uuid(),
  numero_nf text not null unique,
  status text,
  data_pre_nota date,
  natureza text,
  origem_arquivo text,
  atualizado_em timestamptz not null default now()
);

create table if not exists public.nf_pre_nota_importacoes (
  id uuid primary key default gen_random_uuid(),
  arquivo_nome text not null,
  total_linhas integer not null default 0,
  importado_em timestamptz not null default now()
);

alter table public.nf_fornecedores enable row level security;
alter table public.nf_fornecedor_importacoes enable row level security;
alter table public.nf_processamentos enable row level security;
alter table public.nf_configuracoes enable row level security;
alter table public.nf_pre_notas_atual enable row level security;
alter table public.nf_pre_nota_importacoes enable row level security;

-- Leitura pelo aplicativo. Escritas são feitas apenas pelas RPCs SECURITY DEFINER abaixo.
drop policy if exists nf_fornecedores_read on public.nf_fornecedores;
create policy nf_fornecedores_read on public.nf_fornecedores for select to anon, authenticated using (true);

drop policy if exists nf_fornecedor_importacoes_read on public.nf_fornecedor_importacoes;
create policy nf_fornecedor_importacoes_read on public.nf_fornecedor_importacoes for select to anon, authenticated using (true);

drop policy if exists nf_processamentos_read on public.nf_processamentos;
create policy nf_processamentos_read on public.nf_processamentos for select to anon, authenticated using (true);

drop policy if exists nf_configuracoes_read on public.nf_configuracoes;
create policy nf_configuracoes_read on public.nf_configuracoes for select to anon, authenticated using (true);

drop policy if exists nf_pre_notas_read on public.nf_pre_notas_atual;
create policy nf_pre_notas_read on public.nf_pre_notas_atual for select to anon, authenticated using (true);

drop policy if exists nf_pre_nota_importacoes_read on public.nf_pre_nota_importacoes;
create policy nf_pre_nota_importacoes_read on public.nf_pre_nota_importacoes for select to anon, authenticated using (true);

create or replace function public.nf_salvar_configuracao(p_chave text, p_valor jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
begin
  insert into public.nf_configuracoes(chave, valor, atualizado_em)
  values (p_chave, coalesce(p_valor, '{}'::jsonb), now())
  on conflict (chave) do update
    set valor = excluded.valor,
        atualizado_em = now();
  return jsonb_build_object('ok', true, 'chave', p_chave);
end;
$$;

create or replace function public.nf_substituir_fornecedores(
  p_rows jsonb,
  p_arquivo_nome text,
  p_total_linhas integer,
  p_validos integer,
  p_invalidos integer,
  p_duplicados integer
)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_count integer := 0;
begin
  if p_rows is null or jsonb_typeof(p_rows) <> 'array' then
    raise exception 'p_rows deve ser um array JSON';
  end if;

  delete from public.nf_fornecedores;

  insert into public.nf_fornecedores(cnpj, nome_padrao, aliases, ativo, criado_em, atualizado_em)
  select
    regexp_replace(coalesce(x->>'cnpj',''), '\D', '', 'g'),
    trim(coalesce(x->>'nome_padrao','')),
    trim(coalesce(x->>'aliases','')),
    coalesce((x->>'ativo')::boolean, true),
    now(), now()
  from jsonb_array_elements(p_rows) x
  where length(regexp_replace(coalesce(x->>'cnpj',''), '\D', '', 'g')) = 14
    and trim(coalesce(x->>'nome_padrao','')) <> '';

  get diagnostics v_count = row_count;

  insert into public.nf_fornecedor_importacoes(
    arquivo_nome, total_linhas, registros_validos, registros_invalidos, duplicados
  ) values (
    coalesce(p_arquivo_nome, 'fornecedores'),
    coalesce(p_total_linhas, 0),
    coalesce(p_validos, v_count),
    coalesce(p_invalidos, 0),
    coalesce(p_duplicados, 0)
  );

  return jsonb_build_object('ok', true, 'fornecedores', v_count);
end;
$$;

create or replace function public.nf_registrar_processamentos(p_rows jsonb)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_count integer := 0;
begin
  if p_rows is null or jsonb_typeof(p_rows) <> 'array' then
    raise exception 'p_rows deve ser um array JSON';
  end if;

  insert into public.nf_processamentos(
    lote_id, arquivo_original, arquivo_final, tipo_documento, chave_nfe,
    numero_nf, serie, cnpj_fornecedor, fornecedor_padrao, vencimento,
    natureza, prioridade_mrp, pre_nota_status, pre_nota_em, metodo_fornecedor,
    confianca, status, operador, recebido_em, pdf_criado_em, processado_em
  )
  select
    coalesce(x->>'lote_id',''),
    coalesce(x->>'arquivo_original',''),
    coalesce(x->>'arquivo_final',''),
    coalesce(x->>'tipo_documento','NF-e'),
    nullif(x->>'chave_nfe',''),
    nullif(x->>'numero_nf',''),
    nullif(x->>'serie',''),
    nullif(x->>'cnpj_fornecedor',''),
    nullif(x->>'fornecedor_padrao',''),
    nullif(x->>'vencimento','')::date,
    nullif(x->>'natureza',''),
    coalesce((x->>'prioridade_mrp')::boolean, false),
    nullif(x->>'pre_nota_status',''),
    nullif(x->>'pre_nota_em','')::date,
    nullif(x->>'metodo_fornecedor',''),
    nullif(x->>'confianca','')::integer,
    coalesce(nullif(x->>'status',''), 'PDF CRIADO'),
    nullif(x->>'operador',''),
    coalesce(nullif(x->>'recebido_em','')::timestamptz, now()),
    coalesce(nullif(x->>'pdf_criado_em','')::timestamptz, now()),
    coalesce(nullif(x->>'processado_em','')::timestamptz, now())
  from jsonb_array_elements(p_rows) x;

  get diagnostics v_count = row_count;
  return jsonb_build_object('ok', true, 'inseridos', v_count);
end;
$$;

create or replace function public.nf_marcar_enviados(p_ids text[], p_operador text default null)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_count integer := 0;
begin
  update public.nf_processamentos
     set enviado_em = now(),
         status = 'ENVIADO',
         operador = coalesce(nullif(p_operador,''), operador)
   where id::text = any(p_ids);
  get diagnostics v_count = row_count;
  return jsonb_build_object('ok', true, 'atualizados', v_count);
end;
$$;

create or replace function public.nf_substituir_pre_notas(p_rows jsonb, p_arquivo_nome text, p_total_linhas integer)
returns jsonb
language plpgsql
security definer
set search_path = public
as $$
declare
  v_count integer := 0;
begin
  if p_rows is null or jsonb_typeof(p_rows) <> 'array' then
    raise exception 'p_rows deve ser um array JSON';
  end if;

  delete from public.nf_pre_notas_atual;

  insert into public.nf_pre_notas_atual(numero_nf, status, data_pre_nota, natureza, origem_arquivo, atualizado_em)
  select
    trim(coalesce(x->>'numero_nf','')),
    nullif(trim(coalesce(x->>'status','')), ''),
    nullif(x->>'data_pre_nota','')::date,
    nullif(trim(coalesce(x->>'natureza','')), ''),
    coalesce(p_arquivo_nome, 'relatorio'),
    now()
  from jsonb_array_elements(p_rows) x
  where trim(coalesce(x->>'numero_nf','')) <> ''
  on conflict (numero_nf) do update
    set status = excluded.status,
        data_pre_nota = excluded.data_pre_nota,
        natureza = excluded.natureza,
        origem_arquivo = excluded.origem_arquivo,
        atualizado_em = now();

  get diagnostics v_count = row_count;

  insert into public.nf_pre_nota_importacoes(arquivo_nome, total_linhas)
  values (coalesce(p_arquivo_nome, 'relatorio'), coalesce(p_total_linhas, v_count));

  return jsonb_build_object('ok', true, 'registros', v_count);
end;
$$;

revoke all on function public.nf_salvar_configuracao(text, jsonb) from public;
revoke all on function public.nf_substituir_fornecedores(jsonb, text, integer, integer, integer, integer) from public;
revoke all on function public.nf_registrar_processamentos(jsonb) from public;
revoke all on function public.nf_marcar_enviados(text[], text) from public;
revoke all on function public.nf_substituir_pre_notas(jsonb, text, integer) from public;

grant execute on function public.nf_salvar_configuracao(text, jsonb) to anon, authenticated;
grant execute on function public.nf_substituir_fornecedores(jsonb, text, integer, integer, integer, integer) to anon, authenticated;
grant execute on function public.nf_registrar_processamentos(jsonb) to anon, authenticated;
grant execute on function public.nf_marcar_enviados(text[], text) to anon, authenticated;
grant execute on function public.nf_substituir_pre_notas(jsonb, text, integer) to anon, authenticated;
