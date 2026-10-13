"""Conferência de lançamento de NF-e na STSUP01 (coluna AE/TES).

Nunca confirma por número isolado ou por similaridade de razão social.
O vínculo aproximado exige conferência e qualquer item sem TES impede a
confirmação da nota inteira.
"""
from __future__ import annotations

import math


def tes_preenchida(valor) -> bool:
    """Considera célula realmente preenchida, não NaN nem sentinelas vazias."""
    if valor is None:
        return False
    if isinstance(valor, float) and (math.isnan(valor) or valor == 0):
        return False
    if isinstance(valor, (int, float)) and valor == 0:
        return False
    texto = str(valor).strip()
    return texto.casefold() not in {"", "nan", "nat", "none", "null", "<na>", "0", "0.0", "-", "—"}


def validar_lancamento_nf(
    nf_enviada: dict,
    linhas: list[dict],
    *,
    normalizar_nome,
    similaridade,
    normalizar_codigo,
    somente_digitos,
) -> str:
    """Retorna CONFIRMADO, AGUARDANDO_LANCAMENTO, CONFERIR_FORNECEDOR ou NAO_ENCONTRADA.

    As linhas recebidas já devem estar restritas ao mesmo número de NF.
    'cnpj_resolvido' é CNPJ inferido somente por cadastro de código+razão,
    nunca é inventado com base no número da nota.
    """
    if not linhas:
        return "NAO_ENCONTRADA"

    nome = normalizar_nome(nf_enviada.get("fornecedor_padrao"))
    cnpj = somente_digitos(nf_enviada.get("cnpj_fornecedor"))
    if len(cnpj) != 14:
        cnpj = ""
    codigo = normalizar_codigo(nf_enviada.get("fornecedor_codigo"))
    scored = []
    ambiguas = False

    for item in linhas:
        outro_nome = normalizar_nome(item.get("fornecedor"))
        outro_cnpj = somente_digitos(item.get("cnpj_resolvido"))
        if len(outro_cnpj) != 14:
            outro_cnpj = ""
        outro_codigo = normalizar_codigo(item.get("fornecedor_codigo"))

        # CNPJ de ambos os lados conhecido e divergente bloqueia qualquer
        # fallback por nome (inclusive razão social 100% igual).
        if cnpj and outro_cnpj and cnpj != outro_cnpj:
            if nome and outro_nome and (nome == outro_nome or similaridade(nome, outro_nome) >= 82):
                ambiguas = True
            continue

        score = 0
        if cnpj and outro_cnpj == cnpj:
            score = 3
        elif codigo and codigo == outro_codigo and (not nome or nome == outro_nome):
            score = 2
        elif nome and nome == outro_nome:
            score = 1
        elif nome and outro_nome and similaridade(nome, outro_nome) >= 82:
            ambiguas = True
        else:
            # Uma NF com o mesmo número não confirma um fornecedor desconhecido.
            ambiguas = True

        if score:
            scored.append((score, item, outro_cnpj, outro_nome, outro_codigo))

    if not scored:
        return "CONFERIR_FORNECEDOR" if ambiguas else "NAO_ENCONTRADA"

    maior = max(entry[0] for entry in scored)
    melhores = [entry for entry in scored if entry[0] == maior]

    # Incapacidade de diferenciar dois fornecedores com mesmo nome/código
    # ou CNPJs distintos impede confirmação automática.
    docs = {entry[2] for entry in melhores if entry[2]}
    if len(docs) > 1:
        return "CONFERIR_FORNECEDOR"

    # Reunir todos os itens daquele fornecedor, inclusive linhas sem TES.
    # Se houver código comum, não ignorar itens com razão social abreviada.
    if maior == 3:
        relacionadas = [
            item for item in linhas
            if somente_digitos(item.get("cnpj_resolvido")) == cnpj
            or (
                not somente_digitos(item.get("cnpj_resolvido"))
                and nome
                and normalizar_nome(item.get("fornecedor")) == nome
            )
        ]
    elif maior == 2:
        codigo_eleito = melhores[0][4]
        relacionadas = [
            item for item in linhas
            if normalizar_codigo(item.get("fornecedor_codigo")) == codigo_eleito
            and (
                not cnpj or not somente_digitos(item.get("cnpj_resolvido"))
                or somente_digitos(item.get("cnpj_resolvido")) == cnpj
            )
        ]
    else:
        nome_eleito = melhores[0][3]
        relacionadas = [
            item for item in linhas
            if normalizar_nome(item.get("fornecedor")) == nome_eleito
            and (
                not cnpj or not somente_digitos(item.get("cnpj_resolvido"))
                or somente_digitos(item.get("cnpj_resolvido")) == cnpj
            )
        ]

    if not relacionadas:
        return "CONFERIR_FORNECEDOR"
    if not all(tes_preenchida(item.get("tes")) for item in relacionadas):
        return "AGUARDANDO_LANCAMENTO"
    return "CONFIRMADO"
