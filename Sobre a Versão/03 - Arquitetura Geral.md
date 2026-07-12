# 03 - Arquitetura Geral

Este documento detalha a estrutura de diretórios, os módulos constituintes, suas responsabilidades específicas, o fluxo principal e as relações de dependências na **Versão 2 (V2)** do **Assistente Doméstico Inteligente**.

---

## 1. Organização das Pastas (Estrutura de Diretórios)

A árvore física de arquivos e pastas reais da Versão 2 apresenta-se da seguinte forma:

```text
assistente-domestico/
├── assets/                    # [NOVO] Pasta de armazenamento temporário de arquivos de voz (temp_voice.mp3)
├── app/
│   └── main.py                # Orquestrador do ciclo síncrono e fluxo de inicialização e compras
├── core/
│   ├── database/
│   │   └── assistente_casa.db # Banco de dados SQLite contendo o histórico de compras, itens e estoque
│   ├── __init__.py
│   └── config.py              # Centralização de configurações globais e leitura do .env
├── services/
│   ├── __init__.py
│   ├── ai_service.py          # Interface de comunicação com a API Google Gemini (compras multiestabelecimento)
│   ├── audio_service.py       # Captação de microfone com monitoramento de RMS e bips sonoros
│   ├── db_service.py          # Execução de comandos SQL de cabeçalho, detalhe e controle de estoque
│   ├── inventory_assistant.py # [NOVO] Assistente de estoque, cálculo de autonomia preditiva e intenções
│   └── voice_service.py       # [NOVO] Geração de fala usando edge-tts e reprodução com mixer do pygame
├── .env                       # Variáveis de ambiente locais (GEMINI_API_KEY)
├── requirements.txt           # Declarações de dependências oficiais do projeto
└── README.md                  # Documentação de alto nível para inicialização
```

---

## 2. Descrição dos Módulos e Suas Responsabilidades

### A. Orquestrador (`app/main.py`)
*   **Responsabilidade:** Conectar e sincronizar as etapas de execução da aplicação. Na V2, inicializa a varredura ativa de estoque expirado no banco, coordena a captura de voz de novas compras, submete-as à IA para parsing de lojas, passa cada item gerado pelo motor de estoque e, por fim, aciona a gravação relacional final.

### B. Serviço de Inventário (`services/inventory_assistant.py`)
*   **Responsabilidade:** Implementar as regras de negócio de estoque doméstico. Avalia se o estoque previsto terminou comparando a data atual com o ritmo médio de consumo de cada produto. Comanda a síntese e a captação de voz para fazer perguntas interativas ao usuário e atualiza a base com base nas 4 decisões da árvore conversacional (Confirmação, Negativa Zerado, Negativa Sem Consumo, Divergência de Quantidade).

### C. Serviço de Voz (`services/voice_service.py`)
*   **Responsabilidade:** Realizar a síntese de voz (TTS). Transforma strings de texto fornecidas pelo assistente em arquivos físicos temporários de áudio (`assets/temp_voice.mp3`) utilizando o modelo neural `pt-BR-AntonioNeural` do Microsoft Edge, reproduzindo-os na placa de som local e excluindo o arquivo de descarte ao terminar.

### D. Serviço de Áudio (`services/audio_service.py`)
*   **Responsabilidade:** Controlar o canal de gravação local do microfone. Realiza calibração de barulhos, emite bips sonoros e lê o fluxo físico em chunks binários, medindo o volume RMS da sala. Decide encerrar a captura após 5 segundos contínuos de silêncio real ou abortar a chamada caso o usuário permaneça em silêncio absoluto nos primeiros 15 segundos.

### E. Serviço de Banco de Dados (`services/db_service.py`)
*   **Responsabilidade:** Garantir o isolamento das chamadas SQL. Além de criar a estrutura básica relacional de compras, gerencia a tabela de `controle_consumo`, cria índices de otimização de busca rápida e expõe métodos utilitários genéricos de execução e consulta (`executar_comando`, `executar_consulta`, `executar_consulta_uma_linha`).

### F. Serviço de IA (`services/ai_service.py`)
*   **Responsabilidade:** Consumir os serviços do Gemini 2.5 Flash para processar despesas. Interpreta e separa itens comprados em estabelecimentos distintos no mesmo relato de voz, formatando-os em um JSON envelopado em uma lista chaveada por `"compras"`.

---

## 3. Ciclo de Execução da Aplicação (Fluxo Principal)

```
[Inicialização da Aplicação]
           │
           ▼
[main.py: Carrega serviços e abre conexão com o Banco]
           │
           ▼
[Passo 1: Varredura de Autonomia Expirada] ───────► Para cada item vencido no banco:
           │                                        - VoiceService: Pergunta via áudio se o estoque acabou.
           │                                        - AudioService: Ouve a resposta do usuário.
           │                                        - Gemini: Classifica a intenção (Sim/Não) e atualiza o banco.
           ▼
[Passo 2: Captura de Novas Compras] ──────────────► - AudioService: Ouve o relato geral de compras do usuário.
           │                                        - AIService: Converte áudio bruto em JSON com as lojas e itens.
           ▼
[Passo 3: Motor de Resíduos de Estoque] ──────────► Para cada item da nova compra:
           │                                        - Calcula se existe resíduo estimado na base.
           │                                        - Se houver, pergunta ao usuário se confirma a sobra de unidades.
           │                                        - Interpreta a intenção conversacional e grava o resíduo real.
           ▼
[Passo 4: Persistência Relacional] ───────────────► - Salva os cabeçalhos das compras e itens na base SQLite.
           │                                        - Associa os IDs relacionais e encerra a transação com segurança.
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
2.  **`InventoryAssistant`** acopla-se a:
    *   `DatabaseService` para ler/atualizar a tabela de consumo.
    *   `VoiceService` para falar as estimativas do sistema.
    *   `AudioService` para escutar e receber as respostas do usuário.
    *   `google.genai` para realizar classificação de intenções direto em texto.
3.  **`VoiceService`** depende de:
    *   `edge_tts` para geração de áudio por API externa.
    *   `pygame.mixer` para tocar o áudio através de hardware.
4.  **`AudioService`** consome:
    *   `speech_recognition` e `winsound` do Windows.

---

## Principais mudanças arquiteturais em relação à V1

As transformações arquiteturais que marcam a evolução para a Versão 2 são:

1.  **Surgimento da Camada Conversacional Ativa (Bidirecional):** Na V1, a comunicação de voz era exclusivamente de entrada (microfone -> texto). Na V2, o sistema passa a ser bidirecional, integrando síntese de voz (TTS) para questionar o usuário e escutar respostas de validação contextual, criando um laço fechado de conversação.
2.  **Introdução do Motor de Processamento Preditivo e Estatístico:** Adicionado o módulo `InventoryAssistant` que estima a autonomia residual de produtos residenciais com base em uma taxa dinâmica de consumo (ritmo médio de dias por unidade).
3.  **Refinamento do Parser da IA para Multiestabelecimento:** O módulo `ai_service.py` foi reestruturado para lidar com múltiplas transações de lojas em uma única chamada, dividindo a saída JSON em uma estrutura hierárquica complexa (`compras: []`), enquanto a V1 aceitava apenas um estabelecimento individual.
4.  **Evolução no Tratamento Binário de Áudio:** O `AudioService` abandonou a escuta passiva síncrona com temporizadores arbitrários da biblioteca padrão para usar leitura física direta de streams e cálculos de amplitude RMS de áudio, permitindo cortes automáticos inteligentes.
