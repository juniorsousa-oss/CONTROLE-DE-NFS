-- Guardar a identidade original ao desconsiderar uma pré-nota.
-- A linha de auditoria (motivo/origem/operador) permanece no banco mesmo
-- quando ativo=false após lançamento comprovado.
alter table public.nf_documentos_desconsiderados
  add column if not exists identidades jsonb not null default '[]'::jsonb;

create or replace function public.nf_capturar_identidade_desconsiderada()
returns trigger language plpgsql security definer
set search_path = public, pg_temp as $$
declare
  v_identidades jsonb := '[]'::jsonb;
begin
  if not new.ativo then
    return new;
  end if;
  select coalesce(jsonb_agg(distinct jsonb_build_object(
      'cnpj', dados.cnpj, 'fornecedor', dados.fornecedor
    )), '[]'::jsonb)
  into v_identidades
  from (
    select regexp_replace(coalesce(p.cnpj,''),'[^0-9]','','g') as cnpj,
           trim(coalesce(p.fornecedor,'')) as fornecedor
    from public.nf_pre_notas_atual p
    where ltrim(regexp_replace(coalesce(p.numero_nf,''),'[^0-9]','','g'),'0')
          = ltrim(regexp_replace(coalesce(new.numero_nf,''),'[^0-9]','','g'),'0')
    union
    select regexp_replace(coalesce(n.cnpj_fornecedor,''),'[^0-9]','','g') as cnpj,
           trim(coalesce(n.fornecedor_padrao,'')) as fornecedor
    from public.nf_processamentos n
    where upper(coalesce(n.tipo_documento,'NF-E'))='NF-E'
      and ltrim(regexp_replace(coalesce(n.numero_nf,''),'[^0-9]','','g'),'0')
          = ltrim(regexp_replace(coalesce(new.numero_nf,''),'[^0-9]','','g'),'0')
  ) dados
  where (length(dados.cnpj)=14 or length(dados.fornecedor)>0);
  if jsonb_array_length(v_identidades)>0 then
    new.identidades = v_identidades;
  elsif tg_op='INSERT' or (tg_op='UPDATE' and not old.ativo) then
    -- Na reativação sem fornecedor conhecido, nunca herdar outra identidade.
    new.identidades = '[]'::jsonb;
  end if;
  return new;
end;
$$;

drop trigger if exists nf_gravar_identidade_exclusao
  on public.nf_documentos_desconsiderados;
create trigger nf_gravar_identidade_exclusao
before insert or update of ativo on public.nf_documentos_desconsiderados
for each row execute function public.nf_capturar_identidade_desconsiderada();

-- Recuperar, sem alterar status ou motivo, identidades ainda disponíveis
-- para exclusões antigas. Caso a NF já não exista nas bases, manter seguro.
update public.nf_documentos_desconsiderados d
set identidades = coalesce((
    select jsonb_agg(distinct jsonb_build_object(
      'cnpj', regexp_replace(coalesce(p.cnpj,''),'[^0-9]','','g'),
      'fornecedor', trim(coalesce(p.fornecedor,''))
    ))
    from public.nf_pre_notas_atual p
    where ltrim(regexp_replace(coalesce(p.numero_nf,''),'[^0-9]','','g'),'0')
          = ltrim(regexp_replace(coalesce(d.numero_nf,''),'[^0-9]','','g'),'0')
      and (length(regexp_replace(coalesce(p.cnpj,''),'[^0-9]','','g'))=14
           or nullif(trim(p.fornecedor),'') is not null)
  ), '[]'::jsonb)
where d.ativo and d.identidades='[]'::jsonb
  and exists (
    select 1 from public.nf_pre_notas_atual p
    where ltrim(regexp_replace(coalesce(p.numero_nf,''),'[^0-9]','','g'),'0')
          = ltrim(regexp_replace(coalesce(d.numero_nf,''),'[^0-9]','','g'),'0')
  );

revoke all on function public.nf_capturar_identidade_desconsiderada()
  from public, anon, authenticated;
