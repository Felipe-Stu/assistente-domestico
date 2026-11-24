# CHANGELOG

## [V4.3] — Notas fiscais por arquivo: NFC-e (HTML), PDF, foto, pasta de entrada e Telegram (2026-11-23)

### Adicionado
- `services/nfce_service.py`: leitor da página da NFC-e da Sefaz (HTML), sem IA.
  - Lê estabelecimento, CNPJ, data de emissão, itens (código, quantidade, unidade, unitário, total), desconto, valor pago, forma de pagamento e chave de acesso.
  - **Não lê os dados do consumidor** (CPF, nome).
  - O desconto é distribuído entre os itens, proporcionalmente e em centavos, de modo que a soma dos itens fica igual ao valor pago.
  - O tamanho da embalagem é lido do nome ("500ML" vira 0,5 litro no estoque).
- `services/documentos_service.py`: importa HTML da NFC-e, PDF (texto via `pypdf`) e foto (modelo local que entende imagem, `OLLAMA_MODELO_VISAO`).
  - O modelo local só torna legíveis os nomes abreviados do cupom e escolhe a categoria.
  - O original é copiado para `Anexos/AAAA-MM/`; a chave de acesso impede registrar a mesma nota duas vezes (migração v7: `entradas.chave_documento`).
  - Foto e PDF vêm marcados para revisão.
- `services/pasta_entradas_service.py`: a pasta `E:\Agente IA\Entradas` é vigiada.
  - A nota salva ali vira um resumo com "sim/não"; depois o arquivo vai para `processados/` ou `com_erro/`.
- **Telegram:** arquivos e fotos mandados ao bot vão para a pasta de entrada; o resumo volta ao chat do celular e a confirmação é feita no PC.
- `LocalLLMProvider.gerar_json_imagem`.
- **App (Electron):** botão 📎 no chat e arrastar-e-soltar para enviar HTML da nota, PDF ou foto (JPG, PNG, WEBP).
  - O arquivo continua onde estava (só os da pasta de entrada são movidos); o original vai para `Anexos/`.
  - Com uma confirmação já pendente, o app avisa e mostra o resumo depois do "sim" ou "não".
- **Texto da nota colado no chat:** usa o mesmo leitor exato do HTML (desconto distribuído, confirmação antes de gravar).
- `tests/test_documentos.py` (14 testes, com a sua nota real e o CPF trocado por um fictício). Suíte: 288 testes.

### Pendente no PC
- Testar PDF e foto pelo app e pelo Telegram (pypdf já instalado; texto colado testado e aprovado).
- Confirmar se o `gemma4:e4b` lê fotos no seu Ollama; se não, definir outro modelo de visão em `OLLAMA_MODELO_VISAO`.

## [V4.3, parte 1] — Catálogo, centavos e estoque: M07, M08, M06 (2026-11-23)

### Adicionado
- **M07 — catálogo de produtos e categorias fechadas** (migração v4):
  - 15 categorias fechadas, no esquema de saída e no prompt da extração.
  - Tabela `produtos`: "Leite 1L", "leite" e "leites" são o mesmo produto.
  - Produto novo é cadastrado sozinho, e cada item aponta para ele (`itens_compra.produto_id`).
  - Itens antigos entram no catálogo na migração, com a categoria deduzida do nome do produto. O texto original fica preservado.
- **M08 — dinheiro em centavos inteiros** (migração v5):
  - Colunas `*_centavos` em `compras` e `itens_compra`, preenchidas na entrada e na migração (meio centavo para cima).
  - Total da compra somado em centavos; exibição em `R$ 1.234,56`.
  - As colunas REAL antigas continuam preenchidas.
- **M06 — compras alimentam o estoque** (migração v6):
  - Cada item gravado soma ao estoque do produto na mesma transação, em unidade base (kg, litro, un); embalagens são convertidas ("2 pacotes de 5 kg" → 10 kg).
  - O ritmo de consumo é aprendido na recompra; desfazer a compra tira do estoque.
  - "Ainda tenho leite?" responde com quantidade e unidade, sem depender de acentos.

### Corrigido
- **P1:** compras não alimentavam o estoque.

### Testes
- `tests/test_m07.py`, `test_m08.py`, `test_m06.py`. Suíte: 271 testes.
- Migrações v3 a v6 conferidas numa cópia do banco real: 4 compras e 11 itens preservados, totais em centavos iguais à soma dos itens.

### Limitações
- O estoque começa vazio: compras antigas não entram, porque sem ritmo conhecido apareceriam como estoque cheio.
- Sem perguntas de confirmação de sobras (P8); o código antigo de estoque por voz continua sem uso.

## [V4.2] — Medir antes de mudar: M09, M13, M15, M16 (2026-11-23)

### Adicionado
- **M09 — origem de cada registro:** tabela `entradas` (migração v3) com, para cada pedido de compra:
  - texto original e canal (`chat` ou `voz`);
  - o que o modelo devolveu, o modelo, a versão do prompt (hash de 8 caracteres) e a duração.
  - É gravada na mesma transação da compra (`compras.entrada_id`); descartadas e desfeitas também ficam registradas.
- **M13 — conjunto de avaliação:**
  - `scripts/avaliar.py` guarda o histórico de cada medição em `Planejamento/medicoes/historico-avaliacao.jsonl` e mostra as últimas no relatório.
  - Mede o acerto da extração por campo (itens, total, mercado, embalagem) e registra a versão dos prompts do orquestrador e da extração.
  - As medições de 23/11 (SK0 e SK2) entraram no histórico.

### Alterado
- **M16 — nuvem por escolha:** a conversa geral responde localmente por padrão. O Gemini entra quando a pessoa pede ("pergunta pro Gemini", "pesquisa na internet", "procura no Google") ou quando o modelo local falha. O campo `dificuldade` saiu do prompt e do esquema do orquestrador.
- **M15 — prompt enxuto:** registrado como feito pelo SK2 (prompt fixo pelo catálogo: 1.624 → 325 tokens lidos); com o M16, o prompt ficou ainda menor.

### Testes
- `tests/test_m09.py` (8), M16 em `test_sk2.py` e `test_fase1.py`, M13 em `test_sk0.py`. Suíte: 250 testes.

### Medido no PC (23/11, 19:48)
- Escolha da skill com o prompt sem `dificuldade`: 50/53 (antes 44/48), p50 0,75 s e p95 0,83 s (antes 0,87 e 1,01 s), 16 tokens gerados (antes 27).
- Os 3 erros restantes:
  - r53 ("me dê ideias de melhorias...") vai para `ideias`, mas no app o encaminhamento do P23 manda à conversa geral;
  - r43 e r47 são capacidades futuras.

### Decisões
- M14 (classificador por similaridade) descartado: o catálogo já atinge a meta de p95 abaixo de 1 s.

## [V4.1] — M27: configuração e portabilidade; M02: integração contínua na v4.1 (2026-11-23)

### Adicionado
- Configuração no `.env` (`core/config.py`):
  - `OLLAMA_MODELO_PADRAO` e `OLLAMA_MODELO_AVANCADO`.
  - `OLLAMA_TIMEOUT` e `OLLAMA_KEEP_ALIVE`.
  - `RETRY_TENTATIVAS` e `RETRY_ESPERA_S`.
  - O endereço do servidor continua em `OLLAMA_HOST`.
- Electron escolhe o Python assim: `ASSISTENTE_PYTHON`, senão `.venv` do projeto, senão `python` (Windows) ou `python3`.
- `scripts/fixar_versoes.py` e `fixar-versoes.bat`: geram `requirements-lock.txt` com as versões exatas instaladas das dependências.
- `LICENSE` (MIT) e `"license": "MIT"` no `package.json`.
- `tests/test_m27.py` (7 testes). Suíte: 238 testes.

### Alterado
- `llm_provider.py` e `app/main.py` leem modelos, tempos e repetição da configuração (antes fixos no código).
- Bipes do modo voz: `winsound` só no Windows; nos outros sistemas, silêncio, sem erro.
- Integração contínua também roda em push na `v4.1`.
- `requests` entra no `requirements-ci.txt` (usado pelo Claude e pelo Telegram).

### Corrigido
- P16: Python ausente derrubava o Electron sem aviso; agora o erro aparece na interface com a orientação.

## [V4.1] — P23: pedido de sugestões não é ideia salva (2026-11-23)

### Corrigido
- P23, no chat: "Me dê ideias de melhorias para a documentação" ia para a skill `ideias` e respondia "Não encontrei essa ideia".
  - A skill só consulta quando o pedido se refere a uma ideia salva ("minhas ideias", "ideia 3", "a ideia do...", "que salvei"); o resto vai para a conversa geral.
  - Pedido ou pergunta também não é salvo como ideia.
- P23, no Telegram: perguntas e pedidos ("analise a documentação...", "me diga como está o projeto") viravam ideias. Agora o bot explica que não salvou.

### Adicionado
- `Resposta.encaminhar` no motor das skills: um roteiro pode devolver o pedido a uma skill de execução `nucleo` (hoje, a conversa geral).
- No Telegram, "ideia: ..." e "/ideia ..." salvam sempre, mesmo que o texto pareça pergunta.
- `tests/test_ideias.py`: 4 testes do P23. Suíte: 231 testes.

### Alterado
- A descrição da skill `ideias` deixa claro que pedir ideias ou sugestões ao assistente não é com ela.

## [V4.1] — Ideias de projetos, Claude pela assinatura e bot do Telegram (2026-11-23)

### Adicionado
- Skill `ideias`:
  - "tive uma ideia: ..." salva no SQLite na hora (tabela `ideias`).
  - "minhas ideias" e "ver ideia 3" listam e mostram.
  - "como sigo a ideia X?" é respondida pelo modelo local com a análise salva, sem internet.
- `services/ideias_service.py`:
  - Fila de análise em segundo plano: o Claude devolve título, resumo, MVP, como construir, riscos, próximos passos e perguntas (`skills/ideias/prompts/analise.md`).
  - Sem Claude disponível, a ideia fica pendente e é tentada de novo a cada `IDEIAS_RETESTE_MIN`.
  - A análise vai para o banco e para `Ideias/ideia-NNNN-*.md` (fora do Git), que entra na biblioteca local.
- `services/claude_assinatura_service.py` (`CLAUDE_MODO=assinatura`, padrão): usa o Claude Code logado no plano (`claude -p`), sem chave de API.
  - Sem ferramentas: `--tools ""` e sem MCP.
  - Roda numa pasta temporária, sem gravar sessão, e com `ANTHROPIC_API_KEY` retirada do ambiente.
  - Limite do plano: reteste em `CLAUDE_ASSINATURA_RETESTE_MIN`. Sem login: reteste na manhã seguinte.
  - O modo `api` continua disponível.
- `services/telegram_service.py`: bot opcional para mandar ideias do celular.
  - Long polling, sem expor o PC; só os chats de `TELEGRAM_CHAT_IDS` são atendidos.
  - Comandos `/ideias`, `/ver N`, `/reanalisar N`.
  - A análise volta para o chat de origem. O token nunca vai para os logs.
- `testar-claude-assinatura.bat` (instalação, login e resposta) e `configurar-telegram.bat` (descobre o número do chat).
- `tests/test_ideias.py` (20 testes) e 4 casos de avaliação. Suíte: 226 testes.

### Alterado
- `CLAUDE_SKILLS` padrão: `programacao,ideias`.
- A biblioteca aceita pastas extras, lidas a cada indexação.

### Validação no PC (23/11)
- Claude Code instalado e logado no plano (`instalar-claude-code.bat`): resposta em 5,5 s.
- Três ideias mandadas pelo Telegram foram analisadas em cerca de 20 s cada, e as análises voltaram ao chat.

### Privacidade
- O texto da ideia vai ao Claude; a consulta sobre a ideia fica local.
- Pelo Telegram, a mensagem passa pelos servidores do Telegram.

## [V4.1] — SK7: agenda (2026-11-23)

### Adicionado
- Agenda funcional, feita só com `skills/agenda/` (sem alteração em `core/` ou `app/`), no SQLite local (tabela `compromissos`, criada pela skill).
  - Anotar: o modelo local extrai título, data e hora (`prompts/extracao.md`, com a data de hoje); o código valida; sem data, pergunta "para quando?" e a resposta completa o pedido.
  - Consultar: sem modelo; hoje, amanhã, dia da semana, data (26/11), mês; padrão: próximos 7 dias.
  - Cancelar o último compromisso, com confirmação.
- Gatilhos novos: "o que tenho hoje/amanhã/na semana", "na agenda" e "cancelar compromisso".
- `skills/agenda/exemplos.jsonl` e `tests/test_sk7.py` (8 testes). Suíte: 206 testes.

### Corrigido
- P9: a agenda grava e consulta compromissos.

### Limitações
- Sem aviso na hora do compromisso (precisa de agendador no núcleo) e sem Google Agenda: ficam para a V7.

## [V4.1] — SK6: fábrica de skills (2026-11-23)

### Adicionado
- `skills/_modelo/` e `scripts/nova_skill.py`: cria `skills/<nome>/` com `SKILL.md`, `roteiro.py` e `exemplos.jsonl` já válidos; recusa nome inválido, skill existente, descrição curta e contexto já usado, sem deixar pasta pela metade.
- `scripts/validar_skills.py`: cabeçalhos, roteiros importáveis, marcadores dos prompts e `exemplos.jsonl`. Novo passo **Validar skills** na integração contínua.
- `scripts/avaliar.py --skill <nome>`: mede no PC se o orquestrador escolhe a skill para os exemplos dela.
- Serviço `llm_local` (modelo residente) entregue a toda skill, para que uma skill nova use o modelo sem mudar o núcleo.
- `tests/test_sk6.py` (7 testes). Suíte: 198 testes.

### Alterado
- O catálogo ignora pastas que começam com `_` ou `.` (o modelo `skills/_modelo` não é uma skill).

## [V4.1] — SK5: remoção do código antigo e divisão do main.py (2026-11-23)

### Removido
- Orquestrador por contextos fixos (prompt de ~250 linhas) e a opção `ORQUESTRADOR_MODO`: o orquestrador pelo catálogo foi confirmado no PC (44/48 em 0,87 s contra 43/48 em 1,39 s). O código antigo está no histórico do Git até o commit `d128516`.
- `ESQUEMA_ORQUESTRADOR` e as listas de valores do orquestrador antigo em `services/esquemas.py`.
- No assistente local, os ramos de compras e agenda que ficaram inalcançáveis (essas skills têm roteiro). Também `PROMPT_PROGRAMACAO` e `_sanitizar_resposta_json` do `gemma_service.py`, sem uso.
- `services/gemma_service.py`: 373 → 159 linhas.

### Alterado
- A skill `documentar-projeto` passou a ter roteiro (`skills/documentar-projeto/roteiro.py`). O `app/main.py` não tem mais nenhum `if contexto ==`: todas as skills, exceto `conversa-geral`, executam o próprio roteiro.
- Os contextos válidos na decisão do orquestrador vêm do catálogo (`gemma_service.valores_permitidos()`). Antes eram uma lista fixa, e uma skill nova com contexto próprio seria recusada quando escolhida pelo modelo.
- `app/main.py` dividido (974 → 788 linhas): `app/ipc.py` (UTF-8, pipe do Electron isolado e `emitir_electron`), `app/sessao.py` (`GerenciadorDeSessao`) e `app/voz.py` (modo voz e laço do microfone, classe base do runtime). O pipeline continua no `main.py`.

### Decisões (23/11/2026)
- O código de estoque nunca ligado ao app (validação por voz, baixa direta; P8 e P20) fica até a V4.3, que refaz o estoque dentro da skill.
- Divisão segura do `main.py`: o pipeline e o orquestrador continuam onde estão, para não reescrever os testes.

### Testes
- 191 de 191 aprovados. Saíram 5 testes do orquestrador antigo e entrou 1: o contexto de uma skill nova é aceito quando o modelo a escolhe.
- Teste de fumaça do processo real, numa cópia do projeto: `app/main.py` por pipe (como o Electron), com respostas de estoque, desfazer compra e agenda pelos roteiros, sem erros.

## [V4.1] — SKP: programação com Claude (API) e Qwen local como reserva (2026-11-23)

### Adicionado
- `services/claude_service.py`: chamada à API do Claude com `requests` (sem pacote novo). Sem chave, fica desligado.
  - Cota esgotada, teto de gasto, cobrança ou chave recusada (429 sem `retry-after`, 402, 401/403, 400 de limite de gasto) deixam o Claude indisponível até a **primeira solicitação depois das 8h** (`CLAUDE_HORA_RETESTE`). Com `retry-after`, até o horário indicado.
  - Sobrecarga, timeout, erro interno e falha de rede afetam só a solicitação em curso.
  - Gasto do mês estimado pelos tokens de cada resposta; ao passar de `CLAUDE_LIMITE_MENSAL_USD` (padrão US$ 5), o Claude volta no mês seguinte.
  - Estado em `core/database/estado_claude.json`, ignorado pelo Git; nenhuma chave é registrada.
- `services/biblioteca_service.py` e `scripts/indexar_biblioteca.py`: biblioteca de contexto no ChromaDB (coleção `biblioteca_projeto`), com reindexação só do que mudou. Fontes: README, CHANGELOG, `Sobre a Versão`, skills e a documentação gerada pelo ProjectAnalyzer. A pasta de planejamento fica de fora.
- `skills/programacao/roteiro.py`: busca de 6 trechos na biblioteca → Claude → Qwen local (`qwen2.5-coder:7b`), informando o motivo quando o Qwen responde no lugar do Claude.
- `scripts/testar_skp.py` e `testar-skp.bat`: chamada mínima ao Claude, indexação e a mesma pergunta pelos dois provedores, com relatório.
- Opções no `.env`: `ANTHROPIC_API_KEY`, `CLAUDE_MODELO` (padrão `claude-sonnet-5-5`), `CLAUDE_LIMITE_MENSAL_USD`, `CLAUDE_PRECO_ENTRADA`, `CLAUDE_PRECO_SAIDA`, `CLAUDE_HORA_RETESTE`, `CLAUDE_SKILLS`.
- Privacidade `claude` no cabeçalho das skills. A política fica no núcleo: o serviço do Claude só é entregue às skills de `CLAUDE_SKILLS` (padrão: `programacao`) que declaram `privacidade: claude`, e um teste garante que as duas listas concordam.
- `tests/test_skp.py` (18 testes). Suíte: 195 testes.

### Alterado
- A skill `programacao` passou a ser executada pelo próprio roteiro, com privacidade `claude`. Antes usava o modelo ativo (Gemma ou Qwen) com o prompt de programação.
- `scripts/conferir_chaves.py` informa se a chave do Claude está no `.env`, sem exibi-la.

### Decisões (23/11/2026)
- Só a skill de programação pode enviar dados ao Claude; compras, estoque e agenda nunca saem da máquina.
- Acesso por API com chave própria. Endpoint, cabeçalhos e erros conforme a documentação oficial (https://platform.claude.com/docs/en/api/errors).
- Reteste na primeira solicitação depois das 8h, e não em horário fixo: funciona mesmo com o PC desligado de manhã.

### Não verificado
- Chamada real ao Claude e a biblioteca no ChromaDB: dependem do PC (`testar-skp.bat`).

## [V4.1] — SK3: compras, estoque e agenda executam o roteiro da própria skill (2026-11-23)

### Adicionado
- `core/skills/motor.py`: carrega `skills/<nome>/roteiro.py` e executa `executar(ctx, texto, decisao)`; `responder_pendencia(ctx, texto, dados)` trata a resposta a um pedido de confirmação. O roteiro recebe só os serviços e a política de repetição do núcleo (`Contexto`), sem acesso ao runtime, ao Electron ou à política de nuvem.
- Campo `execucao` no cabeçalho das skills: `roteiro` (passos em `roteiro.py`, em ordem fixa) ou `nucleo` (ainda executada por `app/main.py`).
- `skills/compras/roteiro.py`, `skills/estoque/roteiro.py` e `skills/agenda/roteiro.py`, com a lógica e os textos que estavam no `main.py`.
- `tests/test_sk3.py` (7 testes), entre eles: uma compra registrada usa **uma** chamada ao modelo; uma skill nova com confirmação funciona sem mudar o núcleo. Suíte: 177 testes.

### Alterado
- `app/main.py`: os ramos de compras, estoque e agenda foram substituídos por uma chamada ao roteiro da skill do contexto; `_processar_compras` e `_responder_confirmacao_compra` saíram do arquivo.
- A compra aguardando confirmação virou uma pendência genérica (`self.pendencia = (skill, dados)`): a próxima mensagem vai para a skill que perguntou, sem passar pelo orquestrador. `compra_pendente` continua disponível para leitura.

### Testes
- 177 de 177 aprovados (Python 3.10, dependências externas simuladas). O texto enviado ao modelo e a extração não mudaram; a medição do SK0 continua valendo.

## [V4.1] — SK2: o orquestrador escolhe a skill pelo catálogo (2026-11-23)

### Medição que motivou (SK0, 23/11/2026, PC do usuário)

| Configuração | Acerto (48 frases) | Tempo da escolha (mediana) | Tokens lidos / gerados |
|---|---|---|---|
| Gemma 4, prompt por contextos (antes) | 43/48 | 1,39 s | 1.624 / 36 |
| **Gemma 4, catálogo (adotado)** | **45/48** | **0,55 s** | 325 / 8 |
| Qwen 2.5 Coder, catálogo | 45/48 | 0,55 s | 375 / 11 |
| Qwen 2.5 Coder, chamada nativa de ferramentas | 31/48 (não chamou nenhuma em 34 de 34) | — | — |

Extração de compras: 6/8 nos dois modelos (as mesmas duas falhas), sem diferença entre raciocínio ligado e desligado. Troca de modelo na VRAM: 13 a 15 s; os dois modelos não cabem juntos.

### Alterado
- `gemma_service.orquestrar_requisicao`: depois dos comandos e dos gatilhos, o modelo escolhe a **skill** pelo catálogo (`core/skills/seletor.py`), com prompt fixo (nome e descrição de cada skill, sem a frase do usuário dentro) e esquema `{skill, acao, dificuldade}`. A resposta é convertida para o formato de decisão que o resto do app já usa.
- Opção `ORQUESTRADOR_MODO` no `.env`: `catalogo` (padrão) ou `contextos` (prompt anterior, mantido como reserva).
- Skill `compras`: gatilho para pesquisa e comparação de preços entre mercados. Na medição, "Pesquise na internet o preço do frango e compare três mercados" ia para a conversa geral, a única skill que pode ir à nuvem.
- O evento `decisao` do registro de eventos traz a skill escolhida.
- `scripts/avaliar.py`: o modo "atual" mede o orquestrador do app no modo configurado e o relatório informa qual.

### Corrigido
- **P10:** `programacao` e `projetos` não estavam entre as opções do orquestrador e só eram alcançadas por regra. Agora todas as skills do catálogo podem ser escolhidas pelo modelo.

### Decisões (23/11/2026)
- **Gemma 4 E4B é o modelo residente**: escolha da skill, compras, estoque, agenda e conversa. Mesmo acerto do Qwen, mais leve, e a troca de modelo custa 13 a 15 s.
- Programação vira modo sob demanda: Claude (API, só a skill de programação) como principal e Qwen com biblioteca de contexto como reserva (etapa SKP, ainda não feita; depende da troca das chaves, M01).
- A opção "não sei" (perguntar ao usuário quando a escolha for incerta) ficou de fora: muda o comportamento medido e precisa de medição própria.

### Testes
- `tests/test_sk2.py` (10 testes). Suíte: 170 de 170 aprovados (Python 3.10, dependências externas simuladas).
- `tests/dados/roteador_referencia.json`: 3 decisões atualizadas de propósito (a frase de pesquisa de preço), com o motivo registrado em cada uma.
- **Confirmado no PC** (23/11/2026, `scripts/avaliar.py --modos atual`, Gemma 4): 44/48 acertos (32/33 nas capacidades atuais) em 0,87 s de mediana, contra 43/48 (28/33) em 1,39 s do prompt anterior, contando também a ação. Os 4 erros ficaram em skills locais (nenhum foi para a conversa geral).

## [V4.1] — Skills: formato, catálogo e ferramenta de medição (SK0 e SK1) (2026-11-23)

Primeiras etapas do roadmap das skills (planejamento, fora do repositório): base para que cada capacidade nova seja uma pasta, sem mexer no núcleo.

### Adicionado
- **SK1 — skills:** pasta `skills/` com seis skills (`compras`, `estoque`, `agenda`, `documentar-projeto`, `programacao`, `conversa-geral`). Cada uma tem `SKILL.md` (cabeçalho YAML com nome, descrição, contextos, estado, privacidade, entradas, saídas e gatilhos, mais as instruções) e, quando usa modelo, `prompts/*.md`. Formato em `skills/README.md`.
- `core/skills/`: carregador e catálogo. Valida cada cabeçalho (campos, nome igual à pasta, regex, prioridades e contextos únicos) e aponta o arquivo e o campo com erro. Os campos `entradas` e `saidas` já aceitam `pdf`, `imagem`, `audio`, `relatorio` e `acao`.
- **SK0 — medição:** `evals/casos.jsonl` (48 frases com a skill esperada, 15 delas de capacidades futuras: PDF, relatórios, Spotify, câmeras, casa) e `evals/compras.jsonl` (8 compras).
- `scripts/avaliar.py`: no PC com o Ollama, mede a escolha da skill em três modos (orquestrador atual, enum do catálogo e chamada nativa de ferramentas) para cada modelo, a extração de compras com o raciocínio desligado e ligado, e o tempo de troca de modelo na VRAM. Relatório em JSON e Markdown.
- `core/skills/seletor.py`: protótipo dos modos "catálogo" e "nativo", usado só pelo `avaliar.py`; não está ligado ao app.
- `tests/test_skills.py` (13 testes) e `tests/test_sk0.py` (10). A suíte passa a ter 160 testes.
- `tests/dados/roteador_referencia.json`: 168 decisões do roteador por regras gravadas antes da mudança; o teste aponta qualquer decisão que mudar.
- `PyYAML>=6.0` em `requirements.txt` e `requirements-ci.txt` (já vinha instalado junto com o ChromaDB; agora é declarado).

### Alterado
- `services/intent_router.py`: as expressões regulares saíram do código e foram para os gatilhos das skills; o módulo aplica o primeiro gatilho que casar, em ordem de prioridade (101 → 46 linhas).
- `services/gemma_service.py`: `PROMPT_PROGRAMACAO` é lido de `skills/programacao/prompts/sistema.md`; o assistente local usa o prompt da skill do contexto (503 → 352 linhas).
- `services/shopping_assistant.py`: o prompt de extração é lido de `skills/compras/prompts/extracao.md` (531 → 422 linhas).
- Os prompts perderam a indentação de 8 espaços que vinha das strings Python; o texto é o mesmo.

### Decisões
- Nomes `compras` e `estoque` em vez de `registrar-compras` e `gerenciar-estoque` (do plano): as duas skills também respondem a consultas.
- A política de nuvem continua no núcleo (`CONTEXTOS_NUVEM`); o campo `privacidade` declara a intenção e um teste garante que os dois concordam.
- Comandos de modo (Qwen) e de análise de projeto com caminho continuam em `gemma_service.py`, antes dos gatilhos; saem no SK2.

### Testes
- 160 de 160 aprovados (Python 3.10, com `ollama`, `python-dotenv` e `google-genai` simulados). Equivalência conferida antes de apagar o código antigo: 0 diferenças nas 168 decisões do roteador e prompts com o mesmo texto.
- `avaliar.py` exercitado de ponta a ponta com um Ollama falso; a medição real (SK0) depende do PC com o Ollama.

## [V4.1] — Cópia de segurança automática e registro de eventos estruturado (2026-11-22)

### Adicionado
- **M11 — cópia de segurança automática:** `services/backup_service.py`. Uma vez por dia, em segundo plano, grava em `core/database/backups/auto/AAAA-MM-DD/` o banco (`VACUUM INTO`, conferido com `PRAGMA integrity_check`), a pasta do ChromaDB compactada (`chroma_db.zip`; o `chroma.sqlite3` é copiado pela API de backup do SQLite) e um `manifesto.json` com tamanhos e SHA-256. A cópia é montada em `AAAA-MM-DD.parcial` e só recebe o nome final quando termina. Retenção: as 7 cópias mais recentes e a mais nova de cada uma das 4 semanas anteriores. Cópias manuais fora de `auto/` não são tocadas. Com o app aberto de um dia para o outro, a verificação se repete a cada hora.
- `scripts/fazer_backup.py`: cópia manual (`--forcar` refaz a de hoje, `--listar` mostra as guardadas).
- **M26 — registro de eventos estruturado:** cada evento vira uma linha JSON em `Logs/eventos-AAAA-MM-DD.jsonl` com `ts`, `nivel`, `componente`, `evento`, `mensagem` e campos extras. Cada solicitação recebe um identificador (`req`) que acompanha todos os eventos dela, com início, fim e duração total. Etapas medidas: `roteamento`, `extracao_compras`, `banco`, `assistente_local`, `nuvem`, `consulta_estoque`, `voz`, `memoria` e `analise_projeto`. Cada tentativa do `execute_with_retry` aparece como uma etapa.
- `scripts/ver_logs.py`: mostra os eventos de um dia em formato legível, filtra por requisição, componente ou nível e resume o tempo por etapa (`--etapas`: mediana, p95 e máximo).
- Opções no `.env`: `LOG_CONTEUDO` (`0` grava só o tamanho do texto do usuário), `LOG_RETENCAO_DIAS` (30), `LOGS_DIR`, `BACKUP_ATIVO`, `BACKUP_DIR`, `BACKUP_DIARIOS` (7) e `BACKUP_SEMANAIS` (4).
- `tests/test_m11.py`: 18 testes; `tests/test_m26.py`: 13 testes; 1 teste de integração em `tests/test_fase1.py`. A suíte passa a ter 137 testes.

### Alterado
- `services/logger_service.py` reescrito sobre o `logging` padrão. `log_geral` e `log_assistente` continuam funcionando; o nível dessas chamadas é deduzido do texto (palavras como "erro" e "falha" viram `ERROR`). Os arquivos `Logs/<módulo>/log.txt` deixam de receber linhas e ficam como histórico.
- A rotação é por arquivo diário, sem renomear arquivos: no Windows, renomear um log aberto por outro processo falha.
- Textos do usuário registrados por `main.py`, `ai_service`, `inventory_assistant`, `shopping_assistant` e `memory_service` passam por `logger.conteudo()`, que respeita `LOG_CONTEUDO`.

### Corrigido
- **P13:** `scripts/rebuild_embeddings.py` apagava a coleção inteira e só recriava compras e estoque, perdendo as memórias `mem_*`. Agora faz uma cópia de segurança, exporta as memórias para `backups/memorias-AAAAMMDD-HHMMSS.json`, reindexa e regrava as memórias com o modelo atual. Se não conseguir ler as memórias, não apaga nada; se não conseguir regravá-las, avisa e mantém a exportação.
- **P22:** `with get_connection()` confirmava a transação, mas não fechava a conexão SQLite. A conexão agora é criada com uma fábrica (`_ConexaoQueFecha`) que fecha ao sair do bloco, inclusive em caso de erro. Os `ResourceWarning` do SQLite sumiram da suíte.

### Decisões
- A cópia roda ao abrir o app, e não em horário fixo, porque o assistente não fica ligado o tempo todo. Uma pasta por dia, com manifesto, permite conferir e restaurar sem ferramenta.
- Um único arquivo de eventos por dia, com o componente em cada linha, em vez de um arquivo por módulo: uma requisição atravessa vários módulos e precisa ser lida em ordem.

### Medições (22/11/2026, ambiente de desenvolvimento)
- Cópia dos dados reais (copiados para uma pasta temporária): 12 ms; banco com 36,9 kB e ChromaDB compactado com 73,7 kB. Contagens iguais à origem em todas as tabelas (4 compras, 11 itens) e 14 de 14 embeddings; `integrity_check` ok no banco e no `chroma.sqlite3` restaurado.

### Não verificado
- Execução no PC do usuário: a primeira cópia automática e o arquivo de eventos aparecem na próxima vez que o app for aberto.
- Cópia do ChromaDB durante uma gravação de memória: o `chroma.sqlite3` é copiado de forma consistente, mas os arquivos do índice HNSW são copiados como estão.
- A suíte foi executada com `ollama`, `python-dotenv` e `google-genai` simulados (sem rede para instalar).

## [V4.1] — Base de engenharia: integração contínua, saída estruturada e início rápido (2026-11-17)

### Adicionado
- `.github/workflows/testes.yml`: a cada push na `V4` e a cada pull request, verifica a sintaxe (Python e JavaScript) e roda a suíte. O linter (ruff) roda em modo informativo, sem reprovar.
- `requirements-ci.txt`: dependências mínimas da suíte (`ollama`, `python-dotenv`, `google-genai`).
- `services/esquemas.py`: JSON Schema das respostas do orquestrador e da extração de compras.
- `tests/test_v41.py`: 25 testes; `tests/test_m17.py`: 7 testes; 3 testes do M17 em `tests/test_fase1.py`. A suíte passa a ter 105 testes.
- Opção `OLLAMA_SAIDA_ESTRUTURADA` (`.env`): `0` volta ao modo JSON simples.
- Opção `OLLAMA_RACIOCINIO` (`.env`): vazio segue o código, `0` desliga e `1` liga o raciocínio (`think`) em todas as chamadas locais. Quando preenchida, prevalece sobre o código.
- `LocalLLMProvider.gerar_json` aceita `raciocinio` e registra tokens e tempos do Ollama em `ULTIMA_CHAMADA`. Modelo sem suporte a `think` recebe a chamada repetida sem o parâmetro.
- **M17 — falhar rápido quando o Ollama está fora:** `garantir_ollama_disponivel()` consulta `/api/tags` com timeout de 2 s antes de chamar o modelo (resultado positivo vale por 30 s). Erro de conexão vira `OllamaIndisponivelException`, tratada como fatal pelo `execute_with_retry`: sem as 3 tentativas e as 2 esperas de 3 s. JSON inválido continua sendo repetido.
- Resposta `MSG_OLLAMA_FORA` com o botão "Tentar de novo" no chat, que reenvia o mesmo texto (`tentar_novamente` no evento `assistant_message`). Pergunta geral com o Ollama fechado segue para a nuvem quando permitido; compras e demais contextos restritos não.
- Aviso no terminal interno, logo após o início, se o Ollama não responder.
- `scripts/medir_m17.py`: abre o app por pipe, envia uma frase e mede o tempo até a resposta, com o Ollama fechado ou aberto.
- `scripts/medir_v41.py`: mede início (M04), orquestrador e extração (M03) contra o Ollama real. Opções `--modelo gemma|qwen`, `--raciocinio padrao|nao|sim`, `--modos` e `--so-orquestrador`; o relatório traz tokens gerados, caracteres de raciocínio e tempos de prompt e geração. Resultados em `Planejamento/medicoes`.

### Alterado
- `LocalLLMProvider.gerar_json` aceita `esquema` e o envia no parâmetro `format` do Ollama. O orquestrador e o `ShoppingAssistant` passam a usá-lo; valores fora das listas permitidas deixam de ser gerados. A validação em Python foi mantida.
- `EmbeddingService`: o construtor não carrega mais o modelo. O runtime inicia a carga em segundo plano e o chat fica disponível antes dela; enquanto carrega, a busca semântica é ignorada (resposta sem RAG).
- A memória de longo prazo passa a ser gravada depois da entrega da resposta.
- `requirements.txt`: `ollama>=0.4.0` (versão a partir da qual `format` aceita esquema).
- O orquestrador chama o Gemma 4 com o raciocínio desligado (`raciocinio=False`). Com ele ligado, padrão do Ollama para o `gemma4:e4b`, cada decisão gerava cerca de 450 tokens, quase todos de raciocínio, para devolver um JSON de quatro campos.

### Corrigido
- `VectorStoreService.upsert_documents` não grava quando os embeddings não puderam ser gerados; antes, o ChromaDB receberia documentos sem vetor próprio.
- A carga da memória semântica em segundo plano travava quando o back-end recebia os comandos por pipe (Electron e `scripts/medir_v41.py`): no Windows, a thread que espera a próxima linha bloqueia outras consultas ao mesmo pipe, e a importação do modelo só seguia na mensagem seguinte. O runtime passa a ler os comandos por um descritor privado (`ENTRADA_IPC`) e troca a entrada padrão por `os.devnull`. Pelo terminal, a memória ficava pronta em 14 s; por pipe, não ficava pronta em 150 s.
- O modelo de embeddings ia para a GPU (`cuda:0`) apesar de o log dizer CPU. Agora usa `EMBEDDING_DEVICE` (`.env`, padrão `cpu`).
- O modelo de embeddings passa a carregar só do cache local (`local_files_only`); antes fazia cerca de 30 consultas ao Hugging Face a cada início. Sem cache, carrega com rede como antes.

### Decisões
- Com biblioteca `ollama` antiga, que recusa o esquema, o provedor repete a chamada com `format="json"` e registra o aviso. Erros de conexão não geram segunda chamada.
- Os esquemas oferecem ao modelo os mesmos valores descritos no prompt; `programacao`, `projetos` e `chavear_modo` continuam restritos às regras (P10 permanece aberto).

### Medições (17/11/2026, PC do usuário, `scripts/medir_v41.py`)
Início do sistema (1 rodada):

| | Antes da V4.1 | V4.1 |
|---|---|---|
| Chat pronto | ≈ 18 s (logs) | 3,5 s |
| Memória semântica pronta | junto com o chat | 13,0 s, em segundo plano |

Orquestrador (8 frases × 2 repetições, modo esquema):

| Configuração | Acertos | Mediana | Tokens gerados (mediana) |
|---|---|---|---|
| Gemma 4 E4B, raciocínio ligado (comportamento anterior) | 16/16 | 8,1 s | 448 |
| **Gemma 4 E4B, raciocínio desligado (adotado)** | **16/16** | **1,2 s** | 36 |
| Qwen 2.5 Coder 7B | 16/16 | 1,5 s | 42 |

Esquema × JSON simples, com raciocínio ligado: orquestrador 14/16 × 15/16 (mediana 8,7 s nos dois); extração de compras 6/6 nos dois (10,8 s × 11,6 s). O Qwen não aceita `think`; foi medido sem o parâmetro.

M17, Ollama fechado (app real, `scripts/medir_m17.py`): resposta em 2,38 s com o botão "Tentar de novo" e aviso no terminal interno; chat pronto em 3,0 s. Pelo código anterior, eram no mínimo 6 s (3 tentativas e 2 esperas de 3 s) e até ≈ 6 min com o Ollama travado. No Windows, a conexão recusada em localhost leva ~2 s para falhar, daí o valor próximo do limite da verificação. Com o Ollama aberto, a mesma frase foi respondida em 18,9 s, sem o botão.

### Não verificado
- Execução do fluxo no GitHub Actions: depende do repositório publicado.
- Extração de compras com o raciocínio desligado: continua no padrão do Ollama até ser medida (`--so-extracao --raciocinio nao`).
- A suíte foi executada no ambiente de desenvolvimento com as dependências externas simuladas; no PC do usuário, só as medições acima.

## [V4] — Correção de acentuação na entrada (2026-11-16)

### Corrigido
- `app/main.py`: a entrada (stdin) do back-end passa a ser lida em UTF-8, como a saída. Antes, no Windows, textos com acento enviados pelo Electron chegavam corrompidos ("café" virava "cafÃ©" no chat e no banco).

## [V4] — Revisão de credenciais (2026-11-16)

### Segurança
- Varredura do código e do histórico Git de todas as branches: nenhuma chave, senha ou token real encontrado. O único token nos testes é falso e montado em partes.
- `.gitignore` passa a cobrir `.env.*`, `*secret*.json`, `*credentials*.json`, `*.pem`, `*.key`, `*.p12` e `*.pfx`.
- `.env.example` documenta as variáveis sem valores reais; o README orienta copiá-lo para `.env`.

## [V4] — Fase 1: base confiável (2026-11-03)

### Adicionado
- `services/intent_router.py`: roteamento por regras para frases conhecidas, sem chamar o LLM.
- Confirmação de compras em caso de dúvida e comando "desfazer última compra", limitado ao último registro da sessão.
- Preço por embalagem: colunas `embalagem_quantidade` e `embalagem_unidade` em `itens_compra` (schema v2).
- `tests/test_fase1.py`: 41 testes. A suíte passa a ter 70 testes.

### Alterado
- Só contextos `geral` e `outro` podem ir ao Gemini, fora do Modo Qwen; histórico e memórias restritos não são enviados.
- Com o orquestrador indisponível, frases sem regra não são enviadas à nuvem.
- A data da compra é calculada no Python; o LLM não define "ontem" ou "anteontem".
- A divergência entre total, quantidade e preço gera confirmação, sem recálculo silencioso.
- `GEMINI_API_KEY` passa a ser opcional.

### Corrigido
- Consultas de compras não gravam mais registros (P4).
- Novas tentativas não duplicam compras; a gravação ocorre em transação única (P5).
- Prompt geral no Gemini, sem o texto fixo de compras (P3), e tratamento correto de cota esgotada (P15).
- Sistema inicia sem chave do Gemini (P11).
- Agenda informa a indisponibilidade em vez de exibir JSON bruto.

### Dados
- Removida a compra nº 5, registro vazio criado por uma pergunta. Cópia prévia em `core/database/backups/`.

## [V4] — Correções do Modo Qwen e documentação (2026-11-03)

### Corrigido
- `desativar qwen` e `desativar modo qwen` passaram a retornar ao Gemma; antes, a frase era reconhecida como ativação.
- A inatividade de 30 minutos passou a ser avaliada antes de renovar o horário de atividade, na solicitação seguinte.
- `PROMPT_PROGRAMACAO` passou a ser string raw, eliminando `SyntaxWarning` e o caractere de controle no caminho do projeto.

### Adicionado
- `tests/test_gemma_service.py`: 7 testes do orquestrador, sem acesso ao Ollama. A suíte passa a ter 29 testes.
- `Sobre a Versão/06 - Evolução da V3 para a V4.md` e `Sobre a Versão/08 - Estado Atual da V4.md`.

### Alterado
- Documentos 01 a 05 de `Sobre a Versão` revisados para a V4.

## [V4] — Skill ProjectAnalyzer (2026-11-02)

### Adicionado
- `services/project_analyzer/`: Skill de análise de projetos e geração de documentação técnica 100% local (ver `Sobre a Versão/07 - Skill ProjectAnalyzer.md`).
- Comando no chat: `analisar projeto <caminho>` (detecção determinística no orquestrador, contexto `projetos`).
- `scripts/analyze_project.py`: execução pela linha de comando.
- `tests/test_project_analyzer.py`: 22 testes (`python -m unittest discover -s tests -v`).
- `core/config.py`: `PROJECT_ANALYZER_OUTPUT_DIR` (padrão `E:\Agente IA\Documentacao_Gerada`) e `PROJECT_ANALYZER_MODEL` (padrão `qwen2.5-coder:7b`).

### Decisões
- Saída fora do repositório e do projeto analisado; execução síncrona (chat bloqueado); modelo fixo Qwen 2.5-Coder com troca de VRAM (Gemma descarregado antes e Qwen liberado depois).
- A rota `projetos` nunca usa o fallback para o Gemini, o RAG ou a memória semântica.

## [V4] — 2026-11-02 (branch `V4`)

### Adicionado
- Versionamento da V4 que estava sem commit: Electron (`main.js`, `preload.js`, `renderer.js`, `index.*`), runtime Text-First, pacote `services/vector/` e `scripts/`.
- `InventoryAssistant.consultar_estoque()`: consulta de estoque por texto (somente leitura, sem LLM).
- Memória semântica ligada ao pipeline: contexto RAG no assistente local genérico e no Gemini; falas do usuário salvas no `MemoryService`.
- Exemplo few-shot de consulta de inventário no prompt do orquestrador.

### Corrigido
- `.gitignore.txt` renomeado para `.gitignore` (o Git ignorava o arquivo). Removidos do versionamento: `assistente_casa.db`, `__pycache__`, `Logs/` (arquivos locais preservados).
- `requirements.txt`: `google-generativeai` → `google-genai` (SDK usado no código); adicionados `edge-tts` e `pygame`.
- `db_service.py`: removido `from asyncio.windows_events import NULL`; tabela `historico_conversas` passa a ser criada.
- `InventoryAssistant` usa a voz/microfone do runtime e não fala/escuta com o modo voz desligado.
- Rota `inventario` deixou de responder "Consulta realizada com sucesso" sem consultar nada.
- Chat do Electron preserva quebras de linha nas respostas.

### Pendências conhecidas
- Alterar estoque por texto (baixa, correção) depende de diálogo por chat; hoje só por voz.
- Itens com `validacao_pendente` não são perguntados pelo chat.
- `compras` + `consultar` (ex.: "quanto gastei no Moreschi?") é roteado ao `ShoppingAssistant`, que é de registro.
- `AIService.processar_requisicao_complexa` usa prompt fixo de "texto de compras" para qualquer pedido enviado ao Gemini.
- Sem testes automatizados para estoque, serviços vetoriais reais e IPC.
