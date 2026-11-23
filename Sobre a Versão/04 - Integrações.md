# 04 - Integrações

Este documento identifica e mapeia todos os fluxos de integração e conexões — externas, internas e com hardware — que o **Assistente Doméstico Inteligente (V4)** realiza para viabilizar suas funções.

---

## 1. Comunicação com IA Local

### A. Ollama — Servidor Local de Inferência
*   **Tipo:** Comunicação com serviço local (processo separado na mesma máquina).
*   **Origem:** `services/llm_provider.py` - `LocalLLMProvider`, usado pelo orquestrador (`services/gemma_service.py`), pelos assistentes e pelo ProjectAnalyzer.
*   **Destino:** Servidor Ollama em execução local, acessível via `http://127.0.0.1:11434`.
*   **Finalidade:**
    1. **Orquestração de Intenções:** Recebe a transcrição de voz do usuário e retorna um JSON classificando a dificuldade, contexto, ação e mudança de contexto da solicitação.
    2. **Extração de Dados de Compras:** Recebe a transcrição completa de compras e retorna um JSON estruturado com estabelecimentos, itens, quantidades e valores.
    3. **Classificação de Inventário:** Recebe a resposta do usuário sobre estoque e retorna o tipo de intenção identificada (quando a heurística Regex não é suficiente).
*   **Tecnologia:** SDK Python `ollama`, com cliente configurado para `timeout=120.0` segundos.
*   **Formato de envio:** Lista de mensagens `[{role, content}]` com parâmetro `format="json"` e `options={"temperature": 0.1}`.
*   **Formato de retorno:** Dicionário JSON Python parseado via `json.loads()`.
*   **Modelos utilizados:** `gemma4:e4b` (padrão) e `qwen2.5-coder:7b` (Modo Qwen e ProjectAnalyzer). A troca libera a VRAM com `keep_alive=0`.

---

## 2. APIs e Serviços Web Externos (SaaS)

### A. Google Gemini API — Fallback de Nuvem
*   **Tipo:** Comunicação externa via HTTPS.
*   **Origem:** `services/ai_service.py` e indiretamente via `CloudLLMProvider` em `services/llm_provider.py`.
*   **Destino:** Servidores de LLM da Google Cloud (modelo `gemini-2.5-flash`).
*   **Finalidade na V4:** Atende somente perguntas gerais (`geral` e `outro`), fora do Modo Qwen, quando o LLM local falha ou a orquestração as classifica como `medio_dificil`. Compras, estoque, agenda, programação e documentação nunca usam a nuvem. Se o orquestrador falhar, a frase também não é enviada.
*   **Tecnologia:** Biblioteca `google-genai`, requisições HTTPS. A API Key vem da variável de ambiente `GEMINI_API_KEY`, definida no sistema ou no arquivo `.env`, e é opcional: sem ela, todo o processamento fica local.
*   **Contexto enviado:** Além do texto do usuário, podem ser enviados o histórico e as memórias semânticas apenas de `geral` e `outro`.
*   **Formato de envio:** Prompt textual com instrução de sistema e mensagem do usuário.
*   **Formato de retorno:** Texto puro ou JSON parseado via `response_mime_type="application/json"`.

### B. Google Speech Recognition API — Transcrição de Fala
*   **Tipo:** Comunicação externa via HTTP.
*   **Origem:** `services/audio_service.py`.
*   **Destino:** API pública de Reconhecimento de Voz do Google.
*   **Finalidade:** Converter os buffers de áudio capturados pelo microfone em texto bruto (`recognize_google(audio_objeto, language="pt-BR")`).
*   **Tecnologia:** Biblioteca `speech_recognition`, chamada síncrona HTTP.
*   **Formato de envio:** Objeto `sr.AudioData` (buffer PCM bruto do microfone).
*   **Formato de retorno:** String de texto transcrita.
*   **Momento:** Em toda captura de áudio (tanto para novos comandos quanto para respostas de inventário).

### C. Microsoft Edge TTS API — Síntese de Voz
*   **Tipo:** Comunicação externa via conexão web assíncrona.
*   **Origem:** `services/voice_service.py`.
*   **Destino:** Servidores de Voz Neural Microsoft Edge.
*   **Finalidade:** Gerar o arquivo de áudio MP3 sintetizado com a voz `pt-BR-AntonioNeural`.
*   **Tecnologia:** Biblioteca assíncrona `edge_tts`, executada via `asyncio.run()`.
*   **Formato de envio:** String de texto.
*   **Formato de retorno:** Arquivo MP3 salvo em `assets/temp_voice.mp3`.
*   **Momento:** A cada chamada `VoiceService.falar(texto)`.

---

## 3. Integração com Banco de Dados Local

### A. SQLite — Base Relacional
*   **Tipo:** Integração local (arquivo físico).
*   **Origem:** `services/db_service.py`.
*   **Destino:** `core/database/assistente_casa.db`.
*   **Finalidade:** Persistência de compras (`compras`, `itens_compra`) e controle de inventário (`controle_consumo`).
*   **Tecnologia:** Módulo nativo `sqlite3`.
*   **Controle de Versão de Schema:** `PRAGMA user_version` — atualmente na versão 2.
*   **Tabelas:**
    *   `compras`: id, data_compra, nome_comercio, total_gasto.
    *   `itens_compra`: id, compra_id (FK), produto, marca, quantidade, unidade, valor_unitario, valor_total, categoria, embalagem_quantidade, embalagem_unidade.
    *   `controle_consumo`: produto_nome (UNIQUE), categoria, tempo_medio_calculado, data_ultima_compra, quantidade_comprada, quantidade_residual_confirmada, status_estoque, validacao_pendente, ultima_qtd_comprada, quantidade_residual_esgotada. Ainda não é preenchida pelo fluxo de compras.
    *   `historico_conversas`: id, session_id, papel, conteudo, timestamp. Criada, mas sem uso.

### B. ChromaDB — Base Vetorial (NOVO na V4)
*   **Tipo:** Integração local (biblioteca embarcada com persistência em disco).
*   **Origem:** `services/vector/vector_store_service.py`.
*   **Destino:** `core/database/chroma_db/`, coleção `assistente_domestico_memory`.
*   **Finalidade:** Armazenar itens de compra vetorizados e memórias de longo prazo.
*   **Tecnologia:** `chromadb.PersistentClient`, similaridade por cosseno e telemetria desativada.
*   **Embeddings:** `sentence-transformers` na CPU, com o modelo `paraphrase-multilingual-MiniLM-L12-v2`. O download ocorre no primeiro uso; depois, o modelo fica em cache local.

---

## 4. Comunicação Interna entre Componentes

```text
[Electron: renderer.js ↔ preload.js ↔ main.js]
   └── JSON por stdin/stdout
[app/main.py: AssistenteRuntime]
   ├── → gemma_service.orquestrar_requisicao()
   │       ├── Regras: Qwen, ProjectAnalyzer e intent_router
   │       └── LocalLLMProvider.gerar_json() → Ollama Local
   ├── → execute_with_retry(shopping_assistant.preparar_compra)
   │       → LocalLLMProvider.gerar_json() → Ollama Local
   ├── → shopping_assistant.registrar_compras() [uma vez, após confirmar se houver dúvida]
   │       → DatabaseService.salvar_compras_da_ia() → SQLite
   │       → VectorStoreService.upsert_documents() → ChromaDB
   ├── → inventory_assistant.consultar_estoque() → SQLite
   ├── → executar_assistente_local()
   │       → ContextRetrievalService → ChromaDB
   │       → LocalLLMProvider.gerar_texto() → Ollama Local
   ├── → execute_with_retry(ai_service.processar_requisicao_complexa) [só geral/outro]
   │       → Google Gemini API (nuvem)
   ├── → ProjectAnalyzer.analisar() → Ollama Local + pasta de saída
   ├── → MemoryService.salvar_memoria_longo_prazo() → ChromaDB
   └── → inventory_assistant.verificar_itens_expirados_inicializacao() [thread]
           → SQLite
```

### Protocolo Electron ↔ Python (NOVO na V4)

| Direção | Tipos de mensagem |
| :--- | :--- |
| Electron → Python | `send_text`, `toggle_voice_mode`, `toggle_mute`, `shutdown` |
| Python → Electron | `state_changed`, `user_message`, `assistant_message`, `voice_mode_status`, `debug_log`, `error`, `system_ready` |

O `main.js` converte os nomes de `snake_case` para `kebab-case` ao repassá-los ao renderer. Linhas do stdout que não sejam JSON são tratadas como log.

---

## 5. Integração com Hardware

### A. Microfone (Entrada de Áudio)
*   **Origem:** `services/audio_service.py`.
*   **Tecnologia:** `PyAudio` vinculado ao sistema operacional Windows.
*   **Momento:** Em toda captura de voz do usuário.

### B. Alto-falantes (Saída de Áudio)
*   **Origem:** `services/voice_service.py`.
*   **Tecnologia:** `pygame.mixer`.
*   **Momento:** A cada chamada `VoiceService.falar()`.

### C. Bips do Sistema (Feedback Sonoro)
*   **Origem:** `services/audio_service.py`.
*   **Tecnologia:** `winsound.Beep()`.
*   **Momento:** Início de gravação (800Hz), aviso de tempo próximo (600Hz × 2), fim de gravação (440Hz).

---

## 6. Integração com Sistema de Arquivos

### A. Logs Persistentes
*   **Origem:** Todos os módulos de serviço via `logger_service.py`.
*   **Destino:** `Logs/eventos-AAAA-MM-DD.jsonl`, uma linha JSON por evento com o módulo no campo `componente` (até 21/11/2026: `Logs/{nome_modulo}/log.txt`).
*   **Retenção:** arquivos com mais de `LOG_RETENCAO_DIAS` (30) são apagados.

### A.1. Cópias de Segurança
*   **Origem:** `services/backup_service.py`, iniciado pelo runtime.
*   **Destino:** `core/database/backups/auto/AAAA-MM-DD/` (`assistente_casa.db`, `chroma_db.zip`, `manifesto.json`).

### B. Arquivo de Configuração (`.env`)
*   **Origem:** `core/config.py` via `python-dotenv`.
*   **Variáveis:** `GEMINI_API_KEY`, `EMBEDDING_MODEL_NAME`, `PROJECT_ANALYZER_OUTPUT_DIR`, `PROJECT_ANALYZER_MODEL`, `AUDIO_SAMPLE_RATE`, `AUDIO_CHANNELS`, `AUDIO_CHUNK_SIZE`, `AUDIO_RECORD_SECONDS`, `LOGS_DIR`, `LOG_CONTEUDO`, `LOG_RETENCAO_DIAS`, `BACKUP_ATIVO`, `BACKUP_DIR`, `BACKUP_DIARIOS`, `BACKUP_SEMANAIS`.
*   **Observação:** O arquivo é opcional quando as variáveis já estão definidas no sistema.

### C. Arquivos Temporários de Voz
*   **Origem:** `services/voice_service.py`.
*   **Destino:** `assets/temp_voice.mp3` — criado e excluído automaticamente a cada síntese de voz.

### D. Documentação Gerada pelo ProjectAnalyzer (NOVO na V4)
*   **Origem:** `services/project_analyzer/doc_writer.py`.
*   **Destino:** `PROJECT_ANALYZER_OUTPUT_DIR`, por padrão `E:\Agente IA\Documentacao_Gerada`.

---

## 7. Subprocessos e IPC (NOVO na V4)

*   **Origem:** `main.js`, com `spawn('python', ['-u', 'app/main.py'])`.
*   **Requisito:** O comando `python` deve estar no `PATH`.
*   **Encerramento:** O Electron envia `shutdown` e encerra o processo Python após 2 segundos, se necessário.

---

## 8. Categorias Não Identificadas na V4

*   **APIs REST Locais / Servidores HTTP:** Não identificado.
*   **WebSocket:** Não identificado.
*   **OCR / Visão Computacional:** Não identificado.
*   **STT Local (Whisper):** Não identificado. A transcrição de voz utiliza API externa Google.
