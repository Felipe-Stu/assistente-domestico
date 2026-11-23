---
name: estoque
description: Consulta o que há em casa e registra quando um produto acabou. Use quando a pessoa pergunta se ainda tem algo ou avisa que um item terminou.
contextos: [inventario]
estado: ativa
privacidade: local
entradas: [texto, voz]
saidas: [texto]
versao: 1
execucao: roteiro
gatilhos:
  - acao: corrigir
    prioridade: 50
    padrao:
      - '^(?:ja\s+)?(?:acabou|acabaram|terminou|terminaram)\s+(?:o|a|os|as|meu|minha|meus|minhas|todo|toda)\b'
      - '^(?:o|a|os|as|meu|minha|meus|minhas)\s+[\w-]+(?:\s+[\w-]+)?\s+(?:ja\s+)?(?:acabou|acabaram|terminou|terminaram)[.!]?$'
  - acao: consultar
    prioridade: 60
    padrao:
      - '\bainda\s+(?:tenho|temos)\b'
      - '\b(?:tenho|temos)\b.{1,40}\bem casa\b'
      - '\b(?:meu|nosso|o)\s+estoque\b'
      - '\bem estoque\b'
---

# Estoque

Responde se um produto ainda está em casa, com base no controle de consumo.

## Como funciona hoje

- A consulta é feita por regras, sem modelo (`InventoryAssistant.consultar_estoque`).
- Alterações por texto ainda não existem; a resposta informa a limitação.

## Limitação conhecida

As compras ainda não alimentam o estoque (P1), então a consulta costuma vir vazia. Isso será resolvido nesta skill na V4.3.
