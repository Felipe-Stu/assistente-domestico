# 05 - Engenharia do Software

Este documento apresenta os diagramas técnicos de arquitetura, comunicação, fluxo e sequência do **Assistente Doméstico Inteligente**, no estado da **V4.1**.

> [!NOTE]
> Os diagramas abaixo foram revisados a partir do código-fonte da V4.1 em 23/11/2026 (branch `v4.1`, depois do commit `e9441bf`). Linhas tracejadas indicam código existente que não é acionado pelo fluxo atual.

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

    subgraph "Skills — core/skills + skills/"
        ROUTER["intent_router<br>gatilhos das skills"]
        GEMMA_SVC["gemma_service<br>orquestrador pelo catálogo"]
        MOTOR["motor<br>roteiro.py de cada skill"]
        ROUTER --> MOTOR
        GEMMA_SVC --> MOTOR
    end

    subgraph "Serviços de Domínio"
        SHOPPING["shopping_assistant"]
        INVENTORY["inventory_assistant"]
        PA["project_analyzer"]
        IDEIAS["ideias_service<br>fila de análise"]
        BIB["biblioteca_service"]
        TG["telegram_service<br>bot (opcional)"]
    end

    subgraph "LLM"
        LOCAL_PROV["LocalLLMProvider"]
        OLLAMA["Ollama<br>gemma4:e4b / qwen2.5-coder:7b"]
        AI_SVC["ai_service<br>Gemini 2.5 Flash"]
        CLAUDE["Claude<br>assinatura (claude -p) ou API"]
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
        SQLITE[("SQLite<br>compras, itens_compra, controle_consumo<br>compromissos, ideias")]
        DB --> SQLITE
    end

    subgraph "Voz (sob demanda)"
        AUDIO["audio_service<br>PyAudio + Google Speech"]
        TTS["voice_service<br>edge-tts + pygame"]
    end

    EMAIN <-->|"JSON stdin/stdout"| RT
    RT --> ROUTER
    RETRY --> GEMMA_SVC --> LOCAL_PROV
    MOTOR --> SHOPPING --> LOCAL_PROV
    MOTOR --> INVENTORY --> DB
    MOTOR --> PA --> LOCAL_PROV
    MOTOR -->|"agenda: compromissos"| DB
    MOTOR --> IDEIAS
    MOTOR -->|"programacao"| CLAUDE
    MOTOR -->|"programacao sem Claude"| BIB
    IDEIAS --> CLAUDE
    IDEIAS --> DB
    IDEIAS --> BIB --> VS
    TG <--> IDEIAS
    RETRY --> AI_SVC
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
    A([Texto do chat ou voz transcrita]) --> PEND{Pendência de<br>uma skill?}
    PEND -- Sim --> RP[responder_pendencia<br>ex.: confirmar compra]
    RP --> R
    PEND -- Não --> B{Comando<br>determinístico?}
    B -- Qwen --> C[Troca o modelo ativo]
    C --> FIM
    B -- Analisar projeto --> D[ProjectAnalyzer<br>local, sem nuvem]
    D --> FIM
    B -- Gatilho de skill --> SK
    B -- Não --> H{Ollama responde<br>em 2 s?}
    H -- Não --> HX[Avisa: Ollama fechado<br>botão Tentar de novo]
    HX --> FIM
    H -- Sim --> E[orquestrar_requisicao<br>Gemma 4 escolhe a skill pelo catálogo]
    E -- Falha após 3x --> X[Avisa: IA local indisponível<br>nada vai à nuvem]
    E -- conversa-geral --> J{Difícil e pode<br>ir à nuvem?}
    E -- skill com roteiro --> SK[roteiro.py da skill]

    SK -- compras --> V[preparar_compra → confirmação se houver dúvida → SQLite + ChromaDB]
    SK -- estoque --> O[consultar_estoque]
    SK -- agenda --> AG[anotar / consultar / cancelar<br>compromissos]
    SK -- ideias --> ID{Fala de uma<br>ideia salva?}
    ID -- Sim --> IDR[salva ou consulta<br>resposta local com a análise]
    ID -- Não --> J
    SK -- programacao --> PC{Claude<br>disponível?}
    PC -- Sim --> CL[Claude<br>assinatura ou API]
    PC -- Não --> QW[Qwen + biblioteca]
    SK -- documentar-projeto --> D

    J -- Sim --> N[Gemini<br>perguntas gerais]
    J -- Não --> L[executar_assistente_local]
    L -- Falha em geral/outro --> N
    N -- Falha após 3x --> Q[Mensagem de indisponibilidade]

    V --> R[Atualiza sessão]
    O --> R
    AG --> R
    IDR --> R
    CL --> R
    QW --> R
    L --> R
    N -- Sucesso --> R
    R --> S[Registra memória semântica<br>exceto compras, inventário, agenda, projetos e ideias]
    S --> FIM([assistant_message + TTS opcional])
    Q --> FIM
    X --> FIM
```

Em paralelo, a **fila de ideias** manda as pendentes ao Claude e grava a análise. O **bot do Telegram** recebe ideias do celular e devolve a análise (seção 4.1).

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
    RT -->|programação, ideias| CLAUDE["Claude<br>(Externo, via Claude Code ou API)"]
    PHONE["Celular"] -->|ideia| TGAPI["Telegram<br>(Externo)"]
    TGAPI -->|getUpdates| RT
    RT -->|sendMessage: análise| TGAPI
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

    Main->>Main: rotear_por_regras(texto): gatilho "comprei" da skill compras
    Note over Main: Sem gatilho, orquestrar_requisicao escolheria a skill pelo catálogo
    Main->>Main: motor.executar(skill compras) → skills/compras/roteiro.py

    Main->>Retry: execute_with_retry(preparar_compra)
    Retry->>Shopping: preparar_compra(texto)
    Shopping->>LocalLLM: gerar_json(prompt_sistema, texto)
    LocalLLM->>Ollama: POST /api/chat [format=JSON Schema]
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

## 4.1. Diagrama de Sequência — Ideia pelo Telegram (V4.1)

```mermaid
sequenceDiagram
    actor User as 👤 Usuário (celular)
    participant TG as Telegram
    participant Bot as TelegramService
    participant Ideias as IdeiasService
    participant DB as SQLite
    participant Claude as Claude Code (claude -p)
    participant Bib as BibliotecaService

    User->>TG: "Um app que sugere receitas pela geladeira"
    Bot->>TG: getUpdates (long polling)
    TG-->>Bot: mensagem do chat permitido
    Bot->>Ideias: responder_mensagem(texto, "telegram:<chat>")
    Ideias->>Ideias: parece_pergunta? não
    Ideias->>DB: INSERT ideias (pendente)
    Ideias-->>Bot: "Ideia #N salva..."
    Bot->>TG: sendMessage
    Note over Ideias: Fila em segundo plano
    Ideias->>Claude: prompt de análise + ideia (sem ferramentas)
    Claude-->>Ideias: # Título, resumo, MVP, próximos passos...
    Ideias->>DB: UPDATE ideias (analisada)
    Ideias->>Ideias: grava Ideias/ideia-NNNN-*.md
    Ideias->>Bib: indexar() (incremental)
    Ideias->>Bot: aviso para o chat de origem
    Bot->>TG: sendMessage (análise)
    TG-->>User: Análise da ideia
```

---

## 5. Diagrama de Bifurcações — Pontos de Decisão do Sistema

```mermaid
flowchart TD
    START([Texto Transcrito]) --> ORCH{Gatilhos ou orquestrador\npelo catálogo}

    ORCH -->|skill compras| COMP[ShoppingAssistant\nLocalLLMProvider → Gemma]
    ORCH -->|skill agenda| AGENDA[Compromissos\nSQLite local]
    ORCH -->|skill estoque| INVENT["InventoryAssistant\nconsultar_estoque\n(criar/corrigir: informa limitação)"]
    ORCH -->|skill documentar-projeto\nou comando| PROJ[ProjectAnalyzer\nsem nuvem]
    ORCH -->|skill ideias| IDEIA[IdeiasService\nfila → Claude]
    IDEIA -->|não fala de ideia salva| OUTRO
    ORCH -->|skill programacao| PROG[Claude\nou Qwen + biblioteca]
    ORCH -->|conversa-geral fácil| OUTRO[executar_assistente_local\nGemma Local]
    ORCH -->|conversa-geral difícil| NUVEM[ai_service\nGemini API]
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
| **Chain of Responsibility** | Pipeline do runtime (pendência → comandos → gatilhos → orquestrador) e `InventoryAssistant`: regras → LLM | Processamento progressivo, do mais rápido para o mais custoso |
| **Session Management** | `GerenciadorDeSessao` em `app/main.py` | Manutenção de contexto e histórico entre interações |
| **Schema Validation** | `gemma_service._validar_schema_orquestrador` | Contrato rígido de saída do LLM orquestrador |
| **Sanitization Pipeline** | `llm_provider._sanitizar_resposta_json` | Remove marcações Markdown residuais do LLM antes do parse |
| **Event Loop com Fila** | `AssistenteRuntime.rodar` | Processa comandos do chat, voz e controles em uma única sequência |
| **Bridge Seguro** | `preload.js` (`contextBridge`) | Expõe ao renderer apenas a API necessária |
| **Inicialização Lazy** | `VoiceService`, `AudioService` | Só acessa o hardware quando o modo voz é ativado |
| **Singleton** | `EmbeddingService`, `VectorStoreService` | Evita recarregar o modelo e reabrir o cliente ChromaDB |
| **Fachada** | `ProjectAnalyzer` | Coordena varredura, extração, LLM local e documentação |
| **Índice Incremental** | `index_cache.py` | Reanalisa apenas arquivos com hash alterado |
| **Fail Fast** (V4.1) | `llm_provider.garantir_ollama_disponivel` | Verificação de saúde de 2 s; erro de conexão não entra na repetição |
| **Saída Estruturada** (V4.1) | `services/esquemas.py` | O contrato do orquestrador e da extração vai ao modelo, não só à validação |
| **Identificador de Correlação** (V4.1) | `logger_service.requisicao()` | Todos os eventos de uma solicitação levam o mesmo `req`, com o tempo de cada etapa |
| **Escrita Atômica por Renomeação** (V4.1) | `BackupService.fazer_backup` | A cópia é montada em `.parcial` e só recebe o nome final quando termina |
| **Retenção Avô-Pai-Filho** (V4.1) | `BackupService.aplicar_retencao` | 7 cópias diárias e a mais nova de cada uma de 4 semanas |
| **Plugin por Catálogo** (V4.1) | `core/skills/catalogo.py` + `skills/*/SKILL.md` | Uma capacidade nova é uma pasta; gatilhos e contextos vêm do cabeçalho |
| **Política no Cabeçalho** (V4.1) | `privacidade` das skills + `CLAUDE_SKILLS` em `_contexto_skill` | O núcleo só entrega o Claude (ou a nuvem) às skills autorizadas; testes conferem cabeçalho × política |
| **Contexto Mínimo** (V4.1) | `core.skills.Contexto` | O roteiro recebe só os serviços de que precisa, sem acesso ao runtime |
| **Encaminhamento** (V4.1) | `Resposta.encaminhar` | Um roteiro devolve o pedido à conversa geral quando não é com ele (P23) |
| **Adapter** (V4.1) | `ClaudeService` / `ClaudeAssinaturaService` | Mesma interface para API e assinatura; as skills não sabem qual está em uso |
| **Fila com Reteste** (V4.1) | `IdeiasService.iniciar_em_segundo_plano` | Ideia salva na hora; análise tentada de novo enquanto o Claude estiver indisponível |
| **Circuit Breaker Simples** (V4.1) | `indisponivel_ate` no estado do Claude | Sem cota ou sem login, não insiste até o horário de reteste |
| **Lista de Permissões** (V4.1) | `TELEGRAM_CHAT_IDS` | O bot ignora qualquer chat fora da lista |

