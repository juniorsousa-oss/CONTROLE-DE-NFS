-- Unifica critérios do prazo de lançamento de NFs avulsas e convencionais.
-- Natureza MATERIA PRIMA (sem COMPRA DE) é usada nas impressões avulsas.
-- Atualiza APENAS o predicado: sem editar registros, status, datas ou histórico.
-- Mantém fora CT-es, remessas, manutenção e naturezas não enquadradas.
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
    and (
      regexp_replace(
        translate(upper(coalesce(p_natureza,'')),
          'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
          'AAAAAEEEEIIIIOOOOOUUUUC'),
        '[^A-Z0-9]+',' ','g'
      ) like '%COMPRA DE MATERIA PRIMA%'
      or btrim(regexp_replace(
        translate(upper(coalesce(p_natureza,'')),
          'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
          'AAAAAEEEEIIIIOOOOOUUUUC'),
        '[^A-Z0-9]+',' ','g'
      )) = 'MATERIA PRIMA'
      or regexp_replace(
        translate(upper(coalesce(p_natureza,'')),
          'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
          'AAAAAEEEEIIIIOOOOOUUUUC'),
        '[^A-Z0-9]+',' ','g'
      ) like '%EPI GERA ESTOQUE%'
    );
$$;

-- O trigger existente se mantém. Não reprocessar NFs já lançadas ou criar
-- registros históricos retroativos sem nova evidência do STSUP01.
