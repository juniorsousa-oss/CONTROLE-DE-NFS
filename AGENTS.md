# Diretrizes obrigatórias de desenvolvimento e validação — SETTA / Controle de NFs

Estas diretrizes valem para toda manutenção, correção, otimização e novo recurso neste repositório. Podem ser replicadas para outros aplicativos SETTA.

## Antes de modificar
1. Examinar a árvore completa e identificar todos os arquivos relacionados, suas dependências, testes, rotas de navegação, fluxo fiscal, banco e integrações. A revisão é de abrangência do repositório, não uma leitura integral desnecessária de arquivos binários em toda mudança.
2. Investigar o erro e reproduzi-lo com um caso determinístico sempre que possível; registrar o comportamento esperado e o resultado atual.
3. Verificar duplicação real de lógica, consultas repetidas, funções não referenciadas, CSS conflitante, efeitos de rerun, gerenciamento de estado, dimensões responsivas, chamadas de rede e custo de processamento.
4. Não apagar código, dados, integrações, validações, carimbos, controles fiscais ou funcionalidades por mera suspeita de inutilização. Primeiro rastrear chamadas internas/externas e criar regressões.

## Ao programar
5. Aplicar alterações pequenas e rastreáveis, preservando regras aprovadas de NFs, XML, CT-e, TOTVS, fornecedores, MRP, carimbos, ZIPs, autorização e persistência.
6. Não inferir CNPJ por número isolado de NF. Conferir código do fornecedor, documento fiscal, chave e emitente. Havendo ambiguidades, manter pendência para decisão humana.
7. Evitar operações custosas a cada clique/reexecução do Streamlit: indexar tabelas antes de cruzamentos, cachear leituras puras, preservar seleção, não disparar busca remota sem necessidade e usar downloads sem rerun.
8. Não utilizar substituições globais de CSS que prejudiquem sidebar, filtros, tabelas, desktop ou mobile.

## Portão de qualidade obrigatório ANTES de entregar
9. Executar compilação de TODOS os arquivos Python e auditoria estática do repositório.
10. Criar ou atualizar teste automatizado específico para a rotina modificada, contemplando sucesso, entradas ausentes/duplicadas, erro e casos limítrofes; medir custo relativo quando a alteração visa desempenho.
11. Rodar TODOS os testes de regressão e integrações relevantes no GitHub Actions no commit FINAL. O workflow deve disparar para QUALQUER arquivo alterado na branch principal ou PR, inclusive módulos auxiliares.
12. Em falha no CI, inspecionar logs, corrigir causa, executar novamente até obter sucesso. Não entregar uma mudança como validada se o último commit estiver com CI falho, pendente ou não executado.
13. Se alterar tela/layout, exigir também validação visual real (desktop e mobile, menu fechado e aberto, fluxo completo). Testes estáticos/AST NÃO substituem teste de navegação no navegador.
14. Se alterar Supabase/API, confirmar implantação real no ambiente previsto, compatibilidade e autorização. A aprovação do GitHub Actions, por si, NÃO confirma o funcionamento real em produção.
15. Não executar operações destrutivas ou modificar registros fiscais reais durante os testes. Preferir fixtures sintéticas, mocks e read-only.

## Como informar ao solicitante
16. Informar arquivos alterados, impacto no fluxo, quais testes realmente executaram, resultado, link do workflow e limitações ainda não verificadas.
17. Diferenciar claramente: IMPLEMENTADO NO CÓDIGO, TESTES AUTOMÁTICOS APROVADOS, API IMPLANTADA e VALIDADO VISUALMENTE EM PRODUÇÃO. Jamais confundir as etapas.
18. Se o acesso ao navegador ou ao ambiente de produção não estiver disponível, declarar isso. Nunca prometer ausência total de bugs sem evidência.
19. Não transferir testes básicos já automatizáveis para o usuário. A validação operacional final do usuário fica restrita às condições reais que não possam ser reproduzidas com segurança.

## Comandos de referência
- python -m compileall -q .
- python -m scripts.audit_quality
- python -m scripts.test_nf_mrp_index
- python -m scripts.test_nf_supplier_xml_fallback
- Testes adicionais são executados no workflow .github/workflows/central-nfs-ci.yml.

Este é o padrão mínimo. A qualidade do app precede a entrega, não é uma tarefa do usuário.
