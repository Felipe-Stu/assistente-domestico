# 03 - Arquitetura Geral

Este documento detalha a estrutura de diretórios, os módulos constituintes, suas responsabilidades, o fluxo principal e as relações de dependência na **Versão 4 (V4)** do **Assistente Doméstico Inteligente**.

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
│   │   ├── assistente_casa.db           # Banco de dados SQLite (compras, itens, controle_consumo)
│   │   └── chroma_db/                   # [NOVO V4] Banco vetorial ChromaDB (persistência local)
│   ├── __init__.py
│   ├── config.py                        # Configurações globais, caminhos SQLite e ChromaDB, modelo de embedding
│   └── skills/                          # Catálogo, seletor (orquestrador pelo catálogo) e motor de roteiros
├── skills/                              # [SK1] Uma pasta por capacidade: SKILL.md (cabeçalho + instruções) e prompts/
│   ├── compras/  estoque/  agenda/
│   └── documentar-projeto/  programacao/  conversa-geral/
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
│   └── validate_vector_database.py      # Testes automatizados de busca semântica
├── tests/                               # [NOVO V4] Testes automatizados (ProjectAnalyzer e orquestrador)
├── services/
│   ├── __init__.py
│   ├── ai_service.py                    # Interface com a API Gemini (nuvem) — fallback
│   ├── audio_service.py                 # Captura de microfone com RMS e bips
│   ├── backup_service.py                # [M11] Cópia diária do SQLite e do ChromaDB
│   ├── db_service.py                    # Persistência SQLite com migrações de schema
│   ├── gemma_service.py                 # Orquestrador local via Ollama/Gemma 4 e:4b
│   ├── intent_router.py                 # [NOVO V4] Roteamento por regras, sem LLM
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
├── .env                                 # Variáveis de ambiente (GEMINI_API_KEY, EMBEDDING_MODEL_NAME)
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
- **Inicialização em 2 fases:** Fase 1 (essencial): `DatabaseService`, `VectorStoreService`, `MemoryService`, `ContextRetrievalService`, `AIService`, `LocalLLMProvider`, `CloudLLMProvider`, `InventoryAssistant`, `ShoppingAssistant`, `VoiceService`, `AudioService`. Fase 2 (sob demanda): ativação de hardware de voz via `_ativar_modo_voz()`.
- **Event Loop:** Baseado em `queue.Queue` com 3 threads: `_leitor_stdin()` (leitura de comandos do Electron), `_loop_microfone()` (captura contínua condicional) e `_varredura_background()` (estoque).
- **Protocolo IPC:** Função `emitir_electron()` padroniza saída JSON para stdout.
- **Estados do sistema:** `STARTING`, `INITIALIZING`, `READY`, `WAITING_INPUT`, `PROCESSING`, `STOPPING`, `ERROR`.
- **Processamento:** `_processar_solicitacao()` implementa o pipeline Orquestração → Roteamento → Execução → Resposta.
- **Memória semântica:** `_enriquecer_com_memoria()` anexa o contexto do `ContextRetrievalService` às instruções do assistente local genérico e do Gemini (não em `compras`/`agenda`, que geram JSON). `_registrar_memoria()` salva a fala do usuário no `MemoryService` (exceto `compras`, já vetorizadas pelo ShoppingAssistant, e `inventario`). Falhas no ChromaDB não interrompem o pipeline.

#### B.2. Orquestrador Local (`services/gemma_service.py`)
**Responsabilidade:** Encapsula chamadas ao Gemma 4 e:4b via Ollama. Fornece `orquestrar_requisicao()` com validação de schema (`_validar_schema_orquestrador`) e sanitização JSON (`_sanitizar_resposta_json`). Fornece `executar_assistente_local()` para fluxos genéricos.

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

**Responsabilidade:** Analisar um diretório de projeto (somente leitura) e gerar documentação Markdown na pasta `PROJECT_ANALYZER_OUTPUT_DIR`, usando Python para extração/indexação e o LLM local (`qwen2.5-coder:7b`) apenas para interpretação. Acionada pelo comando `analisar projeto <caminho>` (contexto `projetos`), sem fallback para a nuvem. Detalhes em `07 - Skill ProjectAnalyzer.md`.

---

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
         │     ├── [PASSO 1: Orquestração Gemma 4]
         │     │   execute_with_retry(orquestrar_requisicao)
         │     │   → Gemma 4 local classifica {dificuldade, contexto, ação}
         │     │
         │     ├── [INTERCEPTAÇÃO: resposta_direta]
         │     │   → Retorna imediatamente sem roteamento
         │     │
         │     ├── [INTERCEPTAÇÃO: contexto="projetos"]
         │     │   → ProjectAnalyzer (Qwen local) → Documentacao_Gerada
         │     │
         │     ├── [PASSO 2: Roteamento]
         │     │   ├── [compras] → preparar_compra → confirmação se houver dúvida → SQLite + ChromaDB
         │     │   ├── [facil + inventario] → consultar_estoque (criar/corrigir: informa limitação)
         │     │   ├── [facil + outro] → executar_assistente_local → Gemma 4 (com contexto RAG)
         │     │   └── [geral/outro difícil ou falha 3x] → Gemini API (nuvem, com RAG restrito)
         │     │
         │     └── [PASSO 3: Resposta]
         │         → emitir_electron("assistant_message")
         │         → VoiceService.falar() (se modo voz ativo e não mutado)
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
    - `project_analyzer.command_parser`
    - `resilience_service.InvalidOrchestratorOutputException`
    - `logger_service`

15. **`AIService`** acopla-se a:
    - SDK `google-genai`
    - `logger_service`

16. **`DatabaseService`** acopla-se a:
    - `sqlite3`
    - `core/config.DB_PATH`
    - `logger_service`
