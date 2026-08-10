# 05 - Engenharia do Software

Este documento apresenta os diagramas técnicos de arquitetura, comunicação, fluxo e sequência do **Assistente Doméstico Inteligente (V3)**.

> [!NOTE]
> Todos os diagramas abaixo foram construídos a partir da análise direta do código-fonte da V3. Os componentes e fluxos representados refletem o estado real do sistema.

---

## 1. Diagrama de Arquitetura — Componentes Principais

```mermaid
graph TB
    subgraph "Entrada do Usuário"
        MIC["🎤 Microfone\n(PyAudio)"]
        SPK["🔊 Alto-falantes\n(pygame.mixer)"]
    end

    subgraph "Transcrição"
        STT["Google Speech\nRecognition API\n(Externo)"]
    end

    subgraph "app/main.py — Orquestrador"
        MAIN["GerenciadorDeSessao\n+ processar_solicitacao()"]
        RETRY["resilience_service\nexecute_with_retry()"]
    end

    subgraph "LLM Local — Ollama"
        OLLAMA["Servidor Ollama\nhttp://127.0.0.1:11434"]
        GEMMA["Gemma 3 4B\n(gemma4:e4b)"]
        OLLAMA --> GEMMA
    end

    subgraph "Serviços Especializados"
        GEMMA_SVC["gemma_service\norquestrar_requisicao()"]
        SHOPPING["shopping_assistant\nprocessar_texto_compra()"]
        INVENTORY["inventory_assistant\nverificar_itens_expirados()\nprocessar_estoque_nova_compra()"]
    end

    subgraph "Camada de Abstração LLM"
        LOCAL_PROV["LocalLLMProvider\n(Ollama)"]
        CLOUD_PROV["CloudLLMProvider\n(Gemini)"]
    end

    subgraph "IA na Nuvem — Fallback"
        AI_SVC["ai_service\nGemini 2.5 Flash\n(Google Cloud)"]
    end

    subgraph "Persistência"
        DB["DatabaseService\nSQLite"]
        DBFILE["assistente_casa.db\ncompras / itens_compra\ncontrole_consumo"]
    end

    subgraph "Síntese de Voz"
        TTS["voice_service\nedge-tts\n(Microsoft Edge)"]
    end

    MIC --> STT --> MAIN
    MAIN --> RETRY
    RETRY --> GEMMA_SVC --> OLLAMA
    RETRY --> SHOPPING --> LOCAL_PROV --> OLLAMA
    RETRY --> AI_SVC
    SHOPPING --> DB --> DBFILE
    INVENTORY --> LOCAL_PROV
    INVENTORY --> DB
    MAIN --> INVENTORY
    INVENTORY --> TTS --> SPK
    MAIN --> TTS
    LOCAL_PROV --> CLOUD_PROV
    CLOUD_PROV --> AI_SVC
```

---

## 2. Diagrama de Fluxo — Processamento de uma Solicitação

```mermaid
flowchart TD
    A([Início]) --> B[AudioService\nCaptura voz do microfone]
    B --> C{Áudio\ndetectado?}
    C -- Não --> Z([Fim: Nenhuma fala])
    C -- Sim --> D[Google Speech Recognition\nTranscreve para texto]
    D --> E[execute_with_retry\norquestrar_requisicao - Gemma Local]
    E --> F{Orquestração\nbem-sucedida?}
    F -- Falha após 3x --> G[Fallback para Gemini\ndificuldade=medio_dificil]
    F -- Sucesso --> H{Dificuldade\ndo orquestrador}

    H -- facil + compras --> I[execute_with_retry\nShoppingAssistant]
    H -- facil + outro --> J[execute_with_retry\nexecutar_assistente_local]
    H -- medio_dificil --> G

    I --> K{LocalLLM\nbem-sucedido?}
    K -- Sim --> L[Valida e sanitiza JSON]
    K -- Falha após 3x --> G
    L --> M[DatabaseService\nsalvar_compra_da_ia]
    M --> N[VoiceService\nResponde ao usuário]

    J --> N
    G --> O[execute_with_retry\nai_service Gemini]
    O --> P{Gemini\nbem-sucedido?}
    P -- Sim --> N
    P -- Falha após 3x --> Q[Mensagem de erro\npor voz]

    N --> R[GerenciadorDeSessao\nAtualiza contexto]
    Q --> R
    R --> Z2([Fim])
```

---

## 3. Diagrama de Comunicação — Relações entre Componentes

```mermaid
graph LR
    USER["👤 Usuário"] -->|Voz| AUDIO["audio_service"]
    AUDIO -->|Buffer PCM| GOOGLE_STT["Google Speech\nRecognition\n(Externo)"]
    GOOGLE_STT -->|Texto transcrito| MAIN["main.py"]

    MAIN -->|texto_transcrito| GEMMA_SVC["gemma_service"]
    GEMMA_SVC -->|POST /api/chat| OLLAMA["Ollama Local\nGemma 3 4B"]
    OLLAMA -->|JSON classificado| GEMMA_SVC
    GEMMA_SVC -->|decisao dict| MAIN

    MAIN -->|processar_texto_compra| SHOPPING["shopping_assistant"]
    SHOPPING -->|gerar_json prompt| LOCAL_LLM["LocalLLMProvider\nOllama"]
    LOCAL_LLM -->|POST /api/chat| OLLAMA
    OLLAMA -->|JSON compras| LOCAL_LLM
    LOCAL_LLM -->|dados dict| SHOPPING
    SHOPPING -->|dados validados| DB["DatabaseService\nSQLite"]

    MAIN -->|verificar_itens_expirados| INVENTORY["inventory_assistant"]
    INVENTORY -->|falar pergunta| VOICE["voice_service"]
    VOICE -->|texto| EDGE_TTS["Microsoft\nEdge TTS\n(Externo)"]
    EDGE_TTS -->|MP3| VOICE
    VOICE -->|áudio| USER

    INVENTORY -->|capturar resposta| AUDIO
    INVENTORY -->|_heuristica_rapida| REGEX["Regex / Heurística\n(interno)"]
    REGEX -->|Miss| LOCAL_LLM
    INVENTORY -->|UPDATE| DB

    MAIN -->|fallback| AI["ai_service\nGemini Nuvem"]
    AI -->|HTTPS| GEMINI["Google Gemini API\n(Externo)"]
    GEMINI -->|resposta| AI
    AI -->|texto| MAIN
    MAIN -->|resposta_texto| VOICE
```

---

## 4. Diagrama de Sequência — Execução Típica (Registro de Compra)

```mermaid
sequenceDiagram
    actor User as 👤 Usuário
    participant Audio as AudioService
    participant STT as Google STT
    participant Main as main.py
    participant Retry as execute_with_retry
    participant Gemma as gemma_service
    participant Ollama as Ollama Local
    participant Shopping as ShoppingAssistant
    participant LocalLLM as LocalLLMProvider
    participant DB as DatabaseService
    participant Voice as VoiceService

    User->>Audio: Fala: "fui ao Moreschi, comprei frango..."
    Audio->>Audio: Captura buffer PCM (RMS monitoring)
    Audio->>STT: AudioData (pt-BR)
    STT-->>Audio: "fui ao Moreschi, comprei frango..."
    Audio-->>Main: texto_transcrito

    Main->>Retry: execute_with_retry(orquestrar_requisicao)
    Retry->>Gemma: orquestrar_requisicao(texto)
    Gemma->>Ollama: POST /api/chat [format=json, temp=0.1]
    Note over Ollama: Inferência ~40s
    Ollama-->>Gemma: {"dificuldade":"facil","contexto":"compras",...}
    Gemma->>Gemma: _validar_schema_orquestrador()
    Gemma-->>Retry: decisao dict
    Retry-->>Main: {dificuldade:"facil", contexto:"compras"}

    Main->>Retry: execute_with_retry(processar_texto_compra)
    Retry->>Shopping: processar_texto_compra(texto)
    Shopping->>LocalLLM: gerar_json(prompt_sistema, texto)
    LocalLLM->>Ollama: POST /api/chat [format=json]
    Note over Ollama: Inferência JSON compras
    Ollama-->>LocalLLM: {"compras":[{"estabelecimento":"Moreschi","itens":[...]}]}
    LocalLLM-->>Shopping: dados dict
    Shopping->>Shopping: _validar_e_sanitizar_compra()
    Shopping->>DB: salvar_compra_da_ia(dados_validados)
    DB-->>Shopping: compra_id
    Shopping-->>Retry: {"status":"sucesso", "compras_processadas":1}
    Retry-->>Main: resultado

    Main->>Voice: falar("Informações inseridas com sucesso!")
    Voice->>Voice: edge_tts.Communicate(texto).save(mp3)
    Voice->>Voice: pygame.mixer.music.play()
    Voice-->>User: 🔊 Resposta por voz
```

---

## 5. Diagrama de Bifurcações — Pontos de Decisão do Sistema

```mermaid
flowchart TD
    START([Texto Transcrito]) --> ORCH{Orquestrador\nGemma Local}

    ORCH -->|dificuldade='facil'\ncontexto='compras'| COMP[ShoppingAssistant\nLocalLLMProvider → Gemma]
    ORCH -->|dificuldade='facil'\ncontexto='agenda'| AGENDA[executar_assistente_local\nGemma Local]
    ORCH -->|dificuldade='facil'\ncontexto='inventario'| INVENT["InventoryAssistant\n(não implementado no roteador\nda V3 para criação)"]
    ORCH -->|dificuldade='facil'\ncontexto='geral' ou 'outro'| OUTRO[executar_assistente_local\nGemma Local]
    ORCH -->|dificuldade='medio_dificil'| NUVEM[ai_service\nGemini API]
    ORCH -->|Falha após 3x retry| NUVEM

    COMP -->|Sucesso| DB[(SQLite)]
    COMP -->|Falha após 3x retry| NUVEM

    INVENTORY_INIT([Inicialização]) --> VARR{Para cada item\ncom autonomia esgotada}
    VARR --> RESP{Resposta do\nusuário}
    RESP -->|Heurística Regex\nresolve| CLASS1[Classifica\nlocalmente - 0ms]
    RESP -->|Heurística\nnão resolve| CLASS2[Gemma 4 Local\nLocalLLMProvider]
    CLASS1 --> INT{Intenção}
    CLASS2 --> INT
    INT -->|CONFIRMACAO| CONF[Mantém resíduo estimado]
    INT -->|NEGATIVA_ZERADO| ZERO[Zera estoque\nAtualiza ritmo]
    INT -->|NEGATIVA_SEM_CONSUMO| INTACT[Mantém estoque antigo]
    INT -->|DIVERGENCIA_QUANTIDADE| DIV[Ajusta para\nquantidade real]
```

---

## 6. Padrões de Engenharia Identificados no Código

| Padrão | Onde é aplicado | Finalidade |
|--------|-----------------|------------|
| **Strategy Pattern** | `llm_provider.py` (`BaseLLMProvider`) | Permite trocar o provedor LLM (local/nuvem) sem alterar os assistentes |
| **Dependency Injection** | `main.py` → `ShoppingAssistant`, `InventoryAssistant` | Provedores LLM são injetados externamente, facilitando testes e troca |
| **Retry Pattern** | `resilience_service.execute_with_retry` | Resiliência uniforme a falhas em qualquer chamada de LLM |
| **Fallback Chain** | `main.py`: Local → Gemini Nuvem | Garantia de processamento mesmo com falha do modelo local |
| **Chain of Responsibility** | `InventoryAssistant`: Regex → Gemma | Processamento progressivo, do mais rápido para o mais custoso |
| **Session Management** | `GerenciadorDeSessao` em `main.py` | Manutenção de contexto e histórico entre interações |
| **Schema Validation** | `gemma_service._validar_schema_orquestrador` | Contrato rígido de saída do LLM orquestrador |
| **Sanitization Pipeline** | `_sanitizar_resposta_json` (em múltiplos módulos) | Remove marcações Markdown residuais do LLM antes do parse |
