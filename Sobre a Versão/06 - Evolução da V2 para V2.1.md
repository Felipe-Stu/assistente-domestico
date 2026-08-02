# 06 - Evolução da V2 para V2.1

Este documento estabelece o histórico oficial comparativo entre a Versão 2 (V2) e a Versão 2.1 (V2.1 - Patch de Correção 1) do **Assistente Doméstico Inteligente**, demonstrando as correções de estabilização do sistema e a nova infraestrutura de logging implementada.

---

## 1. Tabela Comparativa de Componentes e Serviços

Abaixo está o mapeamento detalhado das alterações introduzidas pelo Patch de Correção 1 em cada componente do sistema:

| Componente / Módulo | Situação na Versão 2 (V2) | Situação na Versão 2.1 (V2.1) | Tipo da Alteração | Impacto |
| :--- | :--- | :--- | :--- | :--- |
| **Orquestrador (`main.py`)** | Fluxo linear síncrono. Em caso de falha da API externa do Gemini (como erro 503), a execução quebrava e o sistema parava. Sem controle de logs em arquivo. | Adicionado tratamento robusto para o erro 503 (`ServiceUnavailableException`) com loop de reenvio de 5s, mantendo o áudio transcrito salvo, informando o usuário por voz ("Tráfego congestionado. Fazendo nova requisição.") e gravando logs. | **Melhoria** / **Correção** | Alta resiliência nas requisições. O assistente não falha mais caso o servidor do Gemini esteja congestionado, garantindo o processamento do comando. |
| **Serviço de IA (`ai_service.py`)** | Apenas realizava a chamada ao Gemini. Se houvesse erro, lançava exceções genéricas de conexão. | Mapeia explicitamente erros de indisponibilidade (503) lançando `ServiceUnavailableException` e limites de cota/tokens (429) lançando `TokenExhaustedException`. Registra atividades no logger. | **Correção** | Permite que o orquestrador identifique e trate de forma especializada e individual as falhas da API. |
| **Serviço de Log (`logger_service.py`)** | Inexistente. O rastreamento era feito via `logging` padrão direcionado apenas para o console. | Módulo criado para gerenciar logs persistentes estruturados no disco. Salva logs da orquestração em `Logs/main/main_log.txt` e de cada assistente em `Logs/[nome]/log.txt`, com divisores de data. | **Novo** | Rastreabilidade e depuração avançadas de execução do sistema em longo prazo. |
| **Serviço de Áudio (`audio_service.py`)** | Gerenciava captação de voz analógica e bips, mas os registros eram apenas de terminal. | Integrado ao `logger_service` para persistir o fluxo de estados do gravador, calibrações de som e RMS de áudio. | **Ajuste** | Histórico detalhado do uso do microfone no arquivo de log do assistente de áudio. |
| **Serviço de Voz (`voice_service.py`)** | Realizava síntese e reprodução síncrona sem registrar as falas em arquivos de logs. | Integrado ao `logger_service` para registrar strings de texto enviadas ao TTS e status de inicialização e reprodução. | **Ajuste** | Histórico das respostas dadas pelo assistente salvo no log da voz. |
| **Banco de Dados (`db_service.py`)** | Persistência física sem registros de queries ou conexões no log. | Integrado ao `logger_service` para registrar queries de escrita/leitura e status da conexão com SQLite. | **Ajuste** | Transações e estados de persistência totalmente rastreáveis. |
| **Assistente de Compras (`shopping_assistant.py`)** | Processava os prompts de compras multiestabelecimento e persistia os dados sem logs físicos. | Integrado ao `logger_service` para registrar os prompts de compras e número de itens e lojas inseridos no banco. | **Ajuste** | Facilita a auditoria de quais produtos foram extraídos das falas do usuário. |
| **Assistente de Inventário (`inventory_assistant.py`)** | Executava regras de consumo preditivo sem logs físicos. | Integrado ao `logger_service` para gravar em arquivo a varredura inicial de itens vencidos, respostas do usuário e ajustes no estoque. | **Ajuste** | Visibilidade completa de como a IA classificou as respostas do usuário e calculou o ritmo de consumo. |
| **Diretório de Logs (`Logs/`)** | Inexistente. | Diretório criado automaticamente na raiz do projeto para abrigar os logs subdivididos por módulos. | **Novo** | Organização física de dados de auditoria técnica. |

---

## 2. Resumo Executivo (Patch de Correção 1)

### A. Principais Correções Realizadas
*   **Tratamento de Indisponibilidade de API (Erro 503):** Mitigação de falhas de rede no Gemini. Quando a API falha por alta demanda, o sistema emite um alerta verbal informando sobre o congestionamento e inicia uma contagem regressiva de 5 segundos em loop até que a comunicação seja restabelecida com sucesso, processando a transcrição de voz salva.
*   **Gestão de Cotas de Tokens (Erro 429):** Mapeamento do limite de requisições (`TokenExhaustedException`) permitindo capturar o estouro de cota e alertar o usuário apropriadamente.

### B. Principais Melhorias
*   **Infraestrutura Transversal de Log:** Implementação do módulo `logger_service.py` que centraliza todos os logs do assistente. Em vez de despejar tudo em uma saída única de terminal, o sistema cria automaticamente a pasta `Logs/` e segmenta as informações de forma limpa: logs de fluxo de negócios vão para a pasta `main/` e logs operacionais internos de hardware/APIs vão para a pasta de seus respectivos serviços (ex: `audio_service`, `voice_service`, `ai_service`, etc.).
*   **Cabeçalhos Cronológicos Automáticos:** Cada arquivo de log recebe um divisor com a data correspondente na primeira inicialização diária do módulo (ex: `**************************** main_02/08/2026 ****************************`), organizando os logs de forma cronológica.

### C. Componentes Afetados
*   **Afetados Diretamente (Código alterado para suportar resiliência ou log):**
    *   `app/main.py` (Lógica de retry do erro 503 e instanciação de logs gerais).
    *   `services/ai_service.py` (Mapeamento de exceções 503/429 e logs).
    *   `services/audio_service.py`, `services/voice_service.py`, `services/db_service.py`, `services/shopping_assistant.py`, `services/inventory_assistant.py` (Integração e chamadas ao logger).
*   **Criados (Novos no projeto):**
    *   `services/logger_service.py` (Componente de CustomLogger).
    *   Pasta `Logs/` na raiz do projeto.

### D. Impacto para o Usuário
*   **Experiência Conversacional Ininterrupta:** O assistente doméstico tornou-se muito mais robusto a instabilidades externas na internet. Caso o Gemini falhe temporariamente, o usuário não precisa repetir o comando inteiro; o assistente explica verbalmente a lentidão e resolve a requisição sozinho assim que o canal liberar.

### E. Impacto para Manutenção e Arquitetura
*   **Manutenibilidade Elevada:** A introdução do logger estruturado facilita drasticamente a identificação de anomalias no ambiente de produção. Caso ocorra uma falha de calibração do microfone, erros de banco de dados ou incoerências na classificação de intenções, os mantenedores podem consultar diretamente os arquivos de log isolados de cada assistente para auditoria.
*   **Baixo Impacto Arquitetural:** O `logger_service.py` funciona como uma utilidade transversal injetada nos módulos existentes sem alterar as regras de negócios da gestão preditiva de estoque ou o processamento de áudio analógico. A arquitetura de camadas herdada da Versão 2 permanece íntegra e equivalente.
