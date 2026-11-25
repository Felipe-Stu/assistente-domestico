# 03 - Arquitetura Geral

Este documento detalha a estrutura de diretórios, os módulos constituintes, suas responsabilidades, o fluxo principal e as relações de dependência do **Assistente Doméstico Inteligente**, no estado da **V5.5 (atualizado em 25/11/2026)**. As mudanças da V4.3 e da V5.5 estão na seção 2.F.

> [!NOTE]
> **V4.1 (fase das skills):** cada capacidade virou uma skill em `skills/`, escolhida por gatilhos ou pelo orquestrador a partir do catálogo (`core/skills/`), e executada pelo próprio roteiro. Entraram também o Claude (programação e ideias), a fila de ideias, o bot do Telegram e a biblioteca de contexto.

> [!IMPORTANT]
> A V4 representa uma expansão arquitetural significativa em relação à V3. Foram adicionados: uma camada de interface desktop (Electron), um novo pacote de serviços vetoriais (`services/vector/`) com 5 módulos, scripts de gestão do banco vetorial, e uma arquitetura de persistência híbrida (SQLite + ChromaDB). O modelo de inicialização foi reformulado para Text-First com ativação dinâmica de voz.

---

## 1. Organização das Pastas (Estrutura de Diretórios)

```text
assistente-domestico/
├── assets/                              # Armazenamento temporário de arquivos de voz (temp_voice.mp3)
├── app/
│   ├── main.py                          # Runtime (AssistenteRuntime): ciclo de vida, filas e pipeline orquestrador → skill
│   ├── ipc.py                           # [SK5] UTF-8, pipe do Electron isolado e emitir_electron
│   ├── sessao.py                        # [SK5] GerenciadorDeSessao (contexto ativo e histórico)
│   └── voz.py                           # [SK5] Modo voz e laço do microfone (classe base do runtime)
├── core/
│   ├── database/
│   │   ├── assistente_casa.db           # Banco de dados SQLite (compras, itens, controle_consumo, compromissos, ideias)
│   │   ├── chroma_db/                   # [NOVO V4] Banco vetorial ChromaDB (memórias e biblioteca_projeto)
│   │   ├── backups/                     # [M11] Cópias diárias (fora do Git)
│   │   └── estado_*.json, telegram_offset.json, biblioteca_indice.json  # [V4.1] Estado do Claude, do bot e da biblioteca (fora do Git)
│   ├── __init__.py
│   ├── config.py                        # Configurações globais, caminhos SQLite e ChromaDB, modelo de embedding
│   └── skills/                          # Catálogo, seletor (orquestrador pelo catálogo) e motor de roteiros
├── skills/                              # [SK1] Uma pasta por capacidade: SKILL.md (cabeçalho + instruções), prompts/, roteiro.py, exemplos.jsonl
│   ├── compras/  estoque/  agenda/  ideias/
│   ├── documentar-projeto/  programacao/  conversa-geral/
│   └── _modelo/                         # [SK6] Modelo usado por scripts/nova_skill.py (ignorado pelo catálogo)
├── Ideias/                              # [SK8] Uma análise .md por ideia (fora do Git; entra na biblioteca)
├── evals/                               # [SK0] Frases com a skill esperada e compras para medir a extração
├── Logs/                                # Gerados automaticamente (ignorados pelo Git)
│   └── eventos-AAAA-MM-DD.jsonl         # [M26] Uma linha JSON por evento; 30 dias de retenção
├── node_modules/                        # [NOVO V4] Dependências do Electron (npm)
├── scripts/                             # [NOVO V4] Scripts de gestão do banco vetorial
│   ├── inspect_vector_database.py       # CLI interativa para inspeção do ChromaDB
│   ├── migrate_vector_database.py       # Migração idempotente SQLite → ChromaDB
│   ├── rebuild_embeddings.py            # Reconstrução dos embeddings, preservando as memórias (P13)
│   ├── fazer_backup.py                  # [M11] Cópia de segurança manual
│   ├── ver_logs.py                      # [M26] Leitura dos eventos e tempo por etapa
│   ├── avaliar.py                       # [SK0] Mede a escolha da skill e a extração (evals/)
│   ├── nova_skill.py, validar_skills.py # [SK6] Cria e valida skills
│   ├── indexar_biblioteca.py            # [SKP] Indexa a biblioteca de contexto
│   ├── testar_skp.py, testar_claude_assinatura.py  # [SKP] Conferem o Claude (API e assinatura)
│   ├── configurar_telegram.py           # [SK8] Descobre o número do chat do bot
│   └── validate_vector_database.py      # Testes automatizados de busca semântica
├── tests/                               # Testes automatizados (231 em 23/11/2026), com dados de referência em tests/dados/
├── services/
│   ├── __init__.py
│   ├── ai_service.py                    # Interface com a API Gemini (nuvem) — fallback
│   ├── audio_service.py                 # Captura de microfone com RMS e bips
│   ├── backup_service.py                # [M11] Cópia diária do SQLite e do ChromaDB
│   ├── biblioteca_service.py            # [SKP] Biblioteca de contexto no ChromaDB (documentação e ideias)
│   ├── claude_service.py                # [SKP] Claude pela API (disponibilidade, reteste, limite mensal)
│   ├── claude_assinatura_service.py     # [SK8] Claude pela assinatura (claude -p, sem ferramentas)
│   ├── esquemas.py                      # [M03] JSON Schema da extração de compras
│   ├── ideias_service.py                # [SK8] Ideias: salvar, fila de análise, .md e comandos do bot
│   ├── telegram_service.py              # [SK8] Bot do Telegram (long polling, chats permitidos)
│   ├── db_service.py                    # Persistência SQLite com migrações de schema
│   ├── gemma_service.py                 # Orquestrador pelo catálogo de skills e assistente local (Gemma 4 E4B)
│   ├── intent_router.py                 # [NOVO V4] Roteamento por regras: aplica os gatilhos das skills
│   ├── inventory_assistant.py           # Controle preditivo de estoque (Regex + Gemma)
│   ├── llm_provider.py                  # Abstração de provedores LLM (Local/Nuvem)
│   ├── logger_service.py                # [M26] Eventos em JSON, requisição e etapas
│   ├── resilience_service.py            # Retry centralizado e parametrizável
│   ├── shopping_assistant.py            # Compras via LLM + SQLite + ChromaDB
│   ├── voice_service.py                 # Síntese neural (Edge TTS) + pygame
│   ├── project_analyzer/                # [NOVO V4] Skill ProjectAnalyzer (análise e documentação local de projetos)
│   └── vector/                          # [NOVO V4] Pacote da Arquitetura Vetorial
│       ├── __init__.py                  # Exporta os 5 serviços vetoriais
│       ├── embedding_service.py         # Geração de embeddings na CPU (SentenceTransformers)
│       ├── vector_store_service.py      # Wrapper desacoplado do ChromaDB PersistentClient
│       ├── memory_service.py            # Gerenciador de Memória de Curto/Longo Prazo
│       ├── semantic_search_service.py   # Busca Semântica Híbrida (Vector + SQLite)
│       └── context_retrieval_service.py # Montador de Contexto RAG para prompts
├── Sobre a Versão/                      # Documentação técnica da versão atual
├── .env                                 # Variáveis de ambiente (chaves, CLAUDE_MODO, TELEGRAM_*, EMBEDDING_*); modelo em .env.example
├── iniciar-assistente.bat               # [V4.1] Abre o Ollama se preciso e inicia o app
├── instalar-claude-code.bat, testar-claude-assinatura.bat, configurar-telegram.bat  # [V4.1] Configuração no PC
├── .gitignore                           # Regras de exclusão do Git (ignora .db, chroma_db, Logs, __pycache__, node_modules)
├── index.html                           # [NOVO V4] Interface HTML do Electron (chat + controles)
├── index.css                            # [NOVO V4] Estilos da interface desktop
├── main.js                              # [NOVO V4] Processo principal Electron (BrowserWindow + spawn Python)
├── preload.js                           # [NOVO V4] Bridge seguro IPC (contextBridge + window.api)
├── renderer.js                          # [NOVO V4] Lógica do Renderer (chat UI + controles + estado)
├── package.json                         # [NOVO V4] Manifesto npm do Electron
├── package-lock.json                    # [NOVO V4] Lock de dependências npm
├── requirements.txt                     # Dependências Python (atualizado na V4)
└── README.md                            # Documentação de alto nível
```

---

## 2. Descrição dos Módulos e Suas Responsabilidades

### A. Camada Electron (Desktop) — NOVO na V4

#### A.1. Processo Principal (`main.js`)
**Responsabilidade:** Ponto de entrada da aplicação desktop. Cria a `BrowserWindow` com dimensões 800×600 (mínimo 600×500), configurações de segurança (`contextIsolation: true`, `nodeIntegration: false`). Inicia o back-end Python como processo filho via `spawn('python', ['-u', 'app/main.py'])`. Implementa `sendToRenderer()` com proteção contra envios durante carregamento do DOM (`isLoading()`). Gerencia a comunicação IPC bidirecional: recebe JSON do stdout do Python, converte nomes de tipo de `snake_case` para `kebab-case` e repassa ao renderer via `webContents.send()`. Listeners IPC: `send-text`, `toggle-voice-mode`, `toggle-mute`, `toggle-microphone` (compatibilidade). Implementa shutdown graceful via `cleanupAndExit()` com timeout de 2 segundos antes de `SIGKILL`.

#### A.2. Preload Bridge (`preload.js`)
**Responsabilidade:** Expõe a API `window.api` no `contextBridge` para comunicação segura entre o Renderer e o Main Process. Métodos de envio: `sendText()`, `toggleVoiceMode()`, `toggleMute()`, `toggleMicrophone()` (compatibilidade). Listeners de recebimento: `onStateChanged()`, `onUserMessage()`, `onAssistantMessage()`, `onRespostaBackend()` (alias), `onVoiceModeStatus()`, `onMicrophoneStatus()` (compatibilidade), `onDebugLog()`, `onError()`, `onSystemReady()`. Todos os listeners incluem logging detalhado de diagnóstico via `logIPC()`.

#### A.3. Renderer — Interface Visual (`renderer.js` + `index.html` + `index.css`)
**Responsabilidade:** Renderiza a interface completa do chat: mensagens do usuário (avatar 👤) e do assistente (avatar 🤖) com timestamps. Painel lateral com: toggle de Modo Voz (checkbox estilizado), badge de status de voz com 5 estados visuais (`inactive`, `loading`, `active`, `partial`, `listening`, `error`), botão Mute (TTS). Terminal de debug com mensagens categorizadas (`system`, `error`, `success`, `process`). Gerencia estado local (`isMuted`, `voiceModeEnabled`, `backendState`). O input do chat permanece **sempre habilitado** (modelo Text-First), exceto durante estados `PROCESSING`, `RESPONDING` e `ERROR`.

---

### B. Back-End Python

#### B.1. Runtime Principal (`app/main.py`)
**Responsabilidade:** Classe `AssistenteRuntime` — núcleo do sistema. Implementa:
- **Inicialização em 2 fases:** Fase 1 (essencial): `DatabaseService`, `VectorStoreService`, `MemoryService`, `ContextRetrievalService`, `AIService`, Claude (`_criar_claude`: assinatura ou API, por `CLAUDE_MODO`), `BibliotecaService`, `IdeiasService`, `LocalLLMProvider`, `CloudLLMProvider`, `InventoryAssistant`, `ShoppingAssistant`, `VoiceService`, `AudioService`. Fase 2 (sob demanda): ativação de hardware de voz via `_ativar_modo_voz()`.
- **Event Loop:** Baseado em `queue.Queue`, com linhas de execução para `_leitor_stdin()` (comandos do Electron), `_loop_microfone()` (captura condicional), varredura de estoque, verificação do Ollama, cópia de segurança do dia (M11), fila de análise das ideias e bot do Telegram (V4.1).
- **Protocolo IPC:** Função `emitir_electron()` padroniza saída JSON para stdout.
- **Estados do sistema:** `STARTING`, `INITIALIZING`, `READY`, `WAITING_INPUT`, `PROCESSING`, `STOPPING`, `ERROR`.
- **Processamento:** `_processar_solicitacao()` implementa o pipeline: pendência de confirmação de uma skill → comandos do modo Qwen → comando de projeto → gatilhos das skills → orquestrador pelo catálogo → roteiro da skill (ou conversa geral, local ou Gemini) → resposta. Desde a V4.1, um roteiro pode devolver o pedido à conversa geral (`Resposta.encaminhar`).
- **Serviços das skills:** `_contexto_skill(skill)` entrega a cada roteiro só o que ele pode usar (banco, assistentes, `llm_local`, `ideias`). O Claude só vai às skills com `privacidade: claude` listadas em `CLAUDE_SKILLS`.
- **Memória semântica:** `_enriquecer_com_memoria()` anexa o contexto do `ContextRetrievalService` às instruções do assistente local genérico e do Gemini (só na conversa geral). `_registrar_memoria()` salva a fala do usuário no `MemoryService`, exceto nos contextos de `CONTEXTOS_SEM_MEMORIA` (`compras`, `inventario`, `agenda`, `projetos`, `ideias`), que já têm registro próprio. Falhas no ChromaDB não interrompem o pipeline.

#### B.2. Orquestrador Local (`services/gemma_service.py`)
**Responsabilidade:** Encapsula chamadas ao Gemma 4 E4B via Ollama. `orquestrar_requisicao()` escolhe a skill pelo catálogo (prompt fixo e JSON Schema de `core/skills/seletor.py`, raciocínio desligado) e valida a decisão; os contextos aceitos vêm do catálogo (`valores_permitidos()`). `executar_assistente_local()` responde a conversa geral. O orquestrador por contextos fixos foi removido no SK5.

#### B.3. Abstração LLM (`services/llm_provider.py`)
**Responsabilidade:** `BaseLLMProvider` (abstrata) → `LocalLLMProvider` (Ollama, `timeout=120.0`) e `CloudLLMProvider` (Gemini via AIService). **Atualizado na V4:** mantém o modelo ativo em memória (`MODO_QWEN_ATIVO`), alterna Gemma e Qwen e libera a VRAM com `keep_alive=0`. O `CloudLLMProvider` é criado no runtime, mas não é usado por nenhum assistente.

#### B.4. Resiliência (`services/resilience_service.py`)
**Responsabilidade:** `execute_with_retry()` centralizado com suporte a callbacks de validação, alertas de voz e exceções recuperáveis.

#### B.5. Assistente de Compras (`services/shopping_assistant.py`) — Atualizado na V4
**Responsabilidade:** Processa transcrições de compras via LLM local em duas etapas: `preparar_compra()` extrai, valida e aponta dúvidas sem gravar; `registrar_compras()` grava em transação única. Também resolve datas no Python e oferece `desfazer_ultimo_registro()`. **Na V4, recebe `VectorStoreService` como dependência injetada** e, após cada compra gravada no SQLite, **vetoriza automaticamente cada item no ChromaDB** com representação em linguagem natural contendo produto, marca, estabelecimento, preço e data. Não atualiza `controle_consumo` (P1 no documento 08).

#### B.6. Assistente de Inventário (`services/inventory_assistant.py`)
**Responsabilidade:** Controle preditivo de estoque. Classificação em dois níveis: Regex → Gemma 4 local. **Atualizado na V4:**
- Recebe `VoiceService`/`AudioService` compartilhados do runtime e a função `modo_voz_ativo`. Sem modo voz ativo, não fala nem escuta.
- Na varredura inicial em modo texto, itens com autonomia esgotada são marcados com `validacao_pendente = 1`. A varredura só roda na inicialização, antes de o usuário ativar a voz, portanto a pergunta por voz não é alcançada (P8 no documento 08).
- Novo método `consultar_estoque(texto)`: somente leitura de `controle_consumo` (itens ativos), filtro por termos do produto e estimativa do restante (`quantidade_comprada + residual − dias/ritmo`, mínimo 0). Sem LLM.

#### B.7. Banco de Dados (`services/db_service.py`)
**Responsabilidade:** Persistência relacional SQLite com `PRAGMA user_version`. Tabelas: `compras`, `itens_compra`, `controle_consumo`, `historico_conversas`. Schema v2: colunas de embalagem em `itens_compra`. `salvar_compras_da_ia()` grava várias compras em transação única. Nenhum fluxo insere registros em `controle_consumo` ou usa `historico_conversas`.

#### B.8. IA na Nuvem (`services/ai_service.py`)
**Responsabilidade:** Interface Gemini API para perguntas gerais. `processar_requisicao_complexa` usa prompt geral e histórico legível. O cliente é criado no primeiro uso, e `disponivel()` informa se há chave configurada.

#### B.9. Serviços de Voz e Áudio
- **`voice_service.py`:** Síntese neural via edge-tts + pygame. Inicialização lazy na V4.
- **`audio_service.py`:** Captura de microfone com RMS. Inicialização lazy na V4.

#### B.10. Log (`services/logger_service.py`)
**Responsabilidade:** Logger transversal. Desde 22/11/2026 (M26), grava uma linha JSON por evento em `Logs/eventos-AAAA-MM-DD.jsonl`. `requisicao()` dá um identificador a todos os eventos de uma solicitação; `etapa()` e `cronometrado()` medem roteamento, extração, banco, voz e memória. A API antiga (`log_geral`, `log_assistente`) continua disponível.

#### B.11. Cópia de segurança (`services/backup_service.py`)
**Responsabilidade:** Cópia diária do SQLite (`VACUUM INTO` + `integrity_check`) e do ChromaDB (zip) em `core/database/backups/auto/AAAA-MM-DD/`, com manifesto e retenção de 7 diárias e 4 semanais. Iniciada em segundo plano pelo runtime (M11).

---

#### B.12. Catálogo e motor de skills (`core/skills/`) — V4.1
**Responsabilidade:** `catalogo.py` lê `skills/*/SKILL.md` (cabeçalho YAML validado: contextos, estado, privacidade, entradas, saídas, execução, gatilhos com prioridade única) e ignora pastas que começam com `_` ou `.`. `seletor.py` monta o prompt e o JSON Schema da decisão `{skill, acao, dificuldade}`. `motor.py` carrega o `roteiro.py` de cada skill e executa `executar(ctx, texto, decisao)` e `responder_pendencia(...)`, devolvendo `Resposta(texto, fala, pendencia, encaminhar)`.

#### B.13. Claude (`services/claude_service.py`, `services/claude_assinatura_service.py`) — V4.1
**Responsabilidade:** Mesma interface nos dois modos (`configurado`, `verificar_disponibilidade`, `gerar_texto`).
- **API:** cota esgotada, problema de cobrança ou chave recusada deixam o Claude indisponível até a primeira solicitação depois das 8h; com `retry-after`, até o horário indicado. Limite mensal estimado pelos tokens.
- **Assinatura:** chama `claude -p --output-format json` sem ferramentas, sem MCP, numa pasta temporária e sem a chave de API no ambiente. Limite do plano: reteste depois de `CLAUDE_ASSINATURA_RETESTE_MIN`; sem login: na manhã seguinte. Acha o `claude.exe` também em `~/.local/bin`.
- **Estado:** em `core/database/estado_claude*.json`, fora do Git.

#### B.14. Ideias (`services/ideias_service.py`) — V4.1
**Responsabilidade:** Tabela `ideias` (título, texto, origem, situação, análise). `salvar()` grava na hora. A fila em segundo plano manda as pendentes ao Claude (prompt `skills/ideias/prompts/analise.md`) e grava a análise no banco e em `Ideias/ideia-NNNN-*.md`, depois atualiza a biblioteca. Sem Claude, a ideia continua pendente e é tentada de novo a cada `IDEIAS_RETESTE_MIN`. Também responde aos comandos do bot e separa pergunta de ideia (`parece_pergunta`, `pede_para_salvar`).

#### B.15. Bot do Telegram (`services/telegram_service.py`) — V4.1
**Responsabilidade:** Long polling com `getUpdates` (o PC não fica exposto), só para os chats de `TELEGRAM_CHAT_IDS`. Outros chats são ignorados e registrados só pelo número. Grava o offset antes de responder, para nunca processar duas vezes. Divide mensagens longas e nunca registra o token nos logs.

#### B.16. Biblioteca de contexto (`services/biblioteca_service.py`) — V4.1
**Responsabilidade:** Indexação incremental no ChromaDB (coleção `biblioteca_projeto`, separada das memórias). Fontes: README, CHANGELOG, `Sobre a Versão/`, `SKILL.md`, documentação gerada e a pasta extra `Ideias/`. A pasta de planejamento fica de fora. Devolve só os trechos mais próximos da pergunta.

---

### C. Pacote Vetorial (`services/vector/`) — NOVO na V4

#### C.1. `embedding_service.py`
**Responsabilidade:** Carrega o modelo `paraphrase-multilingual-MiniLM-L12-v2` como Singleton na CPU. Expõe `gerar_embedding(texto)` para vetorização individual e `gerar_embeddings_em_lote(textos)` para processamento em batch (batch_size=32). Latência típica: 15-30ms por vetor.

#### C.2. `vector_store_service.py`
**Responsabilidade:** Wrapper desacoplado sobre `chromadb.PersistentClient`. Opera com Singleton do cliente. Coleção padrão: `assistente_domestico_memory` (cosseno). Expõe: `upsert_documents()` (idempotente, com vetorização em lote automática), `search_similarity()` (com score de corte e filtro de metadados), `delete_documents()`, `count_documents()`. Define a dataclass `VectorDocument(id, content, metadata, embedding)`.

#### C.3. `memory_service.py`
**Responsabilidade:** Avalia se uma interação tem valor semântico para persistência via `_deve_salvar_em_longo_prazo()`. Filtra automaticamente saudações, interjeições, e comandos de infraestrutura. Persiste fatos relevantes com metadados estruturados (`assistant`, `category`, `entity_type`, `importance`, `created_at`). Recupera memórias por relevância semântica com filtro de metadados.

#### C.4. `semantic_search_service.py`
**Responsabilidade:** Busca vetorial pura (`busca_semantica_pura()`) e busca híbrida de compras (`busca_hibrida_compra()`) que localiza itens no ChromaDB e hidrata dados exatos do SQLite via JOIN em `itens_compra` + `compras`.

#### C.5. `context_retrieval_service.py`
**Responsabilidade:** Executa recuperação de memória semântica e gera string formatada para injeção como contexto nos prompts da LLM. Formato de saída: bloco delimitado com categoria, data e conteúdo para cada memória relevante.

### D. Skill ProjectAnalyzer (`services/project_analyzer/`) — NOVO na V4

**Responsabilidade:** Analisar um diretório de projeto (somente leitura) e gerar documentação Markdown na pasta `PROJECT_ANALYZER_OUTPUT_DIR`, usando Python para extração/indexação e o LLM local (`qwen2.5-coder:7b`) apenas para interpretação. Acionada pelo comando `analisar projeto <caminho>` (contexto `projetos`) ou pela skill `documentar-projeto`, sem fallback para a nuvem. Detalhes em `07 - Skill ProjectAnalyzer.md`.

### E. Skills (`skills/`) — V4.1

| Skill | Contexto | Privacidade | Execução | O que faz |
| :--- | :--- | :--- | :--- | :--- |
| `compras` | compras | local | roteiro | Registra, consulta e desfaz compras; uma chamada ao modelo por compra |
| `estoque` | inventario | local | roteiro | Consulta o estoque (somente leitura) |
| `agenda` | agenda | local | roteiro | Anota, consulta e cancela compromissos (tabela `compromissos`) |
| `ideias` | ideias | claude | roteiro | Salva e consulta ideias de projetos; encaminha à conversa o que não é ideia salva |
| `programacao` | programacao | claude | roteiro | Claude como principal; Qwen + biblioteca como reserva |
| `documentar-projeto` | projetos | local | roteiro | ProjectAnalyzer a partir de um caminho |
| `conversa-geral` | geral, outro | nuvem-permitida | nucleo | Assistente local; Gemini nas difíceis |

---

### F. V4.3 e V5.5 — módulos novos

#### F.1. Núcleo como servidor (V5.5)
| Módulo | Responsabilidade |
|---|---|
| `app/servidor.py` | Starlette + uvicorn em 127.0.0.1:8765: saúde, mensagens, comandos, anexos, eventos (SSE), resumo de gastos, `/entrar`, páginas `web/`. Cabeçalhos de segurança em toda resposta. Encerra se o núcleo parar; não sobe um segundo núcleo na mesma porta. |
| `app/eventos.py` | Barramento: cada evento é publicado uma vez e entregue aos ouvintes; guarda os últimos 60 da conversa e o estado atual; identificador de instância para o cliente perceber reinício. |
| `app/ipc.py` | `emitir_electron` publica no barramento; só imprime na saída padrão na ponte antiga. |
| `app/laco.py` | Partida dos serviços e laço de comandos (`send_text`, voz, mudo, documento, shutdown), com o canal de origem (`app`, `celular`). |
| `app/documentos_app.py` | Importação de notas pelo app, pasta de entrada, Telegram e celular; apaga o temporário do celular depois de importar. |
| `services/dispositivos_service.py` | Token por aparelho (só o hash SHA-256), escopos `local` e `remoto`, revogação, token local do PC; relê o arquivo quando ele muda. |
| `cliente-api.js` | Electron como cliente: sobe o servidor separado da janela se ele não estiver no ar, lê o SSE com reconexão e envia por POST. |
| `web/` | Página do celular (PWA), painel de gastos, `formatar.js` (Markdown seguro, usado também pela janela do PC). |
| `app/mcp_casa.py` | Servidor MCP somente leitura (desligado). |

#### F.2. Compras completas (V4.2 e V4.3)
| Módulo | Responsabilidade |
|---|---|
| `services/nfce_service.py` | Leitores exatos de NFC-e (HTML e texto) e NF-e (texto); Código NF, Série e Emissão; chave de acesso com dígito verificador; remove os dados do consumidor. |
| `services/documentos_service.py` | Importa HTML, PDF e foto; foto em duas etapas (transcrição + leitor); cópia em `Anexos/`; nota repetida pela chave; aviso de possível repetida. |
| `services/imagem_service.py` | Prepara a foto: recorte, faixas, ampliação. |
| `services/pasta_entradas_service.py` | Vigia a pasta `Entradas`. |
| `services/perguntas_compra.py` | Perguntas antes do "sim": loja, produto cortado, conferência de loja e data. |
| `services/consultas_service.py` + `services/periodos.py` | Consultas de gastos em centavos e períodos em português; resumo do painel. |
| `services/edicao_compra.py` | Correções e observações em compras já gravadas. |
| `services/produtos_service.py`, `services/estoque_service.py`, `services/dinheiro.py` | Catálogo, estoque alimentado pelas compras, valores em centavos. |
| `app/sessao.py` | Histórico com janela, resumo e gravação no SQLite. |

## 3. Ciclo de Execução da Aplicação (Fluxo Principal V4)

```
[Usuário abre o Electron Desktop]
         │
         ▼
[main.js: BrowserWindow + spawn Python]
         │
         ▼
[AssistenteRuntime.__init__()]
         │
         ▼
[FASE 1: Inicialização Essencial (Text-First)]
 DatabaseService → SQLite conectado
 VectorStoreService → ChromaDB inicializado (CPU)
 MemoryService + ContextRetrievalService → Prontos
 AIService → Gemini configurado (cliente criado no primeiro uso)
 LocalLLMProvider(gemma4:e4b) + CloudLLMProvider
 InventoryAssistant + ShoppingAssistant (com vector_store)
 VoiceService + AudioService (construtor leve, sem init de hardware)
         │
         ▼
[Thread: _leitor_stdin() ← Comandos do Electron]
[Thread: _loop_microfone() ← Em espera, aguarda voice_mode_active=True]
[Thread: _varredura_background() ← Estoque preditivo]
         │
         ▼
[Estado: READY → WAITING_INPUT]
[emitir_electron("system_ready")]
[Chat desbloqueado no Electron!]
         │
         ▼
[EVENT LOOP: queue.Queue.get()]
         │
         ├── [type="send_text" ou "user_message"]
         │     ▼
         │   _processar_solicitacao(texto)
         │     │
         │     ├── [Pendência de uma skill?] → responder_pendencia (ex.: "sim" de uma compra)
         │     ├── [Comandos do modo Qwen e "analisar projeto <caminho>"]
         │     │
         │     ├── [PASSO 1: Gatilhos das skills (sem IA)]
         │     │   → senão, orquestrar_requisicao: Gemma 4 escolhe {skill, ação, dificuldade} pelo catálogo
         │     │
         │     ├── [PASSO 2: Execução]
         │     │   ├── [skill com roteiro] → skills/<nome>/roteiro.py
         │     │   │     compras · estoque · agenda · ideias · programacao · documentar-projeto
         │     │   │     (o roteiro pode pedir confirmação ou encaminhar à conversa geral)
         │     │   ├── [conversa-geral, fácil] → executar_assistente_local → Gemma 4 (com contexto RAG)
         │     │   └── [conversa-geral difícil ou falha local] → Gemini API (nuvem, com RAG restrito)
         │     │
         │     └── [PASSO 3: Resposta]
         │         → emitir_electron("assistant_message")
         │         → VoiceService.falar() (se modo voz ativo e não mutado)
         │
         ├── [Linha de execução: fila de ideias] → Claude → banco + Ideias/*.md → biblioteca → aviso no Telegram
         ├── [Linha de execução: bot do Telegram] → IdeiasService.responder_mensagem
         │
         ├── [type="voice_input"]
         │     → Mesmo pipeline de _processar_solicitacao()
         │
         ├── [type="toggle_voice_mode"]
         │     → _ativar_modo_voz() / _desativar_modo_voz()
         │     → emitir_electron("voice_mode_status")
         │
         ├── [type="toggle_mute"]
         │     → Alterna is_muted (controla apenas TTS)
         │
         └── [type="shutdown"]
               → Shutdown graceful (encerra threads, desativa hardware)

```

---

## 4. Dependências e Acoplamento de Componentes

1. **`main.js` (Electron Main)** acopla-se a:
   - `electron` (BrowserWindow, ipcMain)
   - `child_process.spawn` (inicia Python)
   - `preload.js` (via webPreferences)

2. **`preload.js`** acopla-se a:
   - `electron` (contextBridge, ipcRenderer)

3. **`renderer.js`** acopla-se a:
   - `window.api` (exposto pelo preload)
   - DOM elements (`index.html`)

4. **`app/main.py` (AssistenteRuntime)** acopla-se a:
   - `DatabaseService`, `AIService`, `VoiceService`, `AudioService`
   - `LocalLLMProvider`, `CloudLLMProvider`
   - `InventoryAssistant`, `ShoppingAssistant`
   - `VectorStoreService`, `MemoryService`, `ContextRetrievalService`
   - `gemma_service.orquestrar_requisicao`, `gemma_service.executar_assistente_local`
   - `core.skills` (catálogo e motor), `ClaudeService`/`ClaudeAssinaturaService`, `BibliotecaService`, `IdeiasService`, `TelegramService`, `BackupService`
   - `resilience_service.execute_with_retry`
   - `logger_service`

5. **`ShoppingAssistant`** acopla-se a:
   - `BaseLLMProvider` (injetado como `LocalLLMProvider`)
   - `DatabaseService`
   - `VectorStoreService` (injetado — **NOVO na V4**)
   - `logger_service`

6. **`InventoryAssistant`** acopla-se a:
   - `BaseLLMProvider` (injetado como `LocalLLMProvider`)
   - `DatabaseService`
   - `VoiceService` e `AudioService` (instâncias compartilhadas injetadas pelo runtime)
   - `logger_service`

7. **`VectorStoreService`** acopla-se a:
   - `chromadb` (PersistentClient)
   - `EmbeddingService`
   - `core/config.CHROMA_DIR`

8. **`EmbeddingService`** acopla-se a:
   - `sentence_transformers` (SentenceTransformer)
   - `core/config.EMBEDDING_MODEL_NAME`

9. **`MemoryService`** acopla-se a:
   - `VectorStoreService`

10. **`SemanticSearchService`** acopla-se a:
    - `VectorStoreService`
    - `DatabaseService`

11. **`ContextRetrievalService`** acopla-se a:
    - `SemanticSearchService`
    - `MemoryService`

12. **`LocalLLMProvider`** acopla-se a:
    - SDK `ollama` (via `ollama.Client`)

13. **`CloudLLMProvider`** acopla-se a:
    - `AIService`

14. **`gemma_service`** acopla-se a:
    - `llm_provider` (o SDK `ollama` é acessado por meio dele)
    - `core.skills` (catálogo e seletor)
    - `resilience_service.InvalidOrchestratorOutputException`
    - `logger_service`

15. **`AIService`** acopla-se a:
    - SDK `google-genai`
    - `logger_service`

16. **`DatabaseService`** acopla-se a:
    - `sqlite3`
    - `core/config.DB_PATH`
    - `logger_service`

17. **Roteiros das skills (`skills/*/roteiro.py`)** acoplam-se só a:
    - `core.skills` (`Resposta`, `obter_catalogo`) e aos serviços entregues pelo `Contexto` (`ctx.servico(...)`)
    - Exceção: `skills/ideias/roteiro.py` importa as funções de texto de `services/ideias_service.py`

18. **`IdeiasService`** acopla-se a:
    - `DatabaseService`, Claude (qualquer dos dois modos), `BibliotecaService`, `logger_service`

19. **`TelegramService`** acopla-se a:
    - `requests` e a uma função `ao_receber(chat, texto)` dada pelo runtime (hoje, `IdeiasService.responder_mensagem`)

