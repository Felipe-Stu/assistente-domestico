# 04 - Integrações

Este documento identifica e mapeia todos os fluxos de integração e conexões — externas, internas e com hardware — que o **Assistente Doméstico Inteligente (V3)** realiza para viabilizar suas funções.

---

## 1. Comunicação com IA Local (NOVO na V3)

### A. Ollama — Servidor Local de Inferência
*   **Tipo:** Comunicação com serviço local (processo separado na mesma máquina).
*   **Origem:** `services/gemma_service.py` (orquestração) e `services/llm_provider.py` - `LocalLLMProvider` (extração de dados e classificação de inventário).
*   **Destino:** Servidor Ollama em execução local, acessível via `http://127.0.0.1:11434`.
*   **Finalidade:**
    1. **Orquestração de Intenções:** Recebe a transcrição de voz do usuário e retorna um JSON classificando a dificuldade, contexto, ação e mudança de contexto da solicitação.
    2. **Extração de Dados de Compras:** Recebe a transcrição completa de compras e retorna um JSON estruturado com estabelecimentos, itens, quantidades e valores.
    3. **Classificação de Inventário:** Recebe a resposta do usuário sobre estoque e retorna o tipo de intenção identificada (quando a heurística Regex não é suficiente).
*   **Tecnologia:** SDK Python `ollama`, com cliente configurado para `timeout=120.0` segundos.
*   **Formato de envio:** Lista de mensagens `[{role, content}]` com parâmetro `format="json"` e `options={"temperature": 0.1}`.
*   **Formato de retorno:** Dicionário JSON Python parseado via `json.loads()`.
*   **Modelo utilizado:** `gemma4:e4b` (Gemma 4 e:4b, quantizado).

---

## 2. APIs e Serviços Web Externos (SaaS)

### A. Google Gemini API — Fallback de Nuvem
*   **Tipo:** Comunicação externa via HTTPS.
*   **Origem:** `services/ai_service.py` e indiretamente via `CloudLLMProvider` em `services/llm_provider.py`.
*   **Destino:** Servidores de LLM da Google Cloud (modelo `gemini-2.5-flash`).
*   **Finalidade na V3:** Atua exclusivamente como **camada de contingência**. É acionada apenas quando o LLM local (Gemma/Ollama) falha após esgotar todas as tentativas de retry, ou quando a orquestração classifica a solicitação como `medio_dificil`.
*   **Tecnologia:** Biblioteca `google-genai`, requisições HTTPS. A API Key é lida do arquivo `.env` via `python-dotenv`.
*   **Formato de envio:** Prompt textual com instrução de sistema e mensagem do usuário.
*   **Formato de retorno:** Texto puro ou JSON parseado via `response_mime_type="application/json"`.

> [!WARNING]
> O método `processar_requisicao_complexa` em `ai_service.py` (L.115-128) contém uma referência a `self.gemini_client` que não foi implementada corretamente. Isso causa falha no fallback de nuvem e está documentado como dívida técnica no código da V3.

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
*   **Controle de Versão de Schema:** `PRAGMA user_version` — atualmente na versão 1.
*   **Tabelas:**
    *   `compras`: id, data_compra, nome_comercio, total_gasto.
    *   `itens_compra`: id, compra_id (FK), produto, marca, quantidade, unidade, valor_unitario, valor_total, categoria.
    *   `controle_consumo`: produto_nome (UNIQUE), categoria, tempo_medio_calculado, data_ultima_compra, quantidade_comprada, quantidade_residual_confirmada, status_estoque, validacao_pendente, ultima_qtd_comprada, quantidade_residual_esgotada.

---

## 4. Comunicação Interna entre Componentes

```text
[main.py]
   ├── → gemma_service.orquestrar_requisicao()
   │       → Ollama Local (Gemma 4)
   ├── → execute_with_retry(shopping_assistant.processar_texto_compra)
   │       → LocalLLMProvider.gerar_json()
   │           → Ollama Local (Gemma 4)
   │       → DatabaseService.salvar_compra_da_ia()
   │           → SQLite
   ├── → execute_with_retry(ai_service.processar_requisicao_complexa) [fallback]
   │       → Google Gemini API (nuvem)
   └── → inventory_assistant.verificar_itens_expirados_inicializacao()
           → VoiceService.falar()
               → Microsoft Edge TTS (externo)
               → pygame.mixer (hardware)
           → AudioService.capturar_audio_e_transcrever()
               → Google Speech Recognition (externo)
           → _heuristica_rapida() [Regex interno]
           → LocalLLMProvider.gerar_json() [se heurística falhar]
               → Ollama Local (Gemma 4)
           → DatabaseService.executar_comando()
               → SQLite
```

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
*   **Destino:** `Logs/{nome_modulo}/log.txt`.

### B. Arquivo de Configuração (`.env`)
*   **Origem:** `core/config.py` via `python-dotenv`.
*   **Variáveis:** `GEMINI_API_KEY`, `AUDIO_SAMPLE_RATE`, `AUDIO_CHANNELS`, `AUDIO_CHUNK_SIZE`, `AUDIO_RECORD_SECONDS`.

### C. Arquivos Temporários de Voz
*   **Origem:** `services/voice_service.py`.
*   **Destino:** `assets/temp_voice.mp3` — criado e excluído automaticamente a cada síntese de voz.

---

## 7. Categorias Não Identificadas na V3

*   **APIs REST Locais / Servidores HTTP:** Não identificado. O sistema roda via linha de comando.
*   **WebSocket:** Não identificado.
*   **Subprocessos / IPC:** Não identificado. Todas as integrações operam sob o mesmo processo Python.
*   **OCR / Visão Computacional:** Não identificado.
*   **STT Local (Whisper):** Não identificado. A transcrição de voz utiliza API externa Google.
