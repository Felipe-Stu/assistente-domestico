# CHANGELOG

## [V4] — Fase 1: base confiável (2026-11-03)

### Adicionado
- `services/intent_router.py`: roteamento por regras para frases conhecidas, sem chamar o LLM.
- Confirmação de compras em caso de dúvida e comando "desfazer última compra", limitado ao último registro da sessão.
- Preço por embalagem: colunas `embalagem_quantidade` e `embalagem_unidade` em `itens_compra` (schema v2).
- `tests/test_fase1.py`: 41 testes. A suíte passa a ter 70 testes.

### Alterado
- Só contextos `geral` e `outro` podem ir ao Gemini, fora do Modo Qwen; histórico e memórias restritos não são enviados.
- Com o orquestrador indisponível, frases sem regra não são enviadas à nuvem.
- A data da compra é calculada no Python; o LLM não define "ontem" ou "anteontem".
- A divergência entre total, quantidade e preço gera confirmação, sem recálculo silencioso.
- `GEMINI_API_KEY` passa a ser opcional.

### Corrigido
- Consultas de compras não gravam mais registros (P4).
- Novas tentativas não duplicam compras; a gravação ocorre em transação única (P5).
- Prompt geral no Gemini, sem o texto fixo de compras (P3), e tratamento correto de cota esgotada (P15).
- Sistema inicia sem chave do Gemini (P11).
- Agenda informa a indisponibilidade em vez de exibir JSON bruto.

### Dados
- Removida a compra nº 5, registro vazio criado por uma pergunta. Cópia prévia em `core/database/backups/`.

## [V4] — Correções do Modo Qwen e documentação (2026-11-03)

### Corrigido
- `desativar qwen` e `desativar modo qwen` passaram a retornar ao Gemma; antes, a frase era reconhecida como ativação.
- A inatividade de 30 minutos passou a ser avaliada antes de renovar o horário de atividade, na solicitação seguinte.
- `PROMPT_PROGRAMACAO` passou a ser string raw, eliminando `SyntaxWarning` e o caractere de controle no caminho do projeto.

### Adicionado
- `tests/test_gemma_service.py`: 7 testes do orquestrador, sem acesso ao Ollama. A suíte passa a ter 29 testes.
- `Sobre a Versão/06 - Evolução da V3 para a V4.md` e `Sobre a Versão/08 - Estado Atual da V4.md`.

### Alterado
- Documentos 01 a 05 de `Sobre a Versão` revisados para a V4.

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
- Sem testes automatizados para estoque, serviços vetoriais reais e IPC.
