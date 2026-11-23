---
name: programacao
description: Ajuda com código do próprio projeto do assistente — analisar, corrigir, explicar e evoluir o sistema. Use no modo Qwen ou quando a pessoa pede ajuda de programação.
contextos: [programacao]
estado: ativa
privacidade: claude
entradas: [texto, voz]
saidas: [texto]
versao: 1
execucao: roteiro
---

# Programação

Assistente de programação para o projeto do assistente doméstico. Usa o prompt `prompts/sistema.md` e os trechos mais próximos da documentação do projeto (biblioteca).

## Como funciona (roteiro.py)

1. Busca na biblioteca os trechos relevantes (`scripts/indexar_biblioteca.py` monta o índice).
2. Responde com o **Claude** (API), quando há chave e cota.
3. Sem Claude, responde com o **Qwen local** e informa o motivo. Cota esgotada: o Claude volta a ser testado na primeira solicitação depois das 8h.

## Regras

- É a única skill autorizada a enviar dados ao Claude (`CLAUDE_SKILLS`); compras, estoque e agenda nunca saem da máquina.
- A biblioteca só contém documentação pública do repositório e a gerada a partir do código; a pasta de planejamento fica de fora.
- O comando de modo ("ativar qwen") é tratado antes dos gatilhos.
