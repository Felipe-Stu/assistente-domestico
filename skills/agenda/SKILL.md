---
name: agenda
description: Compromissos e lembretes da casa — anotar, consultar e cancelar. Use quando a pessoa pede para lembrar, agendar, marcar algo ou pergunta o que tem na agenda.
contextos: [agenda]
estado: ativa
privacidade: local
entradas: [texto, voz]
saidas: [texto]
versao: 1
execucao: roteiro
gatilhos:
  - acao: corrigir
    prioridade: 65
    padrao:
      - '\b(?:cancel|apag|desfaz|remov|exclu)\w*\b.{0,30}\bcompromisso\b'
  - acao: consultar
    prioridade: 70
    padrao:
      - '\bminha agenda\b'
      - '\bmeus compromissos\b'
      - '\bna (?:minha )?agenda\b'
      - '\bo que (?:eu )?tenho\b.{0,25}\b(?:hoje|amanha|semana|agenda)\b'
  - acao: criar
    prioridade: 80
    padrao:
      - '\bme lembr[ae]\b'
      - '\blembrete\b'
      - '\bagend(?:e|ar)\b'
      - '\bmarc(?:a|ar|e)\s+(?:um\s+|uma\s+)?(?:consulta|reuniao|compromisso|horario)\b'
---

# Agenda

Anota, consulta e cancela compromissos e lembretes, guardados no SQLite do assistente (tabela `compromissos`, criada pela própria skill).

## Como funciona (roteiro.py)

- **Anotar:** o modelo local extrai título, data e hora (`prompts/extracao.md`, com a data de hoje). O código valida e grava. Sem data, pergunta "para quando?" e a resposta completa o pedido.
- **Consultar:** sem modelo. Entende hoje, amanhã, semana, mês, dia da semana e datas como 26/11; o padrão são os próximos 7 dias.
- **Cancelar o último compromisso:** pede "sim" antes de apagar.

## Regras

- Nada sai da máquina.
- Feita só com esta pasta (SK7), sem alterar o núcleo.

## Ainda não faz

- Avisar na hora do compromisso (alarme): depende de um agendador no núcleo (V7).
- Sincronizar com o Google Agenda (V7).
- Editar um compromisso: cancele e anote de novo.
