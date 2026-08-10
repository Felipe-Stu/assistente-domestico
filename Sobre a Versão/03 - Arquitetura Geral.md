# 03 - Arquitetura Geral

Este documento detalha a estrutura de diretórios, os módulos constituintes, suas responsabilidades, o fluxo principal e as relações de dependência na **Versão 3 (V3)** do **Assistente Doméstico Inteligente**.

> [!IMPORTANT]
> A V3 representa uma expansão arquitetural em relação à V2.1. Foram adicionados três novos módulos de serviço (`gemma_service.py`, `llm_provider.py`, `resilience_service.py`) e uma nova camada de abstração de LLM, alterando o fluxo de processamento de IA do sistema.

---

## 1. Organização das Pastas (Estrutura de Diretórios)

```text
assistente-domestico/
├── assets/                      # Armazenamento temporário de arquivos de voz (temp_voice.mp3)
├── app/
│   └── main.py                  # Orquestrador principal, sessão de contexto e roteamento de fluxo
├── core/
│   ├── database/
│   │   └── assistente_casa.db   # Banco de dados SQLite (compras, itens, controle_consumo)
│   ├── __init__.py
│   └── config.py                # Configurações globais, variáveis de ambiente e caminhos
├── Logs/                        # Logs persistentes em disco (gerados automaticamente)
│   ├── main/
│   │   └── main_log.txt         # Log geral da orquestração do sistema
│   ├── ai_service/
│   │   └── log.txt
│   ├── audio_service/
│   │   └── log.txt
│   ├── db_service/
│   │   └── log.txt
│   ├── inventory_assistant/
│   │   └── log.txt
│   ├── shopping_assistant/
│   │   └── log.txt
│   └── voice_service/
│       └── log.txt
├── services/
│   ├── __init__.py
│   ├── ai_service.py            # Interface com a API Gemini (nuvem) - fallback
│   ├── audio_service.py         # Captura de microfone com monitoramento RMS e bips
│   ├── db_service.py            # Persistência SQLite com suporte a migrações de schema
│   ├── gemma_service.py         # [NOVO V3] Orquestrador local via Ollama/Gemma 3 4B
│   ├── inventory_assistant.py   # Controle preditivo de estoque com heurística + Gemma local
│   ├── llm_provider.py          # [NOVO V3] Abstração de provedores LLM (Local/Nuvem)
│   ├── logger_service.py        # CustomLogger transversal com logs segmentados por módulo
│   ├── resilience_service.py    # [NOVO V3] Serviço de retry centralizado e parametrizável
│   ├── shopping_assistant.py    # Processamento de compras via LLM local e persistência
│   └── voice_service.py         # Síntese de voz neural (Edge TTS) e reprodução (pygame)
├── Sobre a Versão/              # Documentação técnica da versão atual
├── .env                         # Variáveis de ambiente (GEMINI_API_KEY)
├── requirements.txt             # Dependências do projeto
└── README.md                    # Documentação de alto nível
```

---

## 2. Descrição dos Módulos e Suas Responsabilidades

### A. Orquestrador (`app/main.py`)
**Responsabilidade:** Ponto de entrada do sistema. Inicializa todos os serviços e assistentes via injeção de dependências. Gerencia a `GerenciadorDeSessao` para manter o contexto e histórico da conversa. Implementa a função `processar_solicitacao` que representa o ciclo principal de execução: chama o `gemma_service.orquestrar_requisicao` via `execute_with_retry`, interpreta a decisão de dificuldade/contexto e roteia o fluxo para o assistente especializado correspondente. Define constantes `TEMPO_RETRY = 3.0` e `MAX_TENTATIVAS = 3`.

### B. Serviço de Orquestração Local (`services/gemma_service.py`) — NOVO na V3
**Responsabilidade:** Encapsula as chamadas diretas ao modelo Gemma 4 e:4b via Ollama para orquestração de intenções. Fornece `orquestrar_requisicao()` que envia a transcrição do usuário ao Gemma e retorna um dicionário classificado com `dificuldade`, `mudanca_de_contexto`, `contexto` e `acao`. Valida o schema de saída via `_validar_schema_orquestrador()` e sanitiza o JSON via `_sanitizar_resposta_json()`. Também fornece `executar_assistente_local()` para execuções genéricas de contextos como agenda. Todas as chamadas ao Ollama utilizam `ollama.Client(timeout=120.0)`.

### C. Camada de Abstração LLM (`services/llm_provider.py`) — NOVO na V3
**Responsabilidade:** Define a interface abstrata `BaseLLMProvider` com os métodos `gerar_texto()` e `gerar_json()`. Implementa:
- `LocalLLMProvider`: Chama o Ollama local com `ollama.Client(timeout=120.0)`, usando `format="json"` para respostas estruturadas. Sanitiza e faz parse do JSON retornado.
- `CloudLLMProvider`: Delega para `ai_service.processar_requisicao_complexa()` como fallback de nuvem.

### D. Serviço de Resiliência (`services/resilience_service.py`) — NOVO na V3
**Responsabilidade:** Implementa `execute_with_retry()`, uma função genérica que executa qualquer callable com retry parametrizável. Configura: número máximo de tentativas, tempo de espera entre tentativas, exceções recuperáveis, callbacks de validação de retorno e alertas de voz ao usuário em caso de reprocessamento. Lança `MaxRetriesExceededException` ao esgotar tentativas.

### E. Assistente de Compras (`services/shopping_assistant.py`)
**Responsabilidade:** Processa transcrições de compras de voz. Gera o prompt especializado, chama `self.llm_provider.gerar_json()` (que na V3 resolve para `LocalLLMProvider`) e percorre a lista de compras retornada. Valida e sanitiza os dados financeiros de cada item via `_validar_e_sanitizar_compra()` antes da persistência.

### F. Assistente de Inventário (`services/inventory_assistant.py`)
**Responsabilidade:** Gerencia o controle preditivo de estoque. Na V3, a classificação de intenções do usuário é realizada em dois níveis: (1) `_heuristica_rapida()` via Regex (0ms) e, em caso de falha, (2) `self.llm_provider.gerar_json()` com Gemma 3 4B local. Executa varredura de itens expirados na inicialização, gerencia os 4 cenários de intenção conversacional e suporta baixa voluntária com resolução de ambiguidade.

### G. Serviço de Banco de Dados (`services/db_service.py`)
**Responsabilidade:** Persistência relacional em SQLite com controle de versão de schema via `PRAGMA user_version`. Cria e migra as tabelas `compras`, `itens_compra` e `controle_consumo`. Expõe métodos genéricos (`executar_comando`, `executar_consulta`, `executar_consulta_uma_linha`) e o método especializado `salvar_compra_da_ia()`.

### H. Serviço de IA na Nuvem (`services/ai_service.py`)
**Responsabilidade:** Interface com a API Google Gemini. Na V3, atua como fallback. Trata explicitamente erros `TokenExhaustedException` (429) e `ServiceUnavailableException` (503). O método `processar_requisicao_complexa()` destina-se ao fallback de solicitações complexas, porém contém uma dívida técnica (`self.gemini_client` não instanciado).

### I. Serviço de Voz (`services/voice_service.py`)
**Responsabilidade:** Síntese de voz neural via `edge_tts` com voz `pt-BR-AntonioNeural`, salvando temporariamente o áudio em `assets/temp_voice.mp3` e reproduzindo via `pygame.mixer`. Remove o arquivo temporário após a reprodução.

### J. Serviço de Áudio (`services/audio_service.py`)
**Responsabilidade:** Captura de microfone com calibração de ruído ambiente, monitoramento de volume RMS, bips sonoros de status e controle de tempo (limite global de 120s, corte por silêncio de 5s, cancelamento por inatividade de 15s). Transcrição via Google Speech Recognition API.

### K. Serviço de Log (`services/logger_service.py`)
**Responsabilidade:** Logger transversal com arquivos segmentados por módulo e cabeçalhos diários automáticos. Métodos: `log_geral()` (para `Logs/main/main_log.txt`) e `log_assistente(nome, mensagem)` (para `Logs/{nome}/log.txt`).

---

## 3. Ciclo de Execução da Aplicação (Fluxo Principal V3)

```
[Inicialização: main.py]
         │
         ▼
[Instanciação de Serviços via Injeção de Dependências]
 DatabaseService, AudioService, AIService, VoiceService
 LocalLLMProvider(modelo="gemma4:e4b")
 CloudLLMProvider(ai_service=ai_service)
 InventoryAssistant(db, llm_provider=local_llm)
 ShoppingAssistant(db, llm_provider=local_llm)
         │
         ▼
[Passo 1: Varredura de Itens Expirados]
 inventory_assistant.verificar_itens_expirados_inicializacao()
   → Para cada item com autonomia esgotada:
     → VoiceService.falar(pergunta)
     → AudioService.capturar_audio_e_transcrever()
     → _heuristica_rapida() → ou → LocalLLMProvider.gerar_json() [Gemma 4 Local]
     → DatabaseService: atualiza controle_consumo
         │
         ▼
[Passo 2: Captura de Nova Solicitação por Voz]
 AudioService.capturar_audio_e_transcrever()
         │
         ▼
[Passo 3: Orquestração Local com Gemma 3 4B]
 execute_with_retry(orquestrar_requisicao, texto_transcrito)
   → gemma_service.orquestrar_requisicao()
     → ollama.Client(timeout=120).chat(model="gemma4:e4b", format="json")
     → _sanitizar_resposta_json() → json.loads() → _validar_schema_orquestrador()
   → Retorna: {dificuldade, mudanca_de_contexto, contexto, acao}
         │
         ├── [dificuldade="facil" + contexto="compras"]
         │     ▼
         │   execute_with_retry(shopping_assistant.processar_texto_compra)
         │     → LocalLLMProvider.gerar_json() → Gemma 4 Local
         │     → _validar_e_sanitizar_compra()
         │     → DatabaseService.salvar_compra_da_ia()
         │     → [Falha após 3 tentativas] → Gemini Nuvem (fallback)
         │
         ├── [dificuldade="facil" + outro contexto]
         │     ▼
         │   execute_with_retry(executar_assistente_local)
         │     → gemma_service.executar_assistente_local()
         │     → Gemma 4 Local via Ollama
         │
         └── [dificuldade="medio_dificil"]
               ▼
             execute_with_retry(ai_service.processar_requisicao_complexa)
               → Gemini API na Nuvem
         │
         ▼
[Passo 4: Resposta por Voz ao Usuário]
 VoiceService.falar(resposta_texto)
         │
         ▼
[GerenciadorDeSessao: Atualiza contexto e histórico]
         │
         ▼
[Fim da Execução]
```

---

## 4. Dependências e Acoplamento de Componentes

1. **`main.py`** acopla-se a:
   - `DatabaseService`, `AudioService`, `AIService`, `VoiceService`
   - `LocalLLMProvider`, `CloudLLMProvider`
   - `InventoryAssistant`, `ShoppingAssistant`
   - `gemma_service.orquestrar_requisicao`, `gemma_service.executar_assistente_local`
   - `resilience_service.execute_with_retry`
   - `logger_service`

2. **`ShoppingAssistant`** acopla-se a:
   - `BaseLLMProvider` (injetado como `LocalLLMProvider`)
   - `DatabaseService`
   - `logger_service`

3. **`InventoryAssistant`** acopla-se a:
   - `BaseLLMProvider` (injetado como `LocalLLMProvider`)
   - `DatabaseService`
   - `VoiceService` (instanciado internamente)
   - `AudioService` (instanciado internamente)
   - `logger_service`

4. **`LocalLLMProvider`** acopla-se a:
   - SDK `ollama` (via `ollama.Client`)

5. **`CloudLLMProvider`** acopla-se a:
   - `AIService`

6. **`gemma_service`** acopla-se a:
   - SDK `ollama` (diretamente)
   - `resilience_service.InvalidOrchestratorOutputException`
   - `logger_service`

7. **`AIService`** acopla-se a:
   - SDK `google-genai`
   - `logger_service`

8. **`DatabaseService`** acopla-se a:
   - `sqlite3`
   - `core/config.DB_PATH`
   - `logger_service`
