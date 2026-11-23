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

- É a única skill que pode ir à nuvem (Gemini), e só quando a pergunta é difícil ou o modelo local falha.
- Para a nuvem, só seguem memórias de contextos que também podem sair da máquina.
