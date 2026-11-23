---
name: conversa-geral
description: Perguntas gerais, conversa e pedidos que não pertencem a outra skill. Use quando nenhuma outra skill se aplica.
contextos: [geral, outro]
estado: ativa
privacidade: nuvem-permitida
entradas: [texto, voz]
saidas: [texto]
versao: 1
---

# Conversa geral

Responde perguntas gerais com o modelo local, usando a memória semântica como contexto.

## Regras

- É a única skill que pode ir à nuvem (Gemini), e só quando a pessoa pede ("pergunta pro Gemini...", "pesquisa na internet...") ou quando o modelo local falha (M16).
- Para a nuvem, só seguem memórias de contextos que também podem sair da máquina.
