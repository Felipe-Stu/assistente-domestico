# 02 - Tecnologias Utilizadas

Este documento detalha o ecossistema tecnológico empregado na **Versão 4 (V4)** do **Assistente Doméstico Inteligente**, registrando as tecnologias herdadas da V3 e as novas tecnologias incorporadas nesta versão.

---

## 1. Tecnologias Herdadas da V3 (Mantidas na V4)

### Linguagem Principal
*   **Python (v3.10+)**
    *   **Finalidade:** Linguagem de desenvolvimento de todo o back-end do sistema.
    *   **Onde é utilizada:** Em todos os scripts do projeto (serviços, assistentes, configurações, scripts de migração).
    *   **Introduzido em:** V1.

---

### LLM Local
*   **Ollama**
    *   **Finalidade:** Servidor local de inferência de modelos de linguagem. Expõe uma API HTTP local (padrão em `http://127.0.0.1:11434`).
    *   **Onde é utilizada:** Chamado diretamente pelo `gemma_service.py` (orquestração) e indiretamente pelo `LocalLLMProvider` em `llm_provider.py`.
    *   **Introduzido em:** V3. Mantido na V4.

*   **Modelo Gemma 4 e:4b (`gemma4:e4b`)**
    *   **Finalidade:** LLM local de 4 bilhões de parâmetros. Atua como:
        1.  **Orquestrador** (`gemma_service.py`): desde a V4.1, escolhe a skill pelo catálogo
        2.  **Extrator de Dados de Compras** (via `LocalLLMProvider` no `ShoppingAssistant`)
        3.  **Classificador de Intenções de Inventário** (via `LocalLLMProvider` no `InventoryAssistant`)
        4.  **Extrator de compromissos da agenda** e **respostas sobre ideias salvas** (V4.1, serviço `llm_local` das skills)
        5.  **Conversa geral** (`executar_assistente_local`)
    *   **Formato de comunicação:** JSON Schema enviado no parâmetro `format` do Ollama (V4.1, `services/esquemas.py`); com biblioteca antiga, recai para `format="json"`. No orquestrador, o raciocínio (`think`) é desligado.
    *   **Introduzido em:** V3. Mantido na V4.

*   **Modelo Qwen 2.5-Coder 7B (`qwen2.5-coder:7b`)**
    *   **Finalidade:** LLM local mais forte, usado no Modo Qwen, na interpretação feita pelo ProjectAnalyzer e, desde a V4.1, como reserva da skill de programação quando o Claude não está disponível (com a biblioteca de contexto). A troca descarrega o Gemma da VRAM (13 a 15 s, medido no SK0).
    *   **Onde é utilizada:** `services/llm_provider.py` e `core/config.py` (`PROJECT_ANALYZER_MODEL`).
    *   **Introduzido em:** **V4**.

*   **SDK Python `ollama`**
    *   **Finalidade:** Biblioteca cliente Python que abstrai as chamadas HTTP ao servidor Ollama local.
    *   **Onde é utilizada:** `services/gemma_service.py` e `services/llm_provider.py`.
    *   **Introduzido em:** V3. Mantido na V4.

---

### Inteligência Artificial na Nuvem (Fallback)
*   **Google Gemini API (Modelo `gemini-2.5-flash`)**
    *   **Finalidade na V4:** Atende somente perguntas gerais (`geral` e `outro`), quando o LLM local falha persistentemente ou a orquestração as classifica como `medio_dificil`.
    *   **Onde é utilizada:** `services/ai_service.py` e, indiretamente, via `CloudLLMProvider` em `services/llm_provider.py`.
    *   **Introduzido em:** V1. Papel alterado na V3 (de primário para fallback). Mantido na V4.

*   **SDK `google-genai` (>= 1.0.0)**
    *   **Finalidade:** Biblioteca cliente para comunicação com os endpoints Gemini.
    *   **Onde é utilizada:** `services/ai_service.py`.
    *   **Introduzido em:** V1. Mantido na V4.

> [!NOTE]
> O cliente é criado no primeiro uso, portanto a chave é opcional. `processar_requisicao_complexa` usa um prompt geral e o tratamento de erros de `chamar_llm`.

---

### Processamento e Síntese de Áudio
*   **SpeechRecognition (>= 3.10.0)**
    *   **Finalidade:** Captura do buffer analógico do microfone e calibração de ruído ambiente.
    *   **Onde é utilizada:** `services/audio_service.py`.
    *   **Introduzido em:** V1. Mantido na V4.

*   **PyAudio (>= 0.2.14)**
    *   **Finalidade:** Bindings de baixo nível do sistema operacional para leitura do fluxo do microfone.
    *   **Onde é utilizada:** Indiretamente pelo `SpeechRecognition` em `services/audio_service.py`.
    *   **Introduzido em:** V1. Mantido na V4.

*   **edge-tts**
    *   **Finalidade:** Geração de fala (Text-to-Speech) utilizando os modelos neurais da Microsoft Edge.
    *   **Onde é utilizada:** `services/voice_service.py`.
    *   **Introduzido em:** V2. Mantido na V4.

*   **pygame (Módulo `pygame.mixer`)**
    *   **Finalidade:** Reprodução local dos arquivos de voz neural gerados pelo edge-tts.
    *   **Onde é utilizada:** `services/voice_service.py`.
    *   **Introduzido em:** V2. Mantido na V4.

*   **winsound (Biblioteca Padrão do Windows)**
    *   **Finalidade:** Emissão de bips sonoros de status do microfone.
    *   **Onde é utilizada:** `services/audio_service.py`.
    *   **Introduzido em:** V2. Mantido na V4.

---

### Banco de Dados Relacional
*   **SQLite**
    *   **Finalidade:** Banco de dados relacional embarcado para persistência de compras, itens e controle de inventário.
    *   **Onde é utilizada:** Arquivo físico em `core/database/assistente_casa.db`.
    *   **Introduzido em:** V1. Mantido na V4 com suporte a migrações por `PRAGMA user_version`.

*   **sqlite3 (Biblioteca Padrão do Python)**
    *   **Finalidade:** Driver de conexão com o banco SQLite.
    *   **Onde é utilizada:** `services/db_service.py`.
    *   **Introduzido em:** V1. Mantido na V4.

---

### Utilitários e Bibliotecas Auxiliares (Standard Library)
*   **`python-dotenv` (>= 1.0.1):** Leitura de credenciais do arquivo `.env`. (V1)
*   **`asyncio`:** Execução assíncrona do edge-tts. (V2)
*   **`math` & `struct`:** Cálculo de volume RMS do áudio. (V2)
*   **`time`:** Temporizações de loop e controle de espera nos retries. (V2, expandido na V3)
*   **`pathlib` & `os`:** Gerenciamento de caminhos e criação de diretórios. (V1)
*   **`json` & `datetime`:** Parser de estruturas e manipulação de datas. (V1)
*   **`re` (Expressões Regulares):** Heurística rápida de respostas no `InventoryAssistant`. (V3)
*   **`threading`:** Gerenciamento de threads para stdin, microfone e varredura de estoque. **(Expandido na V4)**
*   **`queue`:** Event loop principal baseado em fila de comandos. **(NOVO na V4)**
*   **`io`:** Configuração de codificação UTF-8 dos fluxos stdin/stdout. **(NOVO na V4)**
*   **`uuid`:** Geração de identificadores únicos para documentos vetoriais. **(NOVO na V4)**
*   **`requests` (>= 2.31.0):** Declarado desde a V3. Na V4.1 passou a ser usado pela API do Claude (`claude_service.py`) e pelo bot do Telegram (`telegram_service.py`).
*   **`unittest`:** Suíte de testes em `tests/` (137 testes na V4.1). **(NOVO na V4)**
*   **`logging` e `contextvars`:** Registro de eventos em JSON com identificador de requisição. **(NOVO na V4.1)**
*   **`zipfile` e API de backup do `sqlite3`:** Cópia de segurança diária. **(NOVO na V4.1)**
*   **`ast`, `hashlib`:** Extração de fatos e índice incremental do ProjectAnalyzer. **(NOVO na V4)**

---

## 2. Tecnologias Adicionadas na V4

### Interface Desktop
*   **Electron (>= 31.0.0)**
    *   **Finalidade:** Framework para construção de aplicações desktop nativas com tecnologias web (HTML/CSS/JavaScript). Encapsula o back-end Python como processo filho e gerencia a comunicação IPC.
    *   **Onde é utilizada:** `main.js` (processo principal), `preload.js` (bridge seguro), `index.html` + `index.css` + `renderer.js` (processo renderer).
    *   **Módulos utilizados:** `BrowserWindow`, `ipcMain`, `ipcRenderer`, `contextBridge`.
    *   **Comunicação:** IPC bidirecional entre processos Electron e o back-end Python via JSON serializado em stdin/stdout.
    *   **Introduzido em:** **V4** (completamente novo).

*   **Node.js (Runtime do Electron)**
    *   **Finalidade:** Ambiente de execução JavaScript para o processo principal e preload do Electron.
    *   **Módulos nativos usados:** `path`, `child_process.spawn`.
    *   **Introduzido em:** **V4** (completamente novo).

---

### Banco Vetorial e Embeddings

*   **ChromaDB (>= 0.4.22)**
    *   **Finalidade:** Banco de dados vetorial embarcado para armazenamento e recuperação de vetores semânticos via similaridade de cosseno. Utiliza `PersistentClient` com persistência local em disco.
    *   **Onde é utilizada:** `services/vector/vector_store_service.py`. Dados persistidos em `core/database/chroma_db/`.
    *   **Coleção principal:** `assistente_domestico_memory`.
    *   **Espaço de similaridade:** Cosseno (`hnsw:space = cosine`).
    *   **Telemetria:** Desabilitada (`anonymized_telemetry=False`).
    *   **Introduzido em:** **V4** (completamente novo).

*   **Sentence-Transformers (>= 2.5.0)**
    *   **Finalidade:** Framework para geração de embeddings de sentenças. Utilizado pelo `EmbeddingService` para criar representações vetoriais densas de texto.
    *   **Modelo padrão:** `paraphrase-multilingual-MiniLM-L12-v2` — modelo multilíngue (incluindo pt-BR) de 384 dimensões, com 12 camadas de transformadores.
    *   **Onde é utilizada:** `services/vector/embedding_service.py`.
    *   **Dispositivo de execução:** **CPU exclusivamente**, preservando a VRAM/GPU para os modelos generativos do Ollama.
    *   **Introduzido em:** **V4** (completamente novo).

---

### Novos Componentes de Software (V4)

*   **`main.js` — Processo Principal Electron**
    *   **Finalidade:** Cria a janela desktop, inicia o back-end Python via `child_process.spawn`, parseia as mensagens JSON do stdout do Python, repassa via IPC para o renderer e implementa shutdown graceful com timeout de 2 segundos.

*   **`preload.js` — Bridge Seguro de IPC**
    *   **Finalidade:** Expõe `window.api` no `contextBridge` com métodos de envio (`sendText`, `toggleVoiceMode`, `toggleMute`) e listeners de recebimento (`onStateChanged`, `onAssistantMessage`, `onVoiceModeStatus`, etc.).

*   **`renderer.js` — Lógica da Interface Gráfica**
    *   **Finalidade:** Gerencia a interface do chat, renderiza mensagens do usuário e assistente, atualiza indicadores de estado, controla toggles de voz/mute e alimenta o terminal de debug.

*   **`services/vector/__init__.py` — Pacote Vetorial**
    *   **Finalidade:** Define o pacote `services.vector` e exporta os 5 serviços vetoriais.

*   **`services/vector/embedding_service.py` — Gerador de Embeddings na CPU**
    *   **Finalidade:** Carrega o modelo de embeddings como Singleton na CPU e expõe `gerar_embedding()` e `gerar_embeddings_em_lote()`.

*   **`services/vector/vector_store_service.py` — Wrapper ChromaDB**
    *   **Finalidade:** Abstração desacoplada sobre o `ChromaDB PersistentClient`, com operações de `upsert_documents()`, `search_similarity()`, `delete_documents()` e `count_documents()`.

*   **`services/vector/memory_service.py` — Gerenciador de Memória**
    *   **Finalidade:** Avalia o valor semântico de interações e persiste/recupera memórias de longo prazo no banco vetorial.

*   **`services/vector/semantic_search_service.py` — Busca Semântica Híbrida**
    *   **Finalidade:** Executa busca vetorial pura ou hidratada (ChromaDB + SQLite) para combinar representação semântica com valores financeiros exatos.

*   **`services/vector/context_retrieval_service.py` — Montador de Contexto RAG**
    *   **Finalidade:** Recupera memórias relevantes e gera um bloco de texto formatado para injeção dinâmica nos prompts da LLM.

*   **`scripts/migrate_vector_database.py` — Script de Migração**
    *   **Finalidade:** Migra idempotentemente o histórico de compras do SQLite para o ChromaDB.

*   **`scripts/rebuild_embeddings.py` — Script de Reconstrução**
    *   **Finalidade:** Recria todos os embeddings do zero. Desde 22/11/2026 faz uma cópia de segurança antes e preserva as memórias `mem_*` (P13).

*   **`scripts/validate_vector_database.py` — Suíte de Validação**
    *   **Finalidade:** Testes automatizados de busca semântica e busca híbrida.

*   **`scripts/inspect_vector_database.py` — Inspetor CLI**
    *   **Finalidade:** CLI interativa para visualizar registros no banco vetorial.

---

## 2.1. Tecnologias Adicionadas na V4.1

*   **GitHub Actions**
    *   **Finalidade:** Integração contínua: sintaxe Python e JavaScript, suíte completa e linter (`ruff`, informativo) a cada push na `V4` e a cada pull request.
    *   **Onde é utilizada:** `.github/workflows/testes.yml`, com as dependências mínimas em `requirements-ci.txt`.
    *   **Introduzido em:** **V4.1**.

*   **JSON Schema (saída estruturada do Ollama)**
    *   **Finalidade:** Restringir a resposta do modelo aos campos e valores permitidos, em vez de validar só depois.
    *   **Onde é utilizada:** `services/esquemas.py` e `core/skills/seletor.py` (decisão do orquestrador, com o nome das skills em `enum`), passado por `LocalLLMProvider.gerar_json(esquema=...)`. Requer `ollama>=0.4.0`.
    *   **Introduzido em:** **V4.1**.

*   **PyYAML (>= 6.0)**
    *   **Finalidade:** Ler o cabeçalho dos `SKILL.md` (contexto, privacidade, gatilhos, entradas e saídas).
    *   **Onde é utilizada:** `core/skills/catalogo.py`.
    *   **Introduzido em:** **V4.1** (SK1).

*   **Claude (Anthropic)**
    *   **Finalidade:** Agente principal de programação e analista das ideias de projetos.
    *   **Modo assinatura (padrão):** Claude Code CLI (`claude -p --output-format json`), logado no plano do usuário, sem chave de API. Roda sem ferramentas (`--tools ""`), sem MCP, numa pasta temporária e sem a `ANTHROPIC_API_KEY` no ambiente (`services/claude_assinatura_service.py`).
    *   **Modo API:** `POST https://api.anthropic.com/v1/messages` com `requests`, modelo `claude-sonnet-5-5`, limite mensal de gasto no `.env` (`services/claude_service.py`).
    *   **Introduzido em:** **V4.1** (SKP e SK8).

*   **Telegram Bot API**
    *   **Finalidade:** Receber ideias pelo celular e devolver a análise.
    *   **Onde é utilizada:** `services/telegram_service.py` (long polling com `getUpdates`, `sendMessage`), só com `requests`.
    *   **Introduzido em:** **V4.1** (SK8).

---

## 3. Status de Outras Categorias

*   **Interface Gráfica:** **Implementada na V4** via Electron com HTML/CSS/JavaScript e comunicação IPC bidirecional com o back-end Python.
*   **OCR / Visão Computacional:** **Não identificado nesta versão.**
*   **WebSocket / API REST Local:** **Não identificado nesta versão.** A comunicação entre Electron e Python utiliza stdin/stdout.
*   **Whisper Local (STT):** **Não identificado nesta versão.** A transcrição de voz ainda depende da API Google Speech Recognition (serviço web externo).
*   **Segunda LLM (Qwen2.5-Coder):** **Implementada parcialmente na V4.** A troca por comando e o retorno por inatividade funcionam; o botão no Electron e a troca por intenção não estão concluídos (ver documento 08). Na V4.1, a skill de programação usa o Qwen como reserva do Claude.
*   **LLM na nuvem:** Gemini (perguntas gerais) e, desde a V4.1, Claude (programação e ideias), cada um restrito pela política de privacidade das skills.
