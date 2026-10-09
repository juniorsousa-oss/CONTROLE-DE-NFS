# Biblioteca operacional de XML — proposta para validação

Objetivo: não exigir que a equipe reenvie a pasta inteira a cada lote ou a cada nova sessão do aplicativo.

## Fonte, segurança e persistência
- Criar uma biblioteca em bucket **privado** no Supabase Storage, com índice PostgreSQL de metadados.
- Liberar gravação/leitura por API autenticada e escopo de acesso SETTA; nunca expor XMLs em bucket público nem token service_role no Streamlit.
- Importação inicial única (pasta ou ZIP); depois, aceitar apenas arquivos novos/alterados, deduplicados pelo SHA-256 e pela chave fiscal de 44 dígitos.
- Manter data de importação, origem, nome, versão, operador e relatório de rejeições de XML inválido.
- O cache operacional é distinto do arquivo fiscal legal; não automatizar exclusão de XML original.

## Vínculos e trabalho diário
- Ao chegar à etapa Documentos Fiscais, consultar a biblioteca por chave de acesso + CNPJ de emitente/destinatário e comparar com as NFs selecionadas.
- Para CT-e, consultar as chaves referenciadas e vínculo NF-e, validar tomador SETTA e apresentar os CT-e na confirmação da etapa 03.
- Selecionar automaticamente apenas documentos com correspondência inequívoca, mantendo os demais em pendência para revisão.
- Exibir indicadores encontrados/faltantes/duplicados e um campo de upload apenas para complementação do lote.
- Permitir reprocessar documento corrigido sem fazer nova carga integral.

## Validação antes da liberação
1. Definir o provedor de origem (biblioteca privada ou pasta sincronizada), método de autenticação e responsável pelo upload.
2. Fazer importação piloto com NFs e CT-e de um lote de homologação; testar conflitos de chaves, duplicidades e registros não autorizados.
3. Só habilitar associação automática em produção depois de validar segregação de acesso e auditoria.
4. Não modificar o comportamento fiscal existente durante a fase piloto.

Status: **arquitetura proposta, ainda não publicada**; o cache atual em memória da sessão permanece funcionando.
