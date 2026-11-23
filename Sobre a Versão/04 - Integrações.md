# 04 - Integrações

Este documento identifica e mapeia todos os fluxos de integração e conexões — externas, internas e com hardware — que o **Assistente Doméstico Inteligente** realiza para viabilizar suas funções, no estado da **V4.1 (atualizado em 23/11/2026)**. A V4.1 acrescentou o Claude (seção 2.D), o bot do Telegram (2.E) e as tabelas `compromissos` e `ideias`.

---

## 1. Comunicação com IA Local

### A. Ollama — Servidor Local de Inferência
*   **Tipo:** Comunicação com serviço local (processo separado na mesma máquina).
*   **Origem:** `services/llm_provider.py` - `LocalLLMProvider`, usado pelo orquestrador (`services/gemma_service.py`), pelos assistentes e pelo ProjectAnalyzer.
*   **Destino:** Servidor Ollama em execução local, acessível via `http://127.0.0.1:11434`.
*   **Finalidade:**
    1. **Escolha da skill (V4.1):** recebe a frase e o catálogo das skills e devolve `{skill, acao, dificuldade}`, restrito por JSON Schema.
    2. **Extração de Dados de Compras:** Recebe a transcrição completa de compras e retorna um JSON estruturado com estabelecimentos, itens, quantidades e valores.
    3. **Classificação de Inventário:** Recebe a resposta do usuário sobre estoque e retorna o tipo de intenção identificada (quando a heurística Regex não é suficiente).
    4. **Agenda e ideias (V4.1):** extrai título, data e hora de um compromisso e responde perguntas sobre uma ideia salva usando a análise guardada.
    5. **Programação sem Claude (V4.1):** o Qwen responde com trechos da biblioteca de contexto.
*   **Tecnologia:** SDK Python `ollama`, com cliente configurado para `timeout=120.0` segundos.
*   **Formato de envio:** Lista de mensagens `[{role, content}]` com JSON Schema no parâmetro `format` (V4.1; recai para `format="json"` com biblioteca antiga) e `options={"temperature": 0.1}`. Raciocínio desligado no orquestrador.
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

### D. Claude (Anthropic) — Programação e Ideias (V4.1)
*   **Tipo:** Processo local (Claude Code) que fala com a Anthropic, ou chamada HTTPS direta.
*   **Origem:** `services/claude_assinatura_service.py` (padrão, `CLAUDE_MODO=assinatura`) ou `services/claude_service.py` (`CLAUDE_MODO=api`).
*   **Finalidade:** Responder a skill `programacao` e analisar as ideias da skill `ideias`. Só essas skills recebem o serviço (`CLAUDE_SKILLS` e `privacidade: claude` no cabeçalho).
*   **Assinatura:**
    *   Executa `claude -p --output-format json --tools "" --disallowedTools mcp__* --no-session-persistence --model sonnet`.
    *   O prompt de sistema vai em arquivo temporário e a conversa pelo stdin.
    *   A chave de API é retirada do ambiente, então o gasto sai da cota do plano.
*   **API:** `POST https://api.anthropic.com/v1/messages`, cabeçalhos `x-api-key` e `anthropic-version`, modelo `claude-sonnet-5-5`, limite mensal em `CLAUDE_LIMITE_MENSAL_USD`.
*   **Contexto enviado:** o texto da ideia, ou a pergunta de programação com o histórico da sessão de programação e trechos da biblioteca (documentação do projeto). Compras, estoque e agenda nunca vão ao Claude.
*   **Indisponível** (sem login, sem cota, limite do plano): a programação usa o Qwen local; as ideias ficam na fila.

### E. Telegram Bot API — Ideias pelo Celular (V4.1)
*   **Tipo:** Comunicação externa via HTTPS.
*   **Origem:** `services/telegram_service.py`, iniciado pelo runtime quando `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_IDS` estão no `.env`.
*   **Destino:** `https://api.telegram.org/bot<token>/getUpdates` e `/sendMessage`.
*   **Finalidade:** Receber ideias, aceitar os comandos `/ideias`, `/ver N`, `/reanalisar N` e `/ideia texto`, e devolver a análise do Claude ao chat de origem.
*   **Segurança:**
    *   Só os chats listados são atendidos.
    *   É long polling: nenhuma porta do PC fica aberta.
    *   O token nunca vai aos logs.
    *   As mensagens passam pelos servidores do Telegram, sem criptografia de ponta a ponta para bots.
*   **Fora do ar:** com o assistente fechado, o Telegram guarda as mensagens por até 24 h.

---

## 3. Integração com Banco de Dados Local

### A. SQLite — Base Relacional
*   **Tipo:** Integração local (arquivo físico).
*   **Origem:** `services/db_service.py`.
*   **Destino:** `core/database/assistente_casa.db`.
*   **Finalidade:** Persistência de compras (`compras`, `itens_compra`), controle de inventário (`controle_consumo`) e, desde a V4.1, compromissos e ideias.
*   **Tecnologia:** Módulo nativo `sqlite3`.
*   **Controle de Versão de Schema:** `PRAGMA user_version` — atualmente na versão 2.
*   **Tabelas:**
    *   `compras`: id, data_compra, nome_comercio, total_gasto.
    *   `itens_compra`: id, compra_id (FK), produto, marca, quantidade, unidade, valor_unitario, valor_total, categoria, embalagem_quantidade, embalagem_unidade.
    *   `controle_consumo`: produto_nome (UNIQUE), categoria, tempo_medio_calculado, data_ultima_compra, quantidade_comprada, quantidade_residual_confirmada, status_estoque, validacao_pendente, ultima_qtd_comprada, quantidade_residual_esgotada. Ainda não é preenchida pelo fluxo de compras.
    *   `historico_conversas`: id, session_id, papel, conteudo, timestamp. Criada, mas sem uso.
    *   `compromissos` (V4.1, criada pela skill `agenda`): id, titulo, data, hora, criado_em.
    *   `ideias` (V4.1, criada pelo `IdeiasService`): id, titulo, texto, origem (`chat` ou `telegram:<chat>`), criado_em, situacao (`pendente`, `analisando`, `analisada`), analise, analisado_em, motivo.

### B. ChromaDB — Base Vetorial (NOVO na V4)
*   **Tipo:** Integração local (biblioteca embarcada com persistência em disco).
*   **Origem:** `services/vector/vector_store_service.py`.
*   **Destino:** `core/database/chroma_db/`, coleções `assistente_domestico_memory` e, desde a V4.1, `biblioteca_projeto`.
*   **Finalidade:** Armazenar itens de compra vetorizados, memórias de longo prazo e trechos da documentação e das análises de ideias (biblioteca de contexto).
*   **Tecnologia:** `chromadb.PersistentClient`, similaridade por cosseno e telemetria desativada.
*   **Embeddings:** `sentence-transformers` na CPU, com o modelo `paraphrase-multilingual-MiniLM-L12-v2`. O download ocorre no primeiro uso; depois, o modelo fica em cache local.

---

## 4. Comunicação Interna entre Componentes

```text
[Electron: renderer.js ↔ preload.js ↔ main.js]
   └── JSON por stdin/stdout
[app/main.py: AssistenteRuntime]
   ├── → intent_router (gatilhos das skills) → senão gemma_service.orquestrar_requisicao()
   │       └── LocalLLMProvider.gerar_json() → Ollama Local
   ├── → core.skills.motor.executar(skill) → skills/<nome>/roteiro.py
   │       ├── agenda → DatabaseService (compromissos) + llm_local
   │       ├── ideias → IdeiasService (ideias) + llm_local
   │       └── programacao → Claude (assinatura/API) ou Qwen + BibliotecaService
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
   ├── → inventory_assistant.verificar_itens_expirados_inicializacao() [thread]
   │       → SQLite
   ├── → IdeiasService (fila) [thread] → Claude → SQLite + Ideias/*.md → BibliotecaService → ChromaDB
   └── → TelegramService [thread] → Telegram Bot API ⇄ IdeiasService
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
*   **Variáveis:** `GEMINI_API_KEY`, `CLAUDE_MODO`, `CLAUDE_MODELO_ASSINATURA`, `CLAUDE_ASSINATURA_RETESTE_MIN`, `ANTHROPIC_API_KEY`, `CLAUDE_MODELO`, `CLAUDE_LIMITE_MENSAL_USD`, `CLAUDE_HORA_RETESTE`, `CLAUDE_SKILLS`, `IDEIAS_DIR`, `IDEIAS_RETESTE_MIN`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_IDS`, `EMBEDDING_MODEL_NAME`, `EMBEDDING_DEVICE`, `OLLAMA_SAIDA_ESTRUTURADA`, `OLLAMA_RACIOCINIO`, `PROJECT_ANALYZER_OUTPUT_DIR`, `PROJECT_ANALYZER_MODEL`, `AUDIO_SAMPLE_RATE`, `AUDIO_CHANNELS`, `AUDIO_CHUNK_SIZE`, `AUDIO_RECORD_SECONDS`, `LOGS_DIR`, `LOG_CONTEUDO`, `LOG_RETENCAO_DIAS`, `BACKUP_ATIVO`, `BACKUP_DIR`, `BACKUP_DIARIOS`, `BACKUP_SEMANAIS`.
*   **Observação:** O arquivo é opcional quando as variáveis já estão definidas no sistema.

### C. Arquivos Temporários de Voz
*   **Origem:** `services/voice_service.py`.
*   **Destino:** `assets/temp_voice.mp3` — criado e excluído automaticamente a cada síntese de voz.

### C.1. Análises de Ideias (V4.1)
*   **Origem:** `services/ideias_service.py`.
*   **Destino:** `Ideias/ideia-NNNN-<titulo>.md` (ou `IDEIAS_DIR`), fora do Git. Cada arquivo traz a ideia original e a análise; entra na biblioteca de contexto e pode ser anexado a um Projeto no app do Claude.

### D. Documentação Gerada pelo ProjectAnalyzer (NOVO na V4)
*   **Origem:** `services/project_analyzer/doc_writer.py`.
*   **Destino:** `PROJECT_ANALYZER_OUTPUT_DIR`, por padrão `E:\Agente IA\Documentacao_Gerada`.

---

## 7. Subprocessos e IPC (NOVO na V4)

*   **Origem:** `main.js`, com `spawn('python', ['-u', 'app/main.py'])`.
*   **Requisito:** O comando `python` deve estar no `PATH`.
*   **Encerramento:** O Electron envia `shutdown` e encerra o processo Python após 2 segundos, se necessário.
*   **Claude Code (V4.1):** no modo assinatura, o back-end inicia `claude.exe` (do `PATH` ou de `%USERPROFILE%\.local\bin`) como subprocesso a cada análise ou pergunta de programação, com timeout de `CLAUDE_ASSINATURA_TIMEOUT` (300 s).

---

## 8. Categorias Não Identificadas na V4

*   **APIs REST Locais / Servidores HTTP:** Não identificado.
*   **WebSocket:** Não identificado.
*   **OCR / Visão Computacional:** Não identificado.
*   **STT Local (Whisper):** Não identificado. A transcrição de voz utiliza API externa Google.
