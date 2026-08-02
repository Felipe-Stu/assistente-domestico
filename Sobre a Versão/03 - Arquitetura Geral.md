# 03 - Arquitetura Geral

Este documento detalha a estrutura de diretórios, os módulos constituintes, suas responsabilidades específicas, o fluxo principal e as relações de dependências na **Versão 2.1 (V2.1 - Patch de Correção 1)** do **Assistente Doméstico Inteligente**.

> [!NOTE]
> A arquitetura permanece equivalente à documentada na Versão 2, exceto pela introdução de um serviço transversal de logs locais (`logger_service.py`) e pela lógica de retry no orquestrador principal para lidar com indisponibilidades temporárias da API do Gemini.

---

## 1. Organização das Pastas (Estrutura de Diretórios)

A árvore física de arquivos e pastas reais da Versão 2.1 apresenta-se da seguinte forma:

```text
assistente-domestico/
├── assets/                    # Pasta de armazenamento temporário de arquivos de voz (temp_voice.mp3)
├── app/
│   └── main.py                # Orquestrador do ciclo síncrono, fluxo de inicialização, compras e retry do Gemini
├── core/
│   ├── database/
│   │   └── assistente_casa.db # Banco de dados SQLite contendo o histórico de compras, itens e estoque
│   ├── __init__.py
│   └── config.py              # Centralização de configurações globais e leitura do .env
├── Logs/                      # [NOVO] Pasta contendo arquivos de log gerados dinamicamente
│   ├── main/
│   │   └── main_log.txt       # Log geral da orquestração do sistema
│   └── [nome_do_assistente]/
│       └── log.txt            # Log individualizado do serviço correspondente
├── services/
│   ├── __init__.py
│   ├── ai_service.py          # Interface de comunicação com a API Google Gemini (compras e classificação)
│   ├── audio_service.py       # Captação de microfone com monitoramento de RMS e bips sonoros
│   ├── db_service.py          # Execução de comandos SQL de cabeçalho, detalhe e controle de estoque
│   ├── inventory_assistant.py # Assistente de estoque, cálculo de autonomia preditiva e intenções
│   ├── logger_service.py      # [NOVO] CustomLogger transversal do sistema para persistência de logs
│   └── voice_service.py       # Geração de fala usando edge-tts e reprodução com mixer do pygame
├── .env                       # Variáveis de ambiente locais (GEMINI_API_KEY)
├── requirements.txt           # Declarações de dependências oficiais do projeto
└── README.md                  # Documentação de alto nível para inicialização
```

---

## 2. Descrição dos Módulos e Suas Responsabilidades

### A. Orquestrador (`app/main.py`)
*   **Responsabilidade:** Conectar e sincronizar as etapas de execução da aplicação. Na V2.1, inicializa a varredura ativa de estoque expirado, coordena a captura de voz de novas compras e o parsing de lojas. Implementa o loop resiliente para erros HTTP 503 (Serviço Indisponível) no Gemini, salvando a transcrição e fazendo novas tentativas a cada 5 segundos. Registra as transições e resultados no logger geral.

### B. Serviço de Inventário (`services/inventory_assistant.py`)
*   **Responsabilidade:** Implementar as regras de negócio de estoque doméstico. Avalia se o estoque previsto terminou comparando a data atual com o ritmo médio de consumo de cada produto. Comanda a síntese e a captação de voz para fazer perguntas interativas ao usuário e atualiza a base com base nas 4 decisões da árvore conversacional. Registra suas operações detalhadamente no seu arquivo de log específico.

### C. Serviço de Voz (`services/voice_service.py`)
*   **Responsabilidade:** Realizar a síntese de voz (TTS). Transforma strings de texto fornecidas pelo assistente em arquivos físicos temporários de áudio (`assets/temp_voice.mp3`) utilizando o modelo neural `pt-BR-AntonioNeural` do Microsoft Edge, reproduzindo-os na placa de som local e excluindo o arquivo de descarte ao terminar. Escreve suas ações no logger do assistente.

### D. Serviço de Áudio (`services/audio_service.py`)
*   **Responsabilidade:** Controlar o canal de gravação local do microfone. Realiza calibração de barulhos, emite bips sonoros e lê o fluxo físico em chunks binários, medindo o volume RMS da sala. Decide encerrar a captura após 5 segundos contínuos de silêncio real ou abortar a chamada caso o usuário permaneça em silêncio absoluto nos primeiros 15 segundos. Registra atividades no logger de áudio.

### E. Serviço de Banco de Dados (`services/db_service.py`)
*   **Responsabilidade:** Garantir o isolamento das chamadas SQL. Além de criar a estrutura básica relacional de compras, gerencia a tabela de `controle_consumo`, cria índices de otimização de busca rápida e expõe métodos utilitários genéricos de execução e consulta. Registra transações no logger do banco.

### F. Serviço de IA (`services/ai_service.py`)
*   **Responsabilidade:** Consumir os serviços do Gemini 2.5 Flash para processar despesas e classificar intenções. Interpreta e separa itens comprados em estabelecimentos distintos no mesmo relato de voz. Trata exceções de limites de cota (429) e indisponibilidade de serviço (503). Registra o status de envio e retorno da API no logger de IA.

### G. Serviço de Log (`services/logger_service.py`)
*   **Responsabilidade:** Centralizar e estruturar os registros de execução em disco. Cria de forma autônoma a estrutura de diretórios e arquivos de logs (`Logs/`), garante a inclusão de um cabeçalho diário no primeiro registro de cada dia e oferece métodos para gravação de log geral (`log_geral`) e de assistentes individuais (`log_assistente`).

---

## 3. Ciclo de Execução da Aplicação (Fluxo Principal)

```
[Inicialização da Aplicação]
           │
           ▼
[main.py: Carrega serviços, abre banco e grava log de inicialização]
           │
           ▼
[Passo 1: Varredura de Autonomia Expirada] ───────► Para cada item vencido no banco:
           │                                        - VoiceService: Pergunta via áudio se o estoque acabou.
           │                                        - AudioService: Ouve a resposta do usuário.
           │                                        - Gemini: Classifica a intenção (Sim/Não) e atualiza o banco.
           ▼
[Passo 2: Captura de Novas Compras] ──────────────► - AudioService: Ouve o relato geral de compras do usuário.
           │
           ▼
[Passo 3: Parsing da Compra com Retry 503] ◄──────► Se o Gemini retornar erro 503 (Indisponível):
           │                                        - VoiceService: Avisa por voz sobre congestionamento de tráfego.
           │                                        - Orquestrador: Aguarda 5 segundos e tenta novamente com o texto salvo.
           ▼
[Passo 4: Motor de Resíduos de Estoque] ──────────► Para cada item da nova compra:
           │                                        - Calcula se existe resíduo estimado na base.
           │                                        - Se houver, pergunta ao usuário se confirma a sobra de unidades.
           │                                        - Interpreta a intenção conversacional e grava o resíduo real.
           ▼
[Passo 5: Persistência Relacional] ───────────────► - Salva os cabeçalhos das compras e itens na base SQLite.
           │                                        - Associa os IDs relacionais e grava logs de finalização de fluxo.
           ▼
[Fim da Execução]
```

---

## 4. Dependências e Acoplamento de Componentes

1.  **`main.py`** atua como hub principal e acopla-se a:
    *   `DatabaseService` para conexão.
    *   `AudioService` para gravação de compras.
    *   `ai_service.py` para estruturação inteligente das compras.
    *   `InventoryAssistant` para verificação de estoques e interceptação de itens comprados.
    *   `logger` (`logger_service.py`) para registrar eventos do fluxo geral de orquestração.
2.  **`InventoryAssistant`** acopla-se a:
    *   `DatabaseService` para ler/atualizar a tabela de consumo.
    *   `VoiceService` para falar as estimativas do sistema.
    *   `AudioService` para escutar e receber as respostas do usuário.
    *   `google.genai` para realizar classificação de intenções direto em texto.
    *   `logger` para gravar seu log especializado de inventário.
3.  **`VoiceService`** depende de:
    *   `edge_tts` para geração de áudio por API externa.
    *   `pygame.mixer` para tocar o áudio através de hardware.
    *   `logger` para logar o texto enviado à síntese.
4.  **`AudioService`** consome:
    *   `speech_recognition` e `winsound` do Windows.
    *   `logger` para logar volume RMS capturado e status de calibração.
5.  **`AIService`** depende de:
    *   `google.genai` para consumo da API do Gemini.
    *   `logger` para logar as interações de prompt e resposta da IA.
6.  **`DatabaseService`** depende de:
    *   `sqlite3` para persistência física.
    *   `logger` para gravar o log de queries e abertura do banco de dados.
