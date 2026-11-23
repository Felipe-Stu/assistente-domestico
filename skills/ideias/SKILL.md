---
name: ideias
description: Ideias de projetos que a PRÓPRIA PESSOA teve e quer guardar — salvar uma ideia nova, listar as ideias salvas e consultar a análise ou os próximos passos de uma delas. Use quando a pessoa diz que teve uma ideia, pede para anotar uma ideia ou pergunta pelas ideias que salvou. Pedir ideias, sugestões ou opiniões ao assistente NÃO é esta skill.
contextos: [ideias]
estado: ativa
privacidade: claude
entradas: [texto, voz]
saidas: [texto, relatorio]
versao: 1
execucao: roteiro
gatilhos:
  - acao: consultar
    prioridade: 55
    padrao:
      - '\bminhas ideias\b'
      - '\b(?:mostr|ver|abr|le)\w*\b.{0,15}\bideia\s*#?\d+\b'
      - '\b(?:como (?:eu )?sigo|proximos passos|como continuo)\b.{0,40}\bideia\b'
  - acao: criar
    prioridade: 58
    padrao:
      - '\b(?:tive|tenho) uma ideia\b'
      - '^\s*ideia\s*:'
      - '\b(?:anot|salv|guard|regist)\w*\b (?:essa |esta |uma |a |minha )?ideia\b'
---

# Ideias

Guarda ideias de projetos e sistemas e entrega uma análise do Claude: escopo, MVP, riscos e próximos passos.

## Como funciona

- **Salvar:** a ideia vai para o SQLite na hora (tabela `ideias`), mesmo sem internet.
- **Analisar:** o `IdeiasService` manda as pendentes ao Claude em segundo plano (`prompts/analise.md`). Sem Claude disponível, a ideia fica na fila e é tentada de novo.
- **Guardar o resultado:** a análise volta para o banco e para `Ideias/ideia-NNNN-*.md` (fora do Git), que entra na biblioteca local.
- **Consultar:** "minhas ideias", "ver ideia 3", "como sigo a ideia do app de receitas?". A pergunta é respondida pelo **modelo local** com a análise salva, sem internet (`prompts/consulta.md`).
- **Pelo celular:** mensagens ao bot do Telegram viram ideias (`services/telegram_service.py`). Perguntas e pedidos não são salvos; "ideia: ..." ou "/ideia ..." salvam sempre.
- **Encaminhamento (P23):** um pedido que não fala de uma ideia salva (ex.: "me dê ideias de melhorias para a documentação") volta para a conversa geral, com `Resposta(encaminhar="conversa-geral")`.

## Privacidade

- O texto da ideia vai ao Claude (privacidade `claude`, autorizada em `CLAUDE_SKILLS`).
- A consulta usa o modelo local.
- Pelo Telegram, a mensagem passa pelos servidores do Telegram.
