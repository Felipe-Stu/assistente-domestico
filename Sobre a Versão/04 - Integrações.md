# 04 - Integrações

Este documento identifica e mapeia todos os fluxos de integração e conexões externas ou de hardware que o **Assistente Doméstico Inteligente (V2)** realiza para viabilizar suas funções.

---

## 1. APIs e Serviços Web Externos (SaaS)

### A. Google Gemini API (Modelagem de IA)
*   **Origem:** [ai_service.py](file:///e:/Agente%20IA/assistente-domestico/services/ai_service.py) e [inventory_assistant.py](file:///e:/Agente%20IA/assistente-domestico/services/inventory_assistant.py).
*   **Destino:** Servidores de LLM da Google Cloud.
*   **Finalidade:**
    1.  *Processamento de Compras:* Transformar a transcrição de novas despesas em uma lista de JSON estruturada por estabelecimento.
    2.  *Classificação de Intenção:* Analisar as falas curtas de confirmação do usuário e categorizá-las em um dos 4 cenários lógicos do inventário (Confirmação, Zera Estoque, Sem Consumo, Ajuste de Quantidade).
*   **Tecnologia Utilizada:** Biblioteca `google-genai` e requisições HTTP seguras (HTTPS).

### B. Google Speech Recognition API (Transcrição de Fala)
*   **Origem:** [audio_service.py](file:///e:/Agente%20IA/assistente-domestico/services/audio_service.py).
*   **Destino:** Servidores de Reconhecimento de Voz do Google.
*   **Finalidade:** Converter os buffers de áudio gravados pelo microfone local em texto bruto para processamento.
*   **Tecnologia Utilizada:** Biblioteca `speech_recognition` realizando chamadas HTTP síncronas para a API web pública.

### C. Microsoft Edge TTS API (Síntese de Voz)
*   **Origem:** [voice_service.py](file:///e:/Agente%20IA/assistente-domestico/services/voice_service.py).
*   **Destino:** Servidores de Voz Neural do Microsoft Edge (serviço gratuito de TTS).
*   **Finalidade:** Gerar o arquivo físico MP3 de voz a partir de strings textuais enviadas pelo assistente de inventário.
*   **Tecnologia Utilizada:** Biblioteca assíncrona `edge_tts` efetuando conexões web seguras e baixando o stream de áudio.

---

## 2. Integração com Banco de Dados

### A. Base Relacional Local SQLite
*   **Origem:** [db_service.py](file:///e:/Agente%20IA/assistente-domestico/services/db_service.py).
*   **Destino:** Arquivo físico de banco de dados `core/database/assistente_casa.db`.
*   **Finalidade:** Persistir registros de compras, itens e gerenciar a tabela `controle_consumo` que rastreia os níveis de estoque e a taxa média de uso de cada mercadoria.
*   **Tecnologia Utilizada:** Módulo nativo `sqlite3` do Python.

---

## 3. Comunicação por Arquivos Locais

### A. Arquivo de Configuração de Variáveis de Ambiente (.env)
*   **Origem:** Raiz do projeto (arquivo `.env`).
*   **Destino:** Módulo de configurações [config.py](file:///e:/Agente%20IA/assistente-domestico/core/config.py).
*   **Finalidade:** Exportar chaves privadas (`GEMINI_API_KEY`) e limites de tempo de áudio para a memória do processo da aplicação.
*   **Tecnologia Utilizada:** Biblioteca `python-dotenv`.

### B. Arquivos Temporários de Voz (MP3)
*   **Origem:** [voice_service.py](file:///e:/Agente%20IA/assistente-domestico/services/voice_service.py).
*   **Destino:** Pasta `assets/temp_voice.mp3` no disco local.
*   **Finalidade:** Armazenar temporariamente o arquivo sintetizado para que o player de som possa carregá-lo e reproduzi-lo no hardware. O arquivo é excluído pelo código imediatamente após a conclusão da fala.
*   **Tecnologia Utilizada:** Módulo `os` do Python para escrita e remoção de arquivo.

---

## 4. Integração com Placa de Som e Serviços do Sistema Operacional

### A. Dispositivo de Reprodução de Áudio (Mixer)
*   **Origem:** [voice_service.py](file:///e:/Agente%20IA/assistente-domestico/services/voice_service.py).
*   **Destino:** Placa de som do sistema operacional (Alto-falantes / Fones).
*   **Finalidade:** Reproduzir as respostas por voz neural geradas pelo assistente para conversação bidirecional.
*   **Tecnologia Utilizada:** Módulo `pygame.mixer` da biblioteca pygame.

### B. Dispositivo de Entrada de Áudio (Microfone)
*   **Origem:** [audio_service.py](file:///e:/Agente%20IA/assistente-domestico/services/audio_service.py).
*   **Destino:** Placa de som do sistema operacional (Microfone).
*   **Finalidade:** Capturar em tempo real a fala do usuário para fins de gravação de comandos ou confirmações.
*   **Tecnologia Utilizada:** Biblioteca `PyAudio` vinculada à API do microfone do sistema operacional Windows.

### C. Alertas do Sistema Operacional (Bips Sonoros)
*   **Origem:** [audio_service.py](file:///e:/Agente%20IA/assistente-domestico/services/audio_service.py).
*   **Destino:** Alto-falante interno da placa-mãe ou saída padrão do Windows.
*   **Finalidade:** Emitir frequências senoidais em hertz para notificar visualmente e sonoramente o usuário sobre a mudança de estado do gravador.
*   **Tecnologia Utilizada:** Biblioteca nativa `winsound` do Windows (`winsound.Beep`).

---

## 5. Categorias Não Identificadas Nesta Versão

*   **APIs REST Locais / Servidores HTTP:** "Não identificado nesta versão." (O sistema roda estritamente via linha de comando).
*   **WebSocket:** "Não identificado nesta versão."
*   **Subprocessos / IPC:** "Não identificado nesta versão." (Todas as integrações operam de forma direta sob a mesma thread do processo Python principal).
*   **Modelos de IA Locais:** "Não identificado nesta versão."

---

## Novas integrações da V2

As seguintes integrações foram introduzidas na transição para a Versão 2:
1.  **API Microsoft Edge TTS:** Interface externa para sintetizar textos em arquivos de áudio neural.
2.  **Dispositivo de Reprodução de Áudio (Mixer Pygame):** Canal físico de saída de som para tocar as falas sintetizadas.
3.  **Winsound Beep API:** Controle de bips sonoros locais do sistema operacional Windows.
4.  **Sistema de Arquivos para Áudios Temporários:** Gravação e remoção programática de arquivos MP3 em tempo de execução na pasta `assets`.
