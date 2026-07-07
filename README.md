# Assistente Doméstico Inteligente Modular

Este é o MVP de um assistente doméstico inteligente, projetado para ser leve, modular e orientado a serviços. Ele captura comandos de voz sobre compras de mercado, transcreve o áudio, processa as informações usando IA (LLM) para extrair dados estruturados e os salva localmente em um banco de dados SQLite.

## Estrutura do Projeto

```text
assistente-domestico/
├── core/
│   ├── database/
│   │   └── assistente_casa.db  # Banco de dados SQLite auto-gerado
│   ├── __init__.py
│   └── config.py              # Configurações globais e de ambiente
├── services/
│   ├── __init__.py
│   ├── audio_service.py       # Captura de microfone e transcrição
│   ├── ai_service.py          # Integração com LLMs (Gemini/OpenAI)
│   └── db_service.py          # Conexão e persistência SQLite
├── app/
│   ├── templates/             # Futura interface web
│   ├── static/                # Arquivos estáticos
│   └── main.py                # Orquestrador do fluxo principal
├── requirements.txt
└── README.md
```

## Pré-requisitos

1. Python 3.10+
2. Chave de API da LLM configurada no arquivo `.env`.

## Instalação e Execução

1. Instale as dependências:
   ```bash
   pip install -r requirements.txt
   ```

2. Crie um arquivo `.env` na raiz do projeto:
   ```env
   GEMINI_API_KEY=sua_chave_aqui
   ```

3. Execute o assistente:
   ```bash
   python app/main.py
   ```
