# 06 - Evolução da V1 para V2

Este documento estabelece o histórico oficial comparativo entre a Versão 1 (V1) e a Versão 2 (V2) do **Assistente Doméstico Inteligente**, demonstrando as evoluções nos módulos de software, as alterações na lógica e o avanço da arquitetura de sistemas.

---

## 1. Tabela Comparativa de Componentes e Serviços

Abaixo está o mapeamento detalhado da transição evolutiva de cada componente do sistema:

| Componente / Módulo | Situação na Versão 1 (V1) | Situação na Versão 2 (V2) | Tipo da Alteração |
| :--- | :--- | :--- | :--- |
| **Orquestração (`main.py`)** | Inicialização sequencial linear e síncrona: captura de áudio simples, chamada do Gemini e salvamento direto. | Coordena fluxo bidirecional de voz, aciona varredura preditiva de estoque expirado e intercepta itens comprados. | **Alterado** |
| **Módulo de Estoque (`inventory_assistant.py`)** | Inexistente (estoque não era mapeado). | Implementa motor preditivo de resíduos de estoque e árvore de decisão conversacional em 4 vias de confirmação. | **Novo** |
| **Módulo de Voz (`voice_service.py`)** | Inexistente (sistema era silencioso). | Síntese de voz neural ativa (TTS) integrada via Edge TTS e player local com mixer Pygame. | **Novo** |
| **Configurações (`config.py`)** | Carregava caminhos básicos de diretórios, chaves de API e tempo fixo de gravação. | Carrega as mesmas variáveis da V1. Adicionada a pasta `assets` para manipulação de áudios temporários. | **Alterado** |
| **Gravação de Áudio (`audio_service.py`)** | Escuta passiva com tempo fixo do microfone utilizando SpeechRecognition puro, sem bips de feedback. | Escuta monitorando RMS em chunks binários, corte inteligente por silêncio (5s), travas de segurança (15s) e bips (`winsound`). | **Alterado** |
| **Parsing de Compras (`ai_service.py`)** | Instruía o Gemini a gerar JSON de compras focando em apenas um estabelecimento. | Instruções refinadas no prompt para separar compras de múltiplos estabelecimentos em uma única lista JSON (`compras`). | **Alterado** |
| **Banco de Dados (`db_service.py`)** | Inicialização simples e gravação das tabelas relacionais de compras e itens. | Adicionada tabela `controle_consumo`, índices de otimização rápidos e métodos genéricos de execução e consulta SQL. | **Alterado** |
| **Tabela `compras`** | Criada sem restrição NOT NULL para nome do comércio. | Mantida idêntica à V1. | **Mantido** |
| **Tabela `itens_compra`** | Continha colunas de marcas, quantidades, valores e categoria sem uso. | Mantida a estrutura e passa a gravar a categoria do produto (preparada na V1). | **Mantido** |
| **Tabela `controle_consumo`** | Inexistente. | Nova tabela para rastrear o ritmo de consumo dinâmico, resíduos de estoque e validações. | **Novo** |
| **Índice `idx_estoque_ativo`** | Inexistente. | Otimização de consultas rápidas para status de estoque ativo na inicialização. | **Novo** |
| **Pasta `assets/`** | Inexistente. | Criada dinamicamente para servir de descarte de arquivos de áudio neural `.mp3` temporários. | **Novo** |
| **Simulação (Fallback)** | Simulação estática de compras no Mercado Estrela. | Simulação estática de compras no restaurante Costela de Chão. | **Alterado** |

---

## 2. Resumo Executivo da Evolução

### A. Principais Evoluções
*   **Conversação Ativa (Sistemas de Voz Interativos):** O projeto deixou de ser um utilitário de entrada estática de dados por comando de voz para tornar-se um assistente conversacional ativo, capaz de falar com o usuário, propor estimativas baseadas em análises de banco e escutar confirmações lógicas contextuais.
*   **Automatização de Inventário Preditivo:** O sistema passa a controlar a quantidade residual de mantimentos no domicílio de forma preditiva, cruzando o tempo decorrido desde a última compra com o ritmo médio de uso, calculando estimativas sem exigir digitação de dados pelo usuário.

### B. Impacto das Mudanças
*   **Qualidade da Experiência do Usuário (UX):** A adição de bips de início/fim e corte por silêncio reduz gargalos onde o usuário esquecia o microfone gravando, poupando largura de banda e tempo de processamento de rede.
*   **Robustez de Hardware:** A detecção cirúrgica baseada em amplitude de volume RMS isola ruídos contínuos do computador (coolers) de forma mais eficiente do que calibrações passivas simples.

### C. Benefícios Arquiteturais
*   **Isolamento e Reusabilidade:** O assistente de inventário não acessa APIs de voz ou gravação diretamente; ele consome interfaces expostas (`VoiceService`, `AudioService` e `DatabaseService`), mantendo o princípio de responsabilidade única.
*   **Baixo Acoplamento Temporal:** A comunicação com APIs externas que exigem rotinas assíncronas (`edge-tts`) está isolada em sua própria camada de serviço, de forma que o fluxo orquestrador principal em `main.py` permanece inteiramente síncrono e de fácil leitura.

### D. Crescimento da Complexidade do Sistema
*   O sistema dobrou o número de serviços ativos e tabelas relacionais. A introdução de rotinas assíncronas (`asyncio`) coexistindo com métodos síncronos adicionou complexidade no ciclo de vida de reprodução de áudio, exigindo manipulação física e liberação correta de recursos de disco (remoção de arquivos temporários).

### E. Possíveis Pontos de Atenção para Futuras Versões
1.  **Sincronização de Esquema do Banco:** Conforme pontuado na análise do módulo de engenharia, a instrução SQL de criação da tabela `controle_consumo` em `db_service.py` não reflete as colunas reais `ultima_qtd_comprada` e `quantidade_residual_esgotada` exigidas pelo motor de inventário, o que causará travamento em novas instalações.
2.  **Volume de Arquivos Temporários:** Em caso de travamento inesperado do mixer de áudio durante a reprodução, o método de exclusão do arquivo temporário MP3 pode ser pulado, deixando resíduos em disco.
3.  **Dependências Ocultas:** As bibliotecas `pygame` e `edge-tts` são importadas dinamicamente mas não estão declaradas no arquivo `requirements.txt`, o que prejudica a instalabilidade direta do projeto por novos desenvolvedores.
