# 02 - Tecnologias Utilizadas

Este documento detalha o ecossistema tecnológico empregado na **Versão 3 (V3)** do **Assistente Doméstico Inteligente**, registrando as tecnologias herdadas da V2.1 e as novas tecnologias incorporadas nesta versão.

---

## 1. Tecnologias Herdadas da V2.1 (Mantidas na V3)

### Linguagem Principal
*   **Python (v3.10+)**
    *   **Finalidade:** Linguagem de desenvolvimento de todo o sistema.
    *   **Onde é utilizada:** Em todos os scripts do projeto.
    *   **Introduzido em:** V1.

---

### Inteligência Artificial na Nuvem (Fallback)
*   **Google Gemini API (Modelo `gemini-2.5-flash`)**
    *   **Finalidade na V3:** Atua exclusivamente como **fallback de contingência** quando o LLM local falha persistentemente. Na V2.1, era a fonte primária de processamento de compras e classificação de intenções; na V3, passou a ser a camada secundária.
    *   **Onde é utilizada:** Em `services/ai_service.py` e, indiretamente, via `CloudLLMProvider` em `services/llm_provider.py`.
    *   **Introduzido em:** V1. **Papel alterado na V3** (de primário para fallback).

*   **SDK `google-genai` (>= 0.8.0)**
    *   **Finalidade:** Biblioteca cliente para comunicação com os endpoints Gemini da Google Cloud.
    *   **Onde é utilizada:** Em `services/ai_service.py`.
    *   **Introduzido em:** V1. Mantido na V3.

> [!NOTE]
> Na V3, o método `processar_requisicao_complexa` em `ai_service.py` contém uma referência a `self.gemini_client` que não foi completamente implementada, causando falha no fallback de nuvem. Isso representa uma dívida técnica identificada no código analisado.

---

### Processamento e Síntese de Áudio
*   **SpeechRecognition (>= 3.10.0)**
    *   **Finalidade:** Captura do buffer analógico do microfone e calibração de ruído ambiente.
    *   **Onde é utilizada:** `services/audio_service.py`.
    *   **Introduzido em:** V1. Mantido na V3.

*   **PyAudio (>= 0.2.14)**
    *   **Finalidade:** Bindings de baixo nível do sistema operacional para leitura do fluxo do microfone.
    *   **Onde é utilizada:** Indiretamente pelo `SpeechRecognition` em `services/audio_service.py`.
    *   **Introduzido em:** V1. Mantido na V3.

*   **edge-tts**
    *   **Finalidade:** Geração de fala (Text-to-Speech) utilizando os modelos neurais da Microsoft Edge.
    *   **Onde é utilizada:** `services/voice_service.py`.
    *   **Introduzido em:** V2. Mantido na V3.

*   **pygame (Módulo `pygame.mixer`)**
    *   **Finalidade:** Reprodução local dos arquivos de voz neural gerados pelo edge-tts.
    *   **Onde é utilizada:** `services/voice_service.py`.
    *   **Introduzido em:** V2. Mantido na V3.

*   **winsound (Biblioteca Padrão do Windows)**
    *   **Finalidade:** Emissão de bips sonoros de status do microfone.
    *   **Onde é utilizada:** `services/audio_service.py`.
    *   **Introduzido em:** V2. Mantido na V3.

---

### Banco de Dados e Persistência
*   **SQLite**
    *   **Finalidade:** Banco de dados relacional embarcado para persistência de compras, itens e controle de inventário.
    *   **Onde é utilizada:** Arquivo físico em `core/database/assistente_casa.db`.
    *   **Introduzido em:** V1. Mantido na V3 com suporte a migrações por `PRAGMA user_version`.

*   **sqlite3 (Biblioteca Padrão do Python)**
    *   **Finalidade:** Driver de conexão com o banco SQLite.
    *   **Onde é utilizada:** `services/db_service.py`.
    *   **Introduzido em:** V1. Mantido na V3.

---

### Utilitários e Bibliotecas Auxiliares (Standard Library)
*   **`python-dotenv` (>= 1.0.1):** Leitura de credenciais do arquivo `.env`. (V1)
*   **`asyncio`:** Execução assíncrona do edge-tts. (V2)
*   **`math` & `struct`:** Cálculo de volume RMS do áudio para corte por silêncio. (V2)
*   **`time`:** Temporizações de loop e controle de espera nos retries. (V2, expandido na V3)
*   **`pathlib` & `os`:** Gerenciamento de caminhos e criação de diretórios. (V1)
*   **`json` & `datetime`:** Parser de estruturas e manipulação de datas. (V1)
*   **`re` (Módulo de Expressões Regulares):** Análise heurística rápida de respostas do usuário no `InventoryAssistant`. **(NOVO na V3)**

---

## 2. Tecnologias Adicionadas na V3

### LLM Local
*   **Ollama**
    *   **Finalidade:** Servidor local de inferência de modelos de linguagem. Expõe uma API HTTP local (padrão em `http://127.0.0.1:11434`) que recebe prompts e retorna respostas dos modelos carregados.
    *   **Onde é utilizada:** Chamado diretamente pelo `gemma_service.py` (para orquestração) e indiretamente pelo `LocalLLMProvider` em `llm_provider.py` (para extração de compras e classificação de inventário).
    *   **Como se comunica:** O SDK Python do Ollama (`import ollama`) faz requisições HTTP ao servidor local. A partir da V3, todas as chamadas utilizam `ollama.Client(timeout=120.0)` para tolerar o tempo de inferência do modelo local (que pode atingir 40+ segundos em hardware sem GPU dedicada).

*   **Modelo Gemma 4 e:4b (`gemma4:e4b`)**
    *   **Finalidade:** LLM local de 4 bilhões de parâmetros, rodando via Ollama na máquina do usuário. Atua em dois papéis na V3:
        1.  **Orquestrador de Intenções:** Classifica a solicitação de voz do usuário (arquivo `gemma_service.py`) retornando um JSON com `dificuldade`, `contexto`, `acao` e `mudanca_de_contexto`.
        2.  **Extrator de Dados de Compras:** Converte a transcrição de voz de compras em JSON estruturado por estabelecimento (via `LocalLLMProvider` no `ShoppingAssistant`).
        3.  **Classificador de Intenções de Inventário:** Analisa respostas do usuário sobre o estoque (via `LocalLLMProvider` no `InventoryAssistant`), como segundo nível após a heurística Regex falhar.
    *   **Formato de comunicação:** JSON estruturado via parâmetro `format="json"` do Ollama SDK.
    *   **Introduzido em:** **V3** (completamente novo).

*   **SDK Python `ollama`**
    *   **Finalidade:** Biblioteca cliente Python que abstrai as chamadas HTTP ao servidor Ollama local.
    *   **Onde é utilizada:** Diretamente em `services/gemma_service.py` e `services/llm_provider.py`.
    *   **Introduzido em:** **V3** (completamente novo).

---

### Novos Componentes de Software (V3)

*   **`services/llm_provider.py` — Camada de Abstração de LLM**
    *   **Finalidade:** Define a interface abstrata `BaseLLMProvider` com contratos `gerar_texto()` e `gerar_json()`, garantindo intercambiabilidade entre provedores de IA (local ou nuvem). Implementa `LocalLLMProvider` (Ollama) e `CloudLLMProvider` (Gemini).
    *   **Padrão de design:** Strategy Pattern para múltiplos provedores de LLM.

*   **`services/gemma_service.py` — Serviço de Orquestração Local**
    *   **Finalidade:** Módulo dedicado às chamadas de orquestração ao Gemma via Ollama. Inclui sanitização de resposta JSON, validação rigorosa de schema (`_validar_schema_orquestrador`) e fallback para execução de assistente local (`executar_assistente_local`).

*   **`services/resilience_service.py` — Serviço de Resiliência**
    *   **Finalidade:** Implementa o padrão Retry de forma centralizada e parametrizável via `execute_with_retry`. Suporta callbacks de validação, avisos de voz em reprocessamento, exceções específicas recuperáveis e limites de tentativas configuráveis. Na V3, toda chamada a LLM ou assistente especializado passa por este módulo.

---

## 3. Status de Outras Categorias

*   **Interface Gráfica:** **Não identificada nesta versão.** O sistema continua operando exclusivamente via linha de comando e interação por voz.
*   **OCR / Visão Computacional:** **Não identificado nesta versão.**
*   **WebSocket / API REST Local:** **Não identificado nesta versão.**
*   **Whisper Local (STT):** **Não identificado nesta versão.** A transcrição de voz ainda depende da API Google Speech Recognition (serviço web externo).
