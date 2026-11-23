# 06 - Evolução da V4 para a V4.1

Este documento registra o histórico comparativo entre a **Versão 4 (V4)** e a **Versão 4.1 (V4.1)** do **Assistente Doméstico Inteligente**, com as mudanças, as decisões tomadas, as medições e o que ficou pendente.

---

## 1. Contexto da Evolução

A V4 entregou o chat, a memória semântica e a Skill ProjectAnalyzer, mas a base tinha custos que atrapalhavam o uso diário: o chat levava ≈ 18 s para aceitar texto, cada decisão do orquestrador levava ≈ 8 s, o Ollama fechado deixava o usuário esperando sem explicação, não havia cópia de segurança e os logs não permitiam medir nada.

A **V4.1 não acrescenta funcionalidades para o usuário**. Ela arruma a base para que as próximas etapas (voz local, leitura de PDF, relatórios, agenda, Spotify) sejam construídas sobre algo rápido, medido e recuperável. As melhorias seguem os códigos `M` do planejamento (documento de melhorias da pasta de planejamento, fora do repositório).

---

## 2. Tabela Comparativa de Componentes

| Componente / Módulo | Situação na V4 | Situação na V4.1 | Tipo da Alteração |
| :--- | :--- | :--- | :--- |
| **Integração contínua (M02)** | **Inexistente** | GitHub Actions: sintaxe Python e JavaScript, suíte completa e linter informativo a cada push na `V4` e a cada pull request | Novo |
| **Saída dos modelos locais (M03)** | `format="json"`; valores fora das listas eram descartados depois | JSON Schema no `format` do Ollama para o orquestrador e a extração de compras (`services/esquemas.py`); recaída para JSON simples com biblioteca antiga | Modificado |
| **Início do sistema (M04)** | Chat esperava o modelo de embeddings (≈ 18 s) | Embeddings carregados em segundo plano; chat pronto em 3,5 s | Reestruturado |
| **Embeddings** | Iam para a GPU apesar do log dizer CPU; ≈ 30 consultas ao Hugging Face por início | `EMBEDDING_DEVICE` (padrão `cpu`) e carga só do cache local | Corrigido |
| **Orquestrador (M32)** | Gemma 4 com raciocínio ligado (padrão do Ollama), ≈ 450 tokens por decisão | Raciocínio desligado; opção `OLLAMA_RACIOCINIO` | Modificado |
| **Ollama fechado (M17)** | 3 tentativas e 2 esperas de 3 s (mínimo de 6 s), sem explicação | Verificação de saúde de 2 s; erro de conexão sem repetição; botão "Tentar de novo" no chat; aviso no início | Novo |
| **Leitura dos comandos do Electron** | Entrada padrão compartilhada; a carga dos embeddings travava até a mensagem seguinte | Pipe lido por descritor privado (`ENTRADA_IPC`) | Corrigido |
| **Cópia de segurança (M11)** | Uma cópia manual, feita antes da Fase 1 | Cópia diária automática do SQLite e do ChromaDB, com verificação de integridade, manifesto e retenção de 7 diárias e 4 semanais (`services/backup_service.py`) | Novo |
| **Registro de eventos (M26)** | Um `.txt` por módulo, sem rotação, sem nível e sem como medir | Uma linha JSON por evento em `Logs/eventos-AAAA-MM-DD.jsonl`, identificador por requisição, tempo por etapa, retenção de 30 dias e opção de omitir o texto do usuário | Reestruturado |
| **Reconstrução dos embeddings (P13)** | Apagava as memórias `mem_*` | Faz cópia, exporta e regrava as memórias | Corrigido |
| **Conexões SQLite (P22)** | Ficavam abertas após o `with` | Fechadas ao sair do bloco | Corrigido |
| **Skills (SK1)** | Prompts dentro do Python e regex no `intent_router.py` | Uma pasta por capacidade em `skills/` (instruções, prompts e gatilhos), lida por `core/skills/` | Novo |
| **Conjunto de avaliação (SK0)** | 8 frases do orquestrador e 6 compras dentro de um script | `evals/` (48 frases por skill, 15 de capacidades futuras, e 8 compras) e `scripts/avaliar.py` | Novo |
| **Testes** | 70 | 160 | Expandido |
| **Medições** | Só pelos logs | Scripts que medem o app real (`medir_v41.py`, `medir_m17.py`) e resumem o tempo por etapa (`ver_logs.py`) | Novo |

---

## 3. Arquivos Adicionados

| Área | Arquivos |
| :--- | :--- |
| Integração contínua | `.github/workflows/testes.yml`, `requirements-ci.txt` |
| Serviços | `services/esquemas.py`, `services/backup_service.py` |
| Scripts | `scripts/medir_v41.py`, `scripts/medir_m17.py`, `scripts/fazer_backup.py`, `scripts/ver_logs.py` |
| Testes | `tests/test_v41.py`, `tests/test_m17.py`, `tests/test_m11.py`, `tests/test_m26.py`, `tests/test_skills.py`, `tests/test_sk0.py`, `tests/dados/roteador_referencia.json` |
| Skills | `skills/` (6 skills e `README.md`), `core/skills/` (`catalogo.py`, `seletor.py`), `evals/`, `scripts/avaliar.py` |

Arquivos alterados: `app/main.py`, `core/config.py`, `services/llm_provider.py`, `services/gemma_service.py`, `services/shopping_assistant.py`, `services/resilience_service.py`, `services/logger_service.py` (reescrito), `services/db_service.py`, `services/vector/embedding_service.py`, `services/vector/vector_store_service.py`, `services/vector/memory_service.py`, `services/ai_service.py`, `services/inventory_assistant.py`, `scripts/rebuild_embeddings.py`, `renderer.js`, `index.css`, `requirements.txt`, `.env.example`, `tests/test_fase1.py`.

---

## 4. Correções Aplicadas

*   O modelo de embeddings passou a respeitar `EMBEDDING_DEVICE`; antes ia para `cuda:0` e disputava a VRAM com o Ollama.
*   A carga dos embeddings em segundo plano não trava mais quando os comandos chegam por pipe (Electron).
*   `VectorStoreService.upsert_documents` não grava documentos sem vetor próprio.
*   `rebuild_embeddings.py` não apaga mais as memórias de longo prazo (P13).
*   As conexões SQLite são fechadas ao sair do `with` (P22).
*   O início do sistema deixou de esperar o modelo de embeddings (P21).

---

## 5. Decisões da Versão

| Decisão | Motivo |
| :--- | :--- |
| Medir no app real antes de mudar o modelo | O gargalo do orquestrador era o raciocínio ligado por padrão, não a capacidade do Gemma: mesmo acerto (16/16) em 1,2 s em vez de 8,1 s |
| Gemma 4 continua orquestrador; Qwen fica para programação | Mesmo acerto, mais rápido e menos VRAM (Qwen: 1,5 s) |
| Erro de conexão não é repetido; JSON inválido é | Repetir não traz o Ollama de volta; uma resposta malformada pode sair certa na tentativa seguinte |
| Com o Ollama fechado, nada restrito vai à nuvem | Mantém a política de privacidade da V4 também na falha |
| Cópia ao abrir o app, não em horário fixo | O assistente não fica ligado o tempo todo |
| Cópia montada em pasta `.parcial` e renomeada ao terminar | Uma pasta com o nome do dia está sempre completa |
| Logs em arquivo diário, sem renomear | No Windows, renomear um log aberto por outro processo falha |
| Um arquivo de eventos por dia, com o componente em cada linha | Uma requisição atravessa vários módulos e precisa ser lida em ordem |
| `logger_service` mantém `log_geral` e `log_assistente` | Os 15 módulos que já registram eventos não precisaram mudar |
| Skills como organização primeiro, sem mudar comportamento | Cada capacidade nova vira uma pasta; a escolha pelo catálogo (SK2) só entra depois de medida |
| Gatilhos com prioridade explícita | O roteador dependia da ordem das regex (desfazer antes de registrar, consulta antes de registro) |

---

## 6. Medições

Feitas no PC do usuário em 17/11/2026 (`scripts/medir_v41.py` e `scripts/medir_m17.py`; relatórios na pasta de planejamento, fora do repositório).

| Medida | V4 | V4.1 |
| :--- | :--- | :--- |
| Chat pronto após abrir | ≈ 18 s | 3,5 s |
| Decisão do orquestrador (mediana) | 8,1 s | 1,2 s |
| Tokens gerados por decisão (mediana) | 448 | 36 |
| Acerto do orquestrador (16 chamadas) | 16/16 | 16/16 |
| Resposta com o Ollama fechado | ≥ 6 s, sem explicação | 2,4 s, com botão "Tentar de novo" |

Cópia de segurança, em 22/11/2026, com os dados reais copiados para uma pasta temporária: 12 ms, com contagens iguais à origem e `integrity_check` ok.

---

## 7. O que a V4.1 Ainda Não Conclui

*   **M01:** as credenciais anotadas em texto puro fora do repositório ainda precisam ser revogadas e trocadas.
*   **M02:** o fluxo de integração contínua só roda depois do primeiro envio ao GitHub.
*   **M27:** modelos e caminhos ainda estão espalhados pelo código, e o Electron inicia o Python com `spawn('python')`.
*   **Extração de compras com raciocínio desligado:** ainda não medida; continua no padrão do Ollama.
*   Os problemas funcionais da V4 continuam abertos, entre eles o P1 (compras não alimentam o estoque).

A lista completa, com locais e evidências, está em `08 - Estado Atual da V4.md` (seções 11 e 12).
