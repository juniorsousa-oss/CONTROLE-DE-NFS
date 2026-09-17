# CONTROLE DE NFs — SETTA

Aplicativo Streamlit para automatizar o fluxo operacional de Notas Fiscais sem armazenar os PDFs no Supabase.

## Fluxo NF-e

1. upload em lote dos PDFs;
2. leitura do DANFE e OCR como contingência;
3. extração da chave NF-e, CNPJ, número, série e primeiro vencimento;
4. vínculo do fornecedor pela base cadastral;
5. conferência obrigatória antes da renomeação;
6. preenchimento/validação da natureza interna;
7. cruzamento opcional com pré-notas e prioridade MRP;
8. renomeação no padrão "VENC. DD.MM - NUMERO - FORNECEDOR.pdf";
9. geração de ZIPs separados por natureza e por prioridade;
10. gravação dos metadados no Supabase e consulta no Dashboard.

## ZIPs

Padrão atual de teste:

- "DD-MM-AAAA - NOTAS FISCAIS - MP.zip"
- "DD-MM-AAAA - NOTAS FISCAIS - MP - PRIORIDADE.zip"

O padrão poderá ser refinado depois da validação operacional.

## Fornecedores

O cadastro não possui edição manual. A nova planilha passa por validação e, quando aprovada, substitui integralmente a base anterior.

Validações atuais:

- CNPJ com 14 dígitos e dígitos verificadores válidos;
- nome obrigatório;
- duplicidades consolidadas quando o nome é o mesmo;
- bloqueio de CNPJ duplicado associado a nomes diferentes;
- prévia da carga antes da substituição.

## Pré-notas

A tela Validação Pré-notas aceita CSV/XLSX, permite mapear as colunas do relatório e confronta os números das NFs com o histórico de documentos processados.

## Prioridade MRP

A tela Prioridade MRP cruza:

Produto urgente do MRP -> Produto no relatório de NFs -> Número da NF -> PDF processado

Se qualquer item de uma NF estiver na lista urgente, a NF inteira recebe prioridade e é separada em ZIP próprio da respectiva natureza.

## Dashboard

Registra e permite consultar:

- número da NF;
- fornecedor;
- vencimento;
- natureza;
- vínculo com pré-nota;
- prioridade MRP;
- data/hora do processamento;
- criação do PDF/ZIP;
- envio;
- operador.

A tabela filtrada pode ser exportada para Excel.

## Supabase

As tabelas e RPCs estão em supabase_schema.sql. Nenhum PDF é armazenado no Supabase.

O aplicativo procura a chave em:

- SUPABASE_ANON_KEY
- SUPABASE_KEY
- SUPABASE_PUBLISHABLE_KEY

Configure uma dessas chaves nos Secrets do Streamlit. A URL do projeto já está parametrizada no código.

## Executar localmente

pip install -r requirements.txt
streamlit run streamlit_app.py

Para OCR local, instale também o Tesseract. No Streamlit Community Cloud, packages.txt contém os pacotes do sistema.

## CT-e e XML

O módulo CT-e está reservado e será ativado após validação com documentos reais.

A geração de DANFE diretamente de XML/chave de acesso permanece como etapa avançada, dependente da confirmação do formato disponível no relatório do Protheus.
