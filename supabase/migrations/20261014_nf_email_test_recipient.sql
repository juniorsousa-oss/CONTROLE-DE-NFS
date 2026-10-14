-- Destinatário de homologação isolado dos endereços de produção.
-- Alteração do valor pela administração do banco, não pelo aplicativo público.
alter table public.nf_email_controle
  add column if not exists destinatario_teste text not null default '';
