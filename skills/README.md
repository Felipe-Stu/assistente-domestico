# Skills

Cada capacidade do assistente é uma pasta aqui, no estilo das skills do Claude. O núcleo lê as pastas com `core/skills` e:

- o roteador por regras usa os **gatilhos** do cabeçalho, em ordem de **prioridade**;
- os assistentes leem os **prompts** em `prompts/*.md`;
- a política de nuvem continua no núcleo (`AssistenteRuntime.CONTEXTOS_NUVEM`); o campo `privacidade` declara a intenção e um teste garante que os dois concordam.

Estado: **SK5** do roadmap das skills. Quando nenhum gatilho casa, o orquestrador escolhe a skill pelo `name` e pela `description` de cada pasta. Por isso a `description` precisa dizer com clareza quando usar a skill. Os contextos declarados em `contextos` são aceitos pelo orquestrador sem mudar o núcleo.

## Estrutura

```text
skills/<nome>/
  SKILL.md          cabeçalho YAML + instruções (o que a skill faz, regras, limitações)
  prompts/<x>.md    textos enviados ao modelo; {{marcador}} é preenchido pelo código
  roteiro.py        passos em ordem fixa, quando execucao: roteiro (SK3)
```

`roteiro.py` define `executar(ctx, texto, decisao)` e, se a skill pede confirmação, `responder_pendencia(ctx, texto, dados)`. Os dois devolvem `Resposta(texto, fala=None, pendencia=None)`; com `pendencia`, a próxima mensagem do usuário volta para a skill. `ctx.servico(nome)` entrega os serviços do núcleo e `ctx.repetir(func, args, ...)` aplica a política de repetição.

## Cabeçalho

```yaml
---
name: compras                       # igual ao nome da pasta, minúsculas e hífens
description: Registra compras ...   # uma frase: o que faz e QUANDO usar (o seletor do SK2 lê só isto)
contextos: [compras]                # rota atual do orquestrador; único por skill
estado: ativa                       # ativa | planejada
privacidade: local                  # local | nuvem-permitida (Gemini) | claude (só em CLAUDE_SKILLS)
entradas: [texto, voz]              # texto, voz, pdf, imagem, audio
saidas: [texto]                     # texto, relatorio, acao
versao: 1
execucao: roteiro                   # roteiro (roteiro.py) | nucleo (ainda no app/main.py; padrão)
gatilhos:                           # opcional: frases resolvidas sem modelo
  - acao: criar                     # criar | corrigir | consultar | delegar | chavear_modo
    prioridade: 30                  # menor primeiro; única em todo o catálogo
    sem_interrogacao: true          # opcional: não casa frase com "?"
    parametros: {operacao: desfazer}  # opcional: vai na decisão
    padrao:                         # alternativas unidas por "|"; o texto chega sem acentos e em minúsculas
      - '\b(?:comprei|compramos|paguei)\b'
---
```

`entradas` e `saidas` já preveem o que o roadmap traz: conversa por voz local, leitura de PDF e de imagens, geração de relatórios e ações em integrações (agenda, Spotify, casa).

## Criar uma skill

1. Crie `skills/<nome>/SKILL.md` com o cabeçalho acima e as instruções.
2. Se a skill usa modelo, ponha o prompt em `prompts/`.
3. Rode `python -m unittest tests.test_skills`. Erros de formato apontam o arquivo e o campo.
4. Se mudou um gatilho, `tests/dados/roteador_referencia.json` aponta qualquer decisão que mudou.

Uma skill nova com `execucao: roteiro` é escolhida pelo orquestrador e executada sem nenhuma alteração no núcleo.

## Skills atuais

| Skill | Contextos | Estado | Privacidade | Gatilhos | Execução |
|---|---|---|---|---|---|
| `compras` | compras | ativa | local | 4 (com pesquisa de preço) | roteiro |
| `estoque` | inventario | ativa | local | 2 | roteiro |
| `agenda` | agenda | planejada | local | 2 | roteiro |
| `documentar-projeto` | projetos | ativa | local | 1 | roteiro |
| `programacao` | programacao | ativa | claude | 0 | roteiro (Claude → Qwen) |
| `conversa-geral` | geral, outro | ativa | nuvem-permitida | 0 | núcleo |
