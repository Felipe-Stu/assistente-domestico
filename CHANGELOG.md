# CHANGELOG

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
