---
name: agenda
description: Compromissos, lembretes e consultas marcadas. Use quando a pessoa pede para lembrar, agendar, marcar algo ou pergunta pela agenda.
contextos: [agenda]
estado: planejada
privacidade: local
entradas: [texto, voz]
saidas: [texto]
versao: 1
gatilhos:
  - acao: consultar
    prioridade: 70
    padrao:
      - '\bminha agenda\b'
      - '\bmeus compromissos\b'
  - acao: criar
    prioridade: 80
    padrao:
      - '\bme lembr[ae]\b'
      - '\blembrete\b'
      - '\bagend(?:e|a|ar)\b'
      - '\bmarc(?:a|ar|e)\s+(?:um\s+|uma\s+)?(?:consulta|reuniao|compromisso|horario)\b'
---

# Agenda

Ainda não implementada: o assistente responde que não consegue salvar nem consultar compromissos.

## Planejado

Integração com a agenda (Google Agenda) e alarmes, na V7. Será a primeira skill criada sem mexer no núcleo (SK7).
