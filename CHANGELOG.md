# CHANGELOG

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
