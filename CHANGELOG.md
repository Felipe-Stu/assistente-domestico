# CHANGELOG

## [V4] — Skill ProjectAnalyzer (2026-11-02)

### Adicionado
- `services/project_analyzer/`: Skill de análise de projetos e geração de documentação técnica 100% local (ver `Sobre a Versão/07 - Skill ProjectAnalyzer.md`).
- Comando no chat: `analisar projeto <caminho>` (detecção determinística no orquestrador, contexto `projetos`).
- `scripts/analyze_project.py`: execução pela linha de comando.
- `tests/test_project_analyzer.py`: 22 testes (`python -m unittest discover -s tests -v`).
- `core/config.py`: `PROJECT_ANALYZER_OUTPUT_DIR` (padrão `E:\Agente IA\Documentacao_Gerada`) e `PROJECT_ANALYZER_MODEL` (padrão `qwen2.5-coder:7b`).

### Decisões
- Saída fora do repositório e do projeto analisado; execução síncrona (chat bloqueado); modelo fixo Qwen 2.5-Coder com troca de VRAM (Gemma descarregado antes e Qwen liberado depois).
- A rota `projetos` nunca usa o fallback para o Gemini, o RAG ou a memória semântica.

## [V4] — 2026-11-02 (branch `V4`)

### Adicionado
- Versionamento da V4 que estava sem commit: Electron (`main.js`, `preload.js`, `renderer.js`, `index.*`), runtime Text-First, pacote `services/vector/` e `scripts/`.
- `InventoryAssistant.consultar_estoque()`: consulta de estoque por texto (somente leitura, sem LLM).
- Memória semântica ligada ao pipeline: contexto RAG no assistente local genérico e no Gemini; falas do usuário salvas no `MemoryService`.
- Exemplo few-shot de consulta de inventário no prompt do orquestrador.

### Corrigido
- `.gitignore.txt` renomeado para `.gitignore` (o Git ignorava o arquivo). Removidos do versionamento: `assistente_casa.db`, `__pycache__`, `Logs/` (arquivos locais preservados).
- `requirements.txt`: `google-generativeai` → `google-genai` (SDK usado no código); adicionados `edge-tts` e `pygame`.
- `db_service.py`: removido `from asyncio.windows_events import NULL`; tabela `historico_conversas` passa a ser criada.
- `InventoryAssistant` usa a voz/microfone do runtime e não fala/escuta com o modo voz desligado.
- Rota `inventario` deixou de responder "Consulta realizada com sucesso" sem consultar nada.
- Chat do Electron preserva quebras de linha nas respostas.

### Pendências conhecidas
- Alterar estoque por texto (baixa, correção) depende de diálogo por chat; hoje só por voz.
- Itens com `validacao_pendente` não são perguntados pelo chat.
- `compras` + `consultar` (ex.: "quanto gastei no Moreschi?") é roteado ao `ShoppingAssistant`, que é de registro.
- `AIService.processar_requisicao_complexa` usa prompt fixo de "texto de compras" para qualquer pedido enviado ao Gemini.
- Sem suíte de testes automatizados no repositório.
