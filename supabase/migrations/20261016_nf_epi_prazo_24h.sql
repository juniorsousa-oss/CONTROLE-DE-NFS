-- Acrescenta EPI GERA ESTOQUE à mesma regra de 24h de matéria-prima.
-- Alteração retrocompatível em um único predicado utilizado pelo dashboard,
-- trigger de histórico e seleção para o piloto/produção de e-mail.
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
      or regexp_replace(
        translate(upper(coalesce(p_natureza,'')),
          'ÁÀÂÃÄÉÈÊËÍÌÎÏÓÒÔÕÖÚÙÛÜÇ',
          'AAAAAEEEEIIIIOOOOOUUUUC'),
        '[^A-Z0-9]+',' ','g'
      ) like '%EPI GERA ESTOQUE%'
    );
$$;
-- Não recriar ocorrências históricas de documentos já lançados:
-- não há prova de atraso anterior somente pela natureza.
