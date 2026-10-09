# Controle de NFs — Integração automática privada dos XMLs

A Etapa 2 passa a pesquisar e baixar XMLs automaticamente pela API privada da Biblioteca, sem exigir login de operador.

## Configuração única

No painel administrativo do Streamlit Cloud do aplicativo nfssetta.streamlit.app:

1. Acessar **Manage app → Settings → Secrets**.
2. Adicionar a variável **NF_XML_AUTOMATION_TOKEN** (fornecida ao administrador fora do repositório GitHub).
3. Salvar e reiniciar o aplicativo, se o Streamlit solicitar.

Exemplo de formato (não é um token real):
```toml
NF_XML_AUTOMATION_TOKEN = "TOKEN_PRIVADO_FORNECIDO_AO_ADMINISTRADOR"
```

A credencial tem hash SHA-256 gravado em tabela privada Supabase e só autoriza **match** e **download** de XML; importação, consulta ampla, permissões e login continuam exigindo usuário SETTA.

A credencial **não** deve ser salva em GitHub, arquivos de exemplo públicos, JS de navegador ou exportações.

## Comportamento

- Na Etapa 1, as NFs adicionadas pela tratativa Protheus entram na seleção ativa.
- Na Etapa 2, as NFs da seleção ativa são comparadas por NF/CNPJ com documentos já vinculados.
- Documentos faltantes são mostrados com NF e CNPJ. Campos sem vencimento devem ser corrigidos pelo operador.
- O aplicativo pesquisa e baixa XMLs disponíveis usando a credencial do servidor (sem nova tela de login).
- Se a credencial ainda não estiver instalada, a Etapa 2 permite upload manual sem liberar a biblioteca anonimamente.
- Na Etapa 3, vínculo de CT-e é revalidado por chave fiscal e NF inequívoca; divergências bloqueiam somente a geração até correção.

## Segurança

- Bucket XML privado e RLS.
- Token de serviço limitado a match/download, sem permissão de upload, listagem ou administração.
- Recomendável rotacionar token quando houver mudança de responsável ou suspeita de exposição.
