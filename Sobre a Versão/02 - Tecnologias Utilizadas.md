# 02 - Tecnologias Utilizadas

Este documento detalha o ecossistema tecnológico empregado na **Versão 2.1 (V2.1 - Patch de Correção 1)** do **Assistente Doméstico Inteligente**, comparando o histórico da versão V1 com a V2/V2.1 para registrar a evolução da pilha de software.

> [!NOTE]
> Não houve alteração nas tecnologias utilizadas em relação à Versão 2. 
> Todos os novos recursos da Versão 2.1 (como o tratamento resiliente do Gemini e a persistência de logs locais) foram desenvolvidos utilizando as tecnologias já existentes e bibliotecas padrão do Python (como `time`, `os` e `datetime`).

---

## 1. Mapeamento das Tecnologias

### Linguagem Principal
*   **Python (v3.10+)**
    *   **Finalidade:** Linguagem de desenvolvimento de todo o sistema.
    *   **Onde é utilizada:** Em todos os scripts do projeto.
    *   **Introduzido em:** **V1** (Mantido na V2/V2.1).

---

### Inteligência Artificial (IA)
*   **Google Gemini API (Modelo `gemini-2.5-flash`)**
    *   **Finalidade:** Realizar a estruturação complexa de textos brutos em listas de compras JSON e classificar as intenções de voz do usuário nos fluxos de confirmação de inventário.
    *   **Onde é utilizada:** Em [ai_service.py](file:///e:/Agente%20IA/assistente-domestico/services/ai_service.py) (para processar compras) e em [inventory_assistant.py](file:///e:/Agente%20IA/assistente-domestico/services/inventory_assistant.py) (para classificar intenções).
    *   **Introduzido em:** **V1** (Expandido na V2/V2.1 para classificação de intenção do usuário em 4 vias).

*   **SDK `google-genai` (Versão >= 0.8.0)**
    *   **Finalidade:** Biblioteca cliente para comunicação direta e nativa com os endpoints Gemini.
    *   **Onde é utilizada:** Nos módulos [ai_service.py](file:///e:/Agente%20IA/assistente-domestico/services/ai_service.py) e [inventory_assistant.py](file:///e:/Agente%20IA/assistente-domestico/services/inventory_assistant.py).
    *   **Introduzido em:** **V1** (Mantido na V2/V2.1).

---

### Processamento e Síntese de Áudio
*   **SpeechRecognition (Versão >= 3.10.0)**
    *   **Finalidade:** Biblioteca utilizada para calibrar ruído ambiente e capturar o buffer analógico do microfone.
    *   **Onde é utilizada:** No serviço de captação [audio_service.py](file:///e:/Agente%20IA/assistente-domestico/services/audio_service.py).
    *   **Introduzido em:** **V1** (Mantido na V2/V2.1).

*   **PyAudio (Versão >= 0.2.14)**
    *   **Finalidade:** Fornecer os bindings de áudio de baixo nível do sistema operacional para leitura física do fluxo do microfone.
    *   **Onde é utilizada:** Utilizado indiretamente pelo `SpeechRecognition` em [audio_service.py](file:///e:/Agente%20IA/assistente-domestico/services/audio_service.py).
    *   **Introduzido em:** **V1** (Mantido na V2/V2.1).

*   **edge-tts**
    *   **Finalidade:** Biblioteca de geração de fala (Text-to-Speech) que acessa de forma assíncrona os modelos neurais de voz da Microsoft Edge, gerando arquivos MP3 sob demanda de alta qualidade.
    *   **Onde é utilizada:** Importada dinamicamente no serviço de voz [voice_service.py](file:///e:/Agente%20IA/assistente-domestico/services/voice_service.py).
    *   **Introduzido em:** **V2** (Mantido na V2.1).

*   **pygame (Módulo `pygame.mixer`)**
    *   **Finalidade:** Inicializar o mixer de som local para reproduzir os arquivos de voz neural gerados temporariamente, aguardando o término da reprodução sem cortar a fala.
    *   **Onde é utilizada:** Inicializado e executado em [voice_service.py](file:///e:/Agente%20IA/assistente-domestico/services/voice_service.py).
    *   **Introduzido em:** **V2** (Mantido na V2.1).

*   **winsound (Biblioteca Padrão do Windows)**
    *   **Finalidade:** Emitir alertas sonoros baseados na frequência do sistema (bips) para dar feedback auditivo ao usuário sobre o status do microfone (início da escuta, término e aviso de fim de tempo).
    *   **Onde é utilizada:** Utilizado no módulo de gravação de áudio [audio_service.py](file:///e:/Agente%20IA/assistente-domestico/services/audio_service.py).
    *   **Introduzido em:** **V2** (Mantido na V2.1).

---

### Banco de Dados e Persistência
*   **SQLite**
    *   **Finalidade:** Banco de dados relacional embarcado em arquivo físico para armazenamento estruturado das compras, itens e tabelas de controle de inventário.
    *   **Onde é utilizada:** O arquivo reside em `core/database/assistente_casa.db`.
    *   **Introduzido em:** **V1** (Mantido na V2/V2.1, com adição de tabelas e índices).

*   **sqlite3 (Biblioteca Padrão do Python)**
    *   **Finalidade:** Driver oficial de conexão com o banco SQLite.
    *   **Onde é utilizada:** Utilizado integralmente no arquivo de acesso a dados [db_service.py](file:///e:/Agente%20IA/assistente-domestico/services/db_service.py).
    *   **Introduzido em:** **V1** (Mantido na V2/V2.1, expandido com novas funções genéricas de escrita/leitura).

---

### Utilitários e Bibliotecas Auxiliares (Standard Library)
*   **`python-dotenv` (Versão >= 1.0.1):** Ler credenciais locais do arquivo `.env` (**V1**).
*   **`asyncio`:** Suportar a execução assíncrona necessária para a geração e execução do Edge TTS (**V2**).
*   **`math` & `struct`:** Utilizados para desempacotar o buffer binário de áudio e calcular matematicamente o nível de volume RMS, evitando que ruídos estáticos impeçam o corte por silêncio (**V2**).
*   **`time`:** Controlar temporizações físicas do loop, intervalos de bips e esperas de nova requisição em caso de erro 503 (**V2**, expandido na V2.1).
*   **`pathlib` & `os`:** Gerenciamento seguro de caminhos de arquivos e criação dinâmica de diretórios de assets e logs (**V1**, estendido na V2/V2.1).
*   **`json` & `datetime`:** Parser de estruturas e manipulação de datas de compras (**V1**).

---

## 2. Status de Outras Categorias

*   **Interface Gráfica:** **Planejado**. Embora os diretórios `app/templates` e `app/static` estejam mapeados em documentação de alto nível para interfaces web futuras, nenhuma biblioteca como Flask, FastAPI ou Tkinter foi implementada.
*   **OCR (Reconhecimento Óptico de Caracteres) / Bibliotecas de Visão:** **Não identificado nesta versão**.
*   **Modelos de IA Locais (Whisper Local / Ollama):** **Não identificado nesta versão**. O sistema consome exclusivamente recursos de processamento via nuvem pelas APIs da Google (Gemini) e Microsoft (Edge TTS).
