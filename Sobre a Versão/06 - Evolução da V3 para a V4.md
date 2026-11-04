# 06 - Evolução da V3 para a V4

Este documento registra o histórico comparativo entre a **Versão 3 (V3)** e a **Versão 4 (V4)** do **Assistente Doméstico Inteligente**, com as mudanças de arquitetura, as decisões tomadas e o que ficou pendente.

---

## 1. Contexto da Evolução

A V3 trouxe o LLM local como camada primária, mas o uso continuava dependente de microfone e linha de comando, o que dificultava testes. A persistência era apenas relacional, sem memória semântica.

A **V4 muda a forma de interação e de memória**: o chat de texto passa a ser o modo principal, com voz sob demanda, e um banco vetorial local passa a complementar o SQLite. A versão também abre espaço para uma segunda IA local, voltada à programação, e para a análise de projetos.

---

## 2. Tabela Comparativa de Componentes

| Componente / Módulo | Situação na V3 | Situação na V4 | Tipo da Alteração |
| :--- | :--- | :--- | :--- |
| **Interface** | Linha de comando e voz | Electron com chat, modo voz, mudo e terminal de debug | Novo |
| **Runtime (`app/main.py`)** | Fluxo principal com `GerenciadorDeSessao` | `AssistenteRuntime` com fila de eventos e threads para stdin, microfone e varredura | Reestruturado |
| **Comunicação** | Processo único | JSON por stdin/stdout entre Electron e Python | Novo |
| **Inicialização** | Dependia do hardware de áudio | Text-First: voz ativada pelo usuário | Reestruturado |
| **Voz e áudio** | Inicialização direta | Construtores leves e `inicializar()` sob demanda | Modificado |
| **Banco de dados** | SQLite | SQLite + ChromaDB em `core/database/chroma_db/` | Expandido |
| **Serviços vetoriais** | **Inexistentes** | Pacote `services/vector/` com 5 serviços | Novo |
| **Compras** | Grava no SQLite | Grava no SQLite e vetoriza os itens no ChromaDB | Expandido |
| **Inventário** | Fala e escuta diretamente | Usa voz compartilhada, respeita o modo texto e ganha `consultar_estoque()` | Modificado |
| **Provedores LLM** | Gemma local e Gemini | Modelo ativo em memória, Modo Qwen e liberação de VRAM | Expandido |
| **Orquestrador** | Classificação por LLM | Comandos determinísticos antes do LLM e novos contextos `programacao` e `projetos` | Expandido |
| **Análise de projetos** | **Inexistente** | Skill ProjectAnalyzer, 100% local | Novo |
| **Testes** | Sem suíte | 70 testes: ProjectAnalyzer, orquestrador e Fase 1 | Novo |
| **Scripts** | **Inexistentes** | Migração, reconstrução, validação e inspeção vetorial; análise de projetos | Novo |

---

## 3. Arquivos Adicionados

| Área | Arquivos |
| :--- | :--- |
| Electron | `main.js`, `preload.js`, `renderer.js`, `index.html`, `index.css`, `package.json`, `package-lock.json` |
| Vetorial | `services/vector/` (5 serviços e `__init__.py`) |
| Skill | `services/project_analyzer/` (9 módulos e `__init__.py`) |
| Scripts | `scripts/inspect_vector_database.py`, `migrate_vector_database.py`, `rebuild_embeddings.py`, `validate_vector_database.py`, `analyze_project.py` |
| Testes | `tests/test_project_analyzer.py`, `tests/test_gemma_service.py`, `tests/test_fase1.py` |
| Roteamento | `services/intent_router.py` |

---

## 4. Correções Aplicadas

*   `.gitignore.txt` renomeado para `.gitignore`; banco, caches e logs saíram do versionamento.
*   `requirements.txt` passou a usar `google-genai`, o SDK realmente importado, e ganhou `edge-tts` e `pygame`.
*   `db_service.py` perdeu o import exclusivo do Windows e passou a criar `historico_conversas`.
*   `ai_service.py` deixou de referenciar `self.gemini_client` e passou a usar prompt geral, com cliente criado no primeiro uso.
*   Compras passaram a ter extração separada da gravação, transação única, datas calculadas no Python e confirmação em caso de dúvida.
*   A rota `inventario` deixou de confirmar consultas que não eram executadas.
*   O chat do Electron passou a preservar quebras de linha.
*   `desativar qwen` passou a retornar ao Gemma, e a inatividade de 30 minutos passou a ser respeitada.
*   `PROMPT_PROGRAMACAO` passou a ser string raw, sem sequências de escape inválidas.

---

## 5. Decisões da Versão

| Decisão | Motivo |
| :--- | :--- |
| Embeddings na CPU | Preservar a VRAM para os modelos do Ollama |
| Um modelo local por vez | A máquina não comporta bem Gemma e Qwen simultaneamente |
| Saída do ProjectAnalyzer fora do repositório | Garantir leitura sem alteração do projeto analisado |
| Só perguntas gerais vão ao Gemini | Manter compras, estoque, agenda, programação e documentação na máquina |
| Confirmar compras apenas em caso de dúvida | Manter o registro rápido, com comando de desfazer |
| Frases não classificadas ficam locais | Sem classificação, o texto pode ser privado |
| Análise síncrona, com chat bloqueado | Simplicidade e previsibilidade de uso da VRAM |
| Consulta de estoque por regras, sem LLM | Resposta rápida e sem custo de inferência |

---

## 6. O que a V4 Ainda Não Conclui

A V4 entrega a nova forma de uso, mas não conclui todos os objetivos. Os principais pontos em aberto são:

*   Compras não alimentam `controle_consumo`, então a gestão preditiva segue inoperante.
*   Validação de estoque por voz ficou inalcançável com o modelo Text-First.
*   Modo Qwen é parcial: os assistentes continuam fixos no Gemma e o prompt de programação não é aplicado de forma garantida.
*   Envio de arquivos pelo chat e botão QWEN no Electron não foram construídos.

A lista completa, com locais e evidências, está em `08 - Estado Atual da V4.md`.
