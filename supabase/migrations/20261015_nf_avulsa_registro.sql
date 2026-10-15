-- O fluxo convencional permanece inalterado.
-- As chaves fiscais são identidade estável, evitando duplicações entre
-- registro convencional e impressão avulsa, inclusive em concorrência.
create unique index if not exists nf_processamentos_nfe_chave_uniq
on public.nf_processamentos(chave_nfe)
where chave_nfe ~ '^[0-9]{44}$';

create unique index if not exists nf_processamentos_cte_chave_uniq
on public.nf_processamentos(chave_cte)
where chave_cte ~ '^[0-9]{44}$';

create or replace function public.nf_registrar_avulsos(p_rows jsonb)
returns jsonb language plpgsql security definer
set search_path = public, pg_temp
as $$
declare
    item jsonb;
    doc_tipo text;
    doc_chave text;
    vistos text[] := array[]::text[];
    qtd integer := 0;
    inseridos integer := 0;
    total integer := 0;
begin
    if p_rows is null or jsonb_typeof(p_rows) <> 'array' then
        raise exception 'LOTE_AVULSO_INVALIDO';
    end if;
    total := jsonb_array_length(p_rows);
    if total < 1 or total > 60 then
        raise exception 'LIMITE_AVULSO_INVALIDO';
    end if;
    perform pg_advisory_xact_lock(hashtext('nf_registrar_avulsos'));
    -- Validar TODO o lote antes do primeiro INSERT; a função é atômica.
    for item in select value from jsonb_array_elements(p_rows)
    loop
        doc_tipo := item->>'tipo_documento';
        doc_chave := case when doc_tipo='NF-e'
            then item->>'chave_nfe' when doc_tipo='CT-e'
            then item->>'chave_cte' else null end;
        if doc_chave is null or doc_chave !~ '^[0-9]{44}$'
          or (doc_tipo='NF-e' and substr(doc_chave,21,2)<>'55')
          or (doc_tipo='CT-e' and substr(doc_chave,21,2)<>'57')
          or doc_chave=any(vistos) then
            raise exception 'CHAVE_FISCAL_AVULSA_INVALIDA_OU_DUPLICADA';
        end if;
        vistos := array_append(vistos,doc_chave);
        if item->>'origem_dados' <> 'IMPRESSAO_AVULSA_XML'
          or item->>'status' <> 'REALIZADO'
          or coalesce(item->>'lote_id','') not like 'AVULSA-%'
          or nullif(item->>'arquivo_final','') is null
          or nullif(item->>'arquivo_original','') is null
          or nullif(item->>'empresa_sigla','') not in ('SEN','SEE','STA')
          or item ? 'enviado_em' then
            raise exception 'CAMPOS_OBRIGATORIOS_AVULSO_INVALIDOS';
        end if;
        if doc_tipo='NF-e' and
          (nullif(item->>'vencimento','') is null
            or nullif(item->>'numero_nf','') is null
            or nullif(item->>'cnpj_fornecedor','') is null)
        then
            raise exception 'NF_AVULSA_INCOMPLETA';
        end if;
        if doc_tipo='CT-e' and
          (nullif(item->>'numero_cte','') is null
            or nullif(item->>'nfs_vinculadas','') is null
            or nullif(item->>'cnpj_tomador','') is null)
        then
            raise exception 'CTE_AVULSO_INCOMPLETO';
        end if;
    end loop;

    for item in select value from jsonb_array_elements(p_rows)
    loop
        doc_tipo := item->>'tipo_documento';
        insert into public.nf_processamentos (
          lote_id,arquivo_original,arquivo_final,tipo_documento,
          chave_nfe,numero_nf,serie,cnpj_fornecedor,fornecedor_padrao,vencimento,
          natureza,prioridade_mrp,pre_nota_status,pre_nota_em,metodo_fornecedor,
          confianca,status,operador,recebido_em,pdf_criado_em,processado_em,
          cr,desc_cr,recebedor,origem_dados,data_chegada,carimbo_aplicado,
          numero_cte,chave_cte,nfs_vinculadas,transportadora,
          cnpj_transportadora,empresa_sigla,tomador_servico,cnpj_tomador
        )
        values (
          item->>'lote_id',item->>'arquivo_original',item->>'arquivo_final',doc_tipo,
          nullif(item->>'chave_nfe',''),nullif(item->>'numero_nf',''),
          nullif(item->>'serie',''),nullif(item->>'cnpj_fornecedor',''),
          nullif(item->>'fornecedor_padrao',''),
          nullif(item->>'vencimento','')::date,
          nullif(item->>'natureza',''),false,
          nullif(item->>'pre_nota_status',''),
          nullif(item->>'pre_nota_em','')::date,
          nullif(item->>'metodo_fornecedor',''),
          nullif(item->>'confianca','')::integer,
          'REALIZADO',nullif(item->>'operador',''),
          coalesce(nullif(item->>'recebido_em','')::timestamptz,now()),
          coalesce(nullif(item->>'pdf_criado_em','')::timestamptz,now()),
          coalesce(nullif(item->>'processado_em','')::timestamptz,now()),
          nullif(item->>'cr',''),nullif(item->>'desc_cr',''),
          nullif(item->>'recebedor',''), 'IMPRESSAO_AVULSA_XML',
          nullif(item->>'data_chegada','')::date,
          coalesce((item->>'carimbo_aplicado')::boolean,false),
          nullif(item->>'numero_cte',''),nullif(item->>'chave_cte',''),
          nullif(item->>'nfs_vinculadas',''),
          nullif(item->>'transportadora',''),
          nullif(item->>'cnpj_transportadora',''),
          nullif(item->>'empresa_sigla',''),
          nullif(item->>'tomador_servico',''),nullif(item->>'cnpj_tomador','')
        )
        on conflict do nothing;
        get diagnostics qtd = row_count;
        inseridos := inseridos + qtd;
    end loop;
    return jsonb_build_object('ok',true,'inseridos',inseridos,
                              'existentes',total-inseridos,'total',total);
end;
$$;
revoke all on function public.nf_registrar_avulsos(jsonb)
from public, anon, authenticated;
grant execute on function public.nf_registrar_avulsos(jsonb)
to anon, authenticated;
