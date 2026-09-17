# CONTROLE DE NFs — SETTA

Protótipo Streamlit para automatizar o fluxo atual de Notas Fiscais:

1. upload em lote dos PDFs;
2. leitura do DANFE e OCR como contingência;
3. extração da chave da NF-e, CNPJ, número, série e vencimento;
4. vínculo do fornecedor pela base cadastral;
5. tela obrigatória de conferência antes da renomeação;
6. renomeação no padrão `VENC. DD.MM - NUMERO - FORNECEDOR.pdf`;
7. geração de ZIP com os PDFs originais apenas renomeados;
8. histórico de metadados, sem armazenar PDF no banco.

## Regra de vencimento

Quando existem várias parcelas, o sistema usa o **primeiro vencimento localizado no bloco FATURA/DUPLICATAS**.

## Regra de fornecedor

Ordem de tentativa:

- CNPJ exato;
- raiz do CNPJ quando houver uma única correspondência;
- similaridade do nome do emitente;
- revisão manual pelo operador.

## Executar localmente

```bash
pip install -r requirements.txt
streamlit run streamlit_app.py
```

Para OCR local, instale também Tesseract com idioma português. No Streamlit Community Cloud, `packages.txt` já solicita os pacotes do sistema.

## Supabase

O arquivo `supabase_schema.sql` contém a estrutura planejada para fornecedores, registros de processamento e configurações. Os PDFs **não** são armazenados no Supabase.

## Status do protótipo

A primeira versão usa a base inicial `data/fornecedores.csv` e mantém alterações visuais/fornecedores em sessão. A próxima etapa é persistir essas tabelas no Supabase e conectar o fluxo de e-mail.
