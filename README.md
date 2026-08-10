================================================================================
ASSISTENTE DOMÉSTICO INTELIGENTE MODULAR (V3)
================================================================================

Este é o repositório do Assistente Doméstico Inteligente, um sistema leve, 
modular e orientado a serviços com Arquitetura Híbrida de IA. Ele captura 
comandos de voz (compras, agenda, inventário), transcreve o áudio, orquestra 
e extrai dados estruturados usando LLM local como primário e fallback 
automático na nuvem, salvando tudo localmente em um banco de dados SQLite.

--------------------------------------------------------------------------------
1. DIAGRAMA DE ARQUITETURA (V3)
--------------------------------------------------------------------------------

Sintaxe Mermaid para visualizadores gráficos:

graph TD
    subgraph V3["V3 — Arquitetura Híbrida"]
        direction TB
        M3["main.py + GerenciadorDeSessao"]

        subgraph Core_Local["Execução Local (Primária)"]
            GEMMA_SVC["gemma_service (Orquestrador)"]
            SHOPPING3["shopping_assistant (LocalLLMProvider)"]
            INVENT3["inventory_assistant (Regex + LocalLLM)"]
            OLLAMA[("Ollama Local\nGemma 4 (e4b)")]
        end

        subgraph Core_Nuvem["Execução Nuvem (Contingência)"]
            AIS3["ai_service.py"]
            GEMINI3["Google Gemini API"]
        end

        M3 -->|execute_with_retry| GEMMA_SVC
        M3 -->|Fluxo Compras| SHOPPING3
        M3 -->|Fluxo Inventário| INVENT3

        GEMMA_SVC & SHOPPING3 & INVENT3 -->|Ollama SDK| OLLAMA

        M3 -->|Fallback Direct| AIS3
        SHOPPING3 -->|Fallback 3x Retry| AIS3
        AIS3 -->|API HTTPS| GEMINI3
    end

--------------------------------------------------------------------------------
2. ESTRUTURA DO PROJETO
--------------------------------------------------------------------------------

assistente-domestico/
├── core/
│   ├── database/
│   │   └── assistente_casa.db   # Banco de dados SQLite auto-gerado
│   ├── __init__.py
│   └── config.py               # Configurações globais e de ambiente
├── services/
│   ├── __init__.py
│   ├── ai_service.py            # Integração com Google Gemini (contingência na nuvem)
│   ├── audio_service.py         # Captura de microfone e transcrição de voz
│   ├── db_service.py            # Conexão e persistência SQLite
│   ├── gemma_service.py         # Orquestrador local e classificação de intenções
│   ├── llm_provider.py          # Abstração de provedores LLM (LocalLLM e CloudLLM)
│   ├── logger_service.py        # Sistema de logs centralizado
│   ├── resilience_service.py    # Tratamento de exceções e políticas de retry
│   ├── shopping_assistant.py    # Assistente especialista em extração de compras
│   └── inventory_assistant.py   # Assistente especialista em inventário e estoque
├── app/
│   ├── templates/              # Futura interface web
│   ├── static/                 # Arquivos estáticos
│   └── main.py                 # Orquestrador do fluxo principal e gerenciamento de sessão
├── requirements.txt             # Dependências do projeto
└── README.md

--------------------------------------------------------------------------------
3. PRÉ-REQUISITOS
--------------------------------------------------------------------------------

1. Python 3.10+
2. Ollama Runtime instalado localmente.
3. Modelo Gemma 4 (gemma4:e4b) baixado no Ollama.
4. Chave de API do Google Gemini (usada para contingência em caso de timeout
   ou falha da LLM local).

--------------------------------------------------------------------------------
4. INSTALAÇÃO E EXECUÇÃO
--------------------------------------------------------------------------------

1. Baixar o Modelo LLM Local:
   Certifique-se de que o Ollama está rodando e baixe o modelo padrão:
   
   ollama pull gemma4:e4b

2. Instalar as Dependências:

   pip install -r requirements.txt

3. Configurar as Variáveis de Ambiente:
   Crie um arquivo .env na raiz do projeto contendo:

   GEMINI_API_KEY=sua_chave_gemini_aqui
   OLLAMA_HOST=http://localhost:11434

4. Executar o Assistente:

   python app/main.py
