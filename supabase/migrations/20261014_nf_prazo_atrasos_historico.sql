-- Histórico permanente do primeiro atraso de NF-e elegível ao acompanhamento
-- de 24h (contam noites, não contam fins de semana).
-- Uma NF gera no máximo uma ocorrência histórica por registro id.
-- Esta tabela não tem FK para preservar auditoria mesmo que a NF seja excluída.

create table if not exists public.nf_prazo_atrasos (
  nf_id uuid primary key,
  numero_nf text not null default '',
  fornecedor text not null default '',
  natureza text not null default '',
  nome_arquivo text not null default '',
  enviado_em timestamptz not null,
  prazo_em timestamptz not null,
  verificado_em timestamptz not null,
  registrado_em timestamptz not null default now(),
  origem text not null default 'STSUP01'
);
create index if not exists nf_prazo_atrasos_registrado_idx
  on public.nf_prazo_atrasos (registrado_em desc);
alter table public.nf_prazo_atrasos enable row level security;
revoke all on public.nf_prazo_atrasos from public, anon, authenticated;
grant select on public.nf_prazo_atrasos to anon, authenticated;
drop policy if exists nf_prazo_atrasos_leitura on public.nf_prazo_atrasos;
create policy nf_prazo_atrasos_leitura
  on public.nf_prazo_atrasos for select to anon, authenticated using (true);

create or replace function public.nf_prazo_natureza_elegivel(p_tipo text, p_natureza text)
returns boolean language sql immutable set search_path = public
as $$
  select
    regexp_replace(
      translate(upper(coalesce(p_tipo,'')),
        'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
        'AAAAAEEEEIIIIOOOOOUUUUC'),
      '[^A-Z0-9]','','g'
    ) in ('NFE','NOTAFISCALELETRONICA')
    and regexp_replace(
      translate(upper(coalesce(p_natureza,'')),
        'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
        'AAAAAEEEEIIIIOOOOOUUUUC'),
      '[^A-Z0-9]+',' ','g'
    ) like '%COMPRA DE MATERIA PRIMA%';
$$;

create or replace function public.nf_prazo_vencimento_24h(p_enviado_em timestamptz)
returns timestamptz
language plpgsql stable set search_path = public
as $$
declare
  v_data timestamp;
  v_dia integer;
  v_limite time;
  v_proxima timestamp;
  v_restante interval := interval '24 hours';
begin
  if p_enviado_em is null then return null; end if;
  v_data := p_enviado_em at time zone 'America/Sao_Paulo';

  -- Ajustar somente o INÍCIO da contagem.
  loop
    v_dia := extract(isodow from v_data)::int;
    if v_dia >= 6 then
      v_data := date_trunc('day', v_data) + make_interval(days => 8-v_dia, hours => 7);
      continue;
    end if;
    if v_data::time < time '07:00' then
      v_data := date_trunc('day', v_data) + interval '7 hours';
      exit;
    end if;
    v_limite := case when v_dia = 5 then time '16:00' else time '18:00' end;
    if v_data::time > v_limite then
      v_data := date_trunc('day', v_data) + interval '1 day 7 hours';
      continue;
    end if;
    exit;
  end loop;

  -- Somar 24h corridas; sábado e domingo não consomem o relógio.
  loop
    v_dia := extract(isodow from v_data)::int;
    if v_dia >= 6 then
      v_data := date_trunc('day', v_data) + make_interval(days => 8-v_dia);
      continue;
    end if;
    v_proxima := date_trunc('day', v_data) + interval '1 day';
    if v_restante < (v_proxima - v_data) then
      v_data := v_data + v_restante;
      exit;
    end if;
    v_restante := v_restante - (v_proxima - v_data);
    v_data := v_proxima;
    if v_restante = interval '0' then
      if extract(isodow from v_data)::int >= 6 then
        v_data := date_trunc('day', v_data)
          + make_interval(days => 8 - extract(isodow from v_data)::int);
      end if;
      exit;
    end if;
  end loop;
  return v_data at time zone 'America/Sao_Paulo';
end;
$$;

create or replace function public.nf_gravar_primeiro_atraso()
returns trigger language plpgsql security definer set search_path = public, pg_temp
as $$
declare
  v_prazo timestamptz;
begin
  if new.enviado_em is null
     or new.lancamento_verificado_em is null
     or new.lancado_em is not null
     or coalesce(new.lancamento_conferencia_pendente, false)
     or not public.nf_prazo_natureza_elegivel(new.tipo_documento, new.natureza)
  then
    return new;
  end if;
  v_prazo := public.nf_prazo_vencimento_24h(new.enviado_em);
  if new.lancamento_verificado_em <= v_prazo then
    return new;
  end if;
  insert into public.nf_prazo_atrasos
    (nf_id,numero_nf,fornecedor,natureza,nome_arquivo,
     enviado_em,prazo_em,verificado_em,origem)
  values
    (new.id,coalesce(new.numero_nf,''),coalesce(new.fornecedor_padrao,''),
     coalesce(new.natureza,''),coalesce(new.arquivo_final,new.arquivo_original,''),
     new.enviado_em,v_prazo,new.lancamento_verificado_em,'STSUP01')
  on conflict (nf_id) do nothing;
  return new;
end;
$$;

drop trigger if exists trg_nf_primeiro_atraso on public.nf_processamentos;
create trigger trg_nf_primeiro_atraso
  after insert or update of enviado_em, lancamento_verificado_em,
    lancado_em, lancamento_conferencia_pendente, natureza, tipo_documento
  on public.nf_processamentos
  for each row execute function public.nf_gravar_primeiro_atraso();

-- Contabilizar somente as pendências já comprováveis com a base atual.
-- Não reconstruir atrasos antigos de NFs já lançadas, sem evidência histórica.
insert into public.nf_prazo_atrasos
  (nf_id,numero_nf,fornecedor,natureza,nome_arquivo,
   enviado_em,prazo_em,verificado_em,origem)
select p.id,coalesce(p.numero_nf,''),coalesce(p.fornecedor_padrao,''),
  coalesce(p.natureza,''),coalesce(p.arquivo_final,p.arquivo_original,''),
  p.enviado_em, public.nf_prazo_vencimento_24h(p.enviado_em),
  p.lancamento_verificado_em, 'IMPLANTACAO'
from public.nf_processamentos p
where p.enviado_em is not null
  and p.lancamento_verificado_em is not null
  and p.lancado_em is null
  and not coalesce(p.lancamento_conferencia_pendente,false)
  and public.nf_prazo_natureza_elegivel(p.tipo_documento,p.natureza)
  and p.lancamento_verificado_em > public.nf_prazo_vencimento_24h(p.enviado_em)
on conflict (nf_id) do nothing;

revoke all on function public.nf_gravar_primeiro_atraso() from public, anon, authenticated;
