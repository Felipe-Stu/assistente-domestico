---
name: compras
description: Registra compras de mercado, farmácia, loja ou restaurante contadas em texto ou voz, desfaz o último registro e, no futuro, responde sobre gastos e preços. Use quando a pessoa conta o que comprou, quanto pagou, onde, ou pergunta sobre o que gastou.
contextos: [compras]
estado: ativa
privacidade: local
entradas: [texto, voz]
saidas: [texto]
versao: 1
gatilhos:
  - acao: corrigir
    prioridade: 10
    parametros: {operacao: desfazer}
    padrao:
      - '\b(?:desfazer|desfaca|cancelar|cancele|apagar|apague|remover|remova|excluir|exclua)\s+(?:a\s+|minha\s+)?(?:ultima\s+compra|compra\s+anterior)\b'
  - acao: consultar
    prioridade: 20
    padrao:
      - '\bquanto\s+(?:eu\s+)?(?:gastei|paguei|gastamos|pagamos)\b'
      - '\bo que\s+(?:eu\s+)?(?:tenho\s+|ando\s+|andei\s+)?(?:comprei|comprado|comprando)\b'
      - '\b(?:onde|quando)\s+(?:eu\s+)?comprei\b'
      - '\bmeus gastos\b'
      - '\bgastos\s+(?:de|do|da|com|no|na)\b'
      - '\bultimas?\s+compras?\b'
      - '\b(?:o que|quais\b.{0,30})\s*(?:eu\s+)?(?:preciso|tenho que|devo)\s+comprar\b'
      - '\blista de compras\b'
  - acao: criar
    prioridade: 30
    sem_interrogacao: true
    padrao:
      - '\b(?:comprei|compramos|paguei)\b'
      - '\b(?:registre|registrar|registra|anote|anotar|anota)\s+(?:uma\s+|a\s+)?compra\b'
  - acao: consultar
    prioridade: 40
    padrao:
      - '\bmais barat[oa]s?\b'
      - '\bqual\s+(?:e\s+|foi\s+)?o preco\b'
      - '\bprecos?\b.{0,40}\bmercados?\b'
      - '\bmercados?\b.{0,40}\bprecos?\b'
      - '\b(?:pesquis\w*|compar\w*)\b.{0,40}\bprecos?\b'
---

# Compras

Registra o que a pessoa comprou: estabelecimento, data e itens (produto, quantidade, unidade, preço unitário e total).

## Como funciona hoje (roteiro fixo, em código)

1. O modelo extrai os dados com o prompt `prompts/extracao.md` e o esquema de `services/esquemas.py`.
2. O código valida contas e datas, aponta dúvidas (mercado não informado, data vaga, preço por kg ambíguo).
3. Sem dúvidas, grava; com dúvidas, mostra o resumo e pede "sim" ou "não".
4. "Desfazer última compra" apaga o último registro.

## Regras

- Nada desta skill vai à nuvem.
- O modelo nunca grava: só o código grava, depois da validação.
- Consultas de gastos e preços ainda não existem; a resposta informa isso e nada é gravado.
