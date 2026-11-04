# 05 - Engenharia do Software

Este documento apresenta os diagramas técnicos de arquitetura, comunicação, fluxo e sequência do **Assistente Doméstico Inteligente (V4)**.

> [!NOTE]
> Os diagramas abaixo foram revisados a partir do código-fonte da V4 em 03/11/2026 (commit `c754a6a`). Linhas tracejadas indicam código existente que não é acionado pelo fluxo atual.

---

## 1. Diagrama de Arquitetura — Componentes Principais

```mermaid
graph TB
    subgraph "Interface Desktop — Electron"
        UI["renderer.js + index.html"]
        BRIDGE["preload.js<br>window.api"]
        EMAIN["main.js<br>spawn do Python"]
        UI --> BRIDGE --> EMAIN
    end

    subgraph "Runtime — app/main.py"
        RT["AssistenteRuntime<br>fila de eventos"]
        SESSAO["GerenciadorDeSessao"]
        RETRY["resilience_service<br>execute_with_retry()"]
        RT --> SESSAO
        RT --> RETRY
    end

    subgraph "Serviços de Domínio"
        GEMMA_SVC["gemma_service<br>orquestrar_requisicao()"]
        SHOPPING["shopping_assistant"]
        INVENTORY["inventory_assistant"]
        PA["project_analyzer"]
    end

    subgraph "LLM"
        LOCAL_PROV["LocalLLMProvider"]
        OLLAMA["Ollama<br>gemma4:e4b / qwen2.5-coder:7b"]
        AI_SVC["ai_service<br>Gemini 2.5 Flash"]
        LOCAL_PROV --> OLLAMA
    end

    subgraph "Memória Semântica"
        CTX["ContextRetrievalService"]
        MEM["MemoryService"]
        BUSCA["SemanticSearchService"]
        VS["VectorStoreService"]
        EMB["EmbeddingService<br>CPU"]
        CHROMA[("ChromaDB")]
        CTX --> BUSCA --> VS
        MEM --> VS
        VS --> EMB
        VS --> CHROMA
    end

    subgraph "Persistência Relacional"
        DB["DatabaseService"]
        SQLITE[("SQLite<br>compras, itens_compra<br>controle_consumo")]
        DB --> SQLITE
    end

    subgraph "Voz (sob demanda)"
        AUDIO["audio_service<br>PyAudio + Google Speech"]
        TTS["voice_service<br>edge-tts + pygame"]
    end

    EMAIN <-->|"JSON stdin/stdout"| RT
    RETRY --> GEMMA_SVC --> LOCAL_PROV
    RETRY --> SHOPPING --> LOCAL_PROV
    RETRY --> AI_SVC
    RT --> PA --> LOCAL_PROV
    RT --> INVENTORY --> DB
    SHOPPING --> DB
    SHOPPING --> VS
    RT --> CTX
    RT --> MEM
    RT --> AUDIO
    RT --> TTS
    SHOPPING -.->|"não implementado"| INVENTORY
```

---

## 2. Diagrama de Fluxo — Processamento de uma Solicitação

```mermaid
flowchart TD
    A([Texto do chat ou voz transcrita]) --> B{Comando<br>determinístico?}
    B -- Qwen --> C[Troca o modelo ativo]
    C --> FIM
    B -- Analisar projeto --> D[ProjectAnalyzer<br>local, sem nuvem]
    D --> FIM
    B -- Não --> E[execute_with_retry<br>orquestrar_requisicao]
    B -- Regra conhecida --> J{Contexto}
    E -- Falha após 3x --> X[Avisa: IA local indisponível<br>nada vai à nuvem]
    E -- Classificado --> J
    J -- geral/outro difícil --> N[Gemini<br>perguntas gerais]
    J -- compras --> I{acao}
    J -- inventario --> K{acao}
    J -- agenda --> Y[Avisa: ainda indisponível]
    J -- geral/outro/programacao --> L[executar_assistente_local]

    I -- consultar --> Z[Avisa: disponível na Fase 3]
    I -- criar --> V[preparar_compra]
    V -- Falha após 3x --> X
    V -- Sem dúvida --> M[(SQLite + ChromaDB)]
    V -- Com dúvida --> W{Usuário confirma?}
    W -- Sim --> M
    W -- Não --> R
    K -- consultar/delegar --> O[consultar_estoque]
    K -- criar/corrigir --> P[Informa a limitação]
    L -- Falha em geral/outro --> N
    L -- Falha em programacao --> X

    N -- Falha após 3x --> Q[Mensagem de indisponibilidade]
    M --> R[Atualiza sessão]
    O --> R
    P --> R
    Y --> R
    Z --> R
    L --> R
    N -- Sucesso --> R
    R --> S[Registra memória semântica<br>exceto compras e inventário]
    S --> FIM([assistant_message + TTS opcional])
    Q --> FIM
    X --> FIM
```

---

## 3. Diagrama de Comunicação — Relações entre Componentes

```mermaid
graph LR
    USER["Usuário"] -->|Texto| UI["Electron"]
    USER -->|Voz, se ativada| AUDIO["audio_service"]
    AUDIO -->|Buffer PCM| GOOGLE_STT["Google Speech<br>(Externo)"]
    GOOGLE_STT -->|Texto transcrito| RT["AssistenteRuntime"]
    UI -->|send_text| RT
    RT -->|assistant_message| UI

    RT -->|texto| GEMMA_SVC["gemma_service"]
    GEMMA_SVC -->|POST /api/chat| OLLAMA["Ollama Local"]
    OLLAMA -->|JSON classificado| GEMMA_SVC

    RT -->|preparar e registrar compra| SHOPPING["shopping_assistant"]
    SHOPPING -->|gerar_json| OLLAMA
    SHOPPING -->|dados validados| DB["SQLite"]
    SHOPPING -->|itens vetorizados| CHROMA["ChromaDB"]

    RT -->|consultar_estoque| INVENTORY["inventory_assistant"]
    INVENTORY -->|SELECT| DB

    RT -->|recupera e salva memória| CHROMA
    RT -->|perguntas gerais| AI["ai_service"]
    AI -->|HTTPS| GEMINI["Gemini<br>(Externo)"]
    RT -->|resposta, se voz ativa| VOICE["voice_service"]
    VOICE -->|texto| EDGE_TTS["Edge TTS<br>(Externo)"]
    VOICE -->|áudio| USER
```

---

## 4. Diagrama de Sequência — Execução Típica (Registro de Compra)

```mermaid
sequenceDiagram
    actor User as 👤 Usuário
    participant UI as Electron
    participant Main as AssistenteRuntime
    participant Retry as execute_with_retry
    participant Gemma as gemma_service
    participant Ollama as Ollama Local
    participant Shopping as ShoppingAssistant
    participant LocalLLM as LocalLLMProvider
    participant DB as DatabaseService
    participant Chroma as VectorStoreService
    participant Voice as VoiceService

    User->>UI: Digita: "fui ao Moreschi, comprei frango..."
    UI->>Main: send_text (JSON por stdin)

    Main->>Retry: execute_with_retry(orquestrar_requisicao)
    Retry->>Gemma: orquestrar_requisicao(texto)
    Gemma->>Gemma: rotear_por_regras(texto)
    Gemma-->>Retry: decisao dict
    Retry-->>Main: {dificuldade:"facil", contexto:"compras"}

    Main->>Retry: execute_with_retry(preparar_compra)
    Retry->>Shopping: preparar_compra(texto)
    Shopping->>LocalLLM: gerar_json(prompt_sistema, texto)
    LocalLLM->>Ollama: POST /api/chat [format=json]
    Note over Ollama: Inferência JSON compras
    Ollama-->>LocalLLM: {"compras":[{"estabelecimento":"Moreschi","itens":[...]}]}
    LocalLLM-->>Shopping: dados dict
    Shopping->>Shopping: _validar_e_sanitizar_compra()
    Shopping-->>Retry: {"compras":[...], "duvidas":[]}
    Retry-->>Main: compra preparada
    Main->>Shopping: registrar_compras(compras)
    Shopping->>DB: salvar_compras_da_ia(compras)
    DB-->>Shopping: ids
    Shopping->>Chroma: upsert_documents(itens vetorizados)
    Shopping-->>Main: {"status":"sucesso", "compras_processadas":1}

    Main-->>UI: assistant_message (JSON por stdout)
    UI-->>User: Exibe a resposta no chat
    opt Modo voz ativo e sem mudo
        Main->>Voice: falar("Informações inseridas com sucesso!")
        Voice-->>User: Resposta por voz
    end
```

---

## 5. Diagrama de Bifurcações — Pontos de Decisão do Sistema

```mermaid
flowchart TD
    START([Texto Transcrito]) --> ORCH{Orquestrador\nGemma Local}

    ORCH -->|dificuldade='facil'\ncontexto='compras'| COMP[ShoppingAssistant\nLocalLLMProvider → Gemma]
    ORCH -->|dificuldade='facil'\ncontexto='agenda'| AGENDA[Avisa: agenda\nainda indisponível]
    ORCH -->|dificuldade='facil'\ncontexto='inventario'| INVENT["InventoryAssistant\nconsultar_estoque\n(criar/corrigir: informa limitação)"]
    ORCH -->|Regex\ncontexto='projetos'| PROJ[ProjectAnalyzer\nsem nuvem]
    ORCH -->|dificuldade='facil'\ncontexto='geral' ou 'outro'| OUTRO[executar_assistente_local\nGemma Local]
    ORCH -->|'geral' ou 'outro' difícil| NUVEM[ai_service\nGemini API]
    ORCH -->|Falha após 3x retry| AVISO[Avisa: IA local indisponível\nnada vai à nuvem]
    OUTRO -->|Falha após 3x retry| NUVEM

    COMP -->|Sem dúvida ou confirmada| DB[(SQLite)]
    COMP -->|Falha após 3x retry\nnada é gravado| AVISO

    INVENTORY_INIT([Inicialização]) --> VARR{Para cada item ativo\ncom autonomia esgotada}
    VARR --> PEND[Modo texto: marca\nvalidacao_pendente]
    VARR -.->|Voz ativa: não ocorre\nna inicialização| RESP{Resposta do\nusuário}
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
| **Dependency Injection** | `app/main.py` → `ShoppingAssistant`, `InventoryAssistant` | Provedores LLM são injetados externamente, facilitando testes e troca |
| **Retry Pattern** | `resilience_service.execute_with_retry` | Resiliência uniforme a falhas em qualquer chamada de LLM |
| **Fallback Chain** | `app/main.py`: Local → Gemini, só em `geral` e `outro` | Contingência sem enviar dados restritos à nuvem |
| **Chain of Responsibility** | `orquestrar_requisicao` e `InventoryAssistant`: regras → LLM | Processamento progressivo, do mais rápido para o mais custoso |
| **Session Management** | `GerenciadorDeSessao` em `app/main.py` | Manutenção de contexto e histórico entre interações |
| **Schema Validation** | `gemma_service._validar_schema_orquestrador` | Contrato rígido de saída do LLM orquestrador |
| **Sanitization Pipeline** | `_sanitizar_resposta_json` (em múltiplos módulos) | Remove marcações Markdown residuais do LLM antes do parse |
| **Event Loop com Fila** | `AssistenteRuntime.rodar` | Processa comandos do chat, voz e controles em uma única sequência |
| **Bridge Seguro** | `preload.js` (`contextBridge`) | Expõe ao renderer apenas a API necessária |
| **Inicialização Lazy** | `VoiceService`, `AudioService` | Só acessa o hardware quando o modo voz é ativado |
| **Singleton** | `EmbeddingService`, `VectorStoreService` | Evita recarregar o modelo e reabrir o cliente ChromaDB |
| **Fachada** | `ProjectAnalyzer` | Coordena varredura, extração, LLM local e documentação |
| **Índice Incremental** | `index_cache.py` | Reanalisa apenas arquivos com hash alterado |
