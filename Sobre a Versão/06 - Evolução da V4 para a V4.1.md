# 06 - Evolução da V4 para a V4.1

Este documento registra o histórico comparativo entre a **Versão 4 (V4)** e a **Versão 4.1 (V4.1)** do **Assistente Doméstico Inteligente**, com as mudanças, as decisões tomadas, as medições e o que ficou pendente.

---

## 1. Contexto da Evolução

A V4 entregou o chat, a memória semântica e a Skill ProjectAnalyzer, mas a base tinha custos que atrapalhavam o uso diário: o chat levava ≈ 18 s para aceitar texto, cada decisão do orquestrador levava ≈ 8 s, o Ollama fechado deixava o usuário esperando sem explicação, não havia cópia de segurança e os logs não permitiam medir nada.

A V4.1 começou **sem funcionalidades novas para o usuário**: a primeira parte arruma a base para que as próximas etapas (voz local, leitura de PDF, relatórios, agenda, Spotify) sejam construídas sobre algo rápido, medido e recuperável. As melhorias seguem os códigos `M` do planejamento (documento de melhorias da pasta de planejamento, fora do repositório).

A segunda parte, a **fase das skills** (SK0 a SK8 e SKP, concluída em 23/11/2026), reorganizou o sistema em skills escolhidas por catálogo. Sobre essa base entraram a agenda, as ideias de projetos com análise do Claude e o bot do Telegram (seção 8).

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
| **Conjunto de avaliação (SK0)** | 8 frases do orquestrador e 6 compras dentro de um script | `evals/` (53 frases por skill, com capacidades futuras, e 8 compras) e `scripts/avaliar.py` (também por skill: `--skill`) | Novo |
| **Orquestrador (SK2/SK5)** | Prompt de ≈ 250 linhas com contextos fixos | Escolha da skill pelo catálogo (prompt fixo, JSON Schema com o nome das skills); o antigo foi removido | Reestruturado |
| **Roteiros (SK3)** | `if contexto ==` no `app/main.py` | Cada skill executa o próprio `roteiro.py`; confirmação genérica (`pendencia`); encaminhamento à conversa geral | Reestruturado |
| **`app/main.py` (SK5)** | 974 linhas | 788 linhas + `app/ipc.py`, `app/sessao.py`, `app/voz.py` | Dividido |
| **Fábrica de skills (SK6)** | — | `skills/_modelo`, `scripts/nova_skill.py`, `scripts/validar_skills.py` (na integração contínua) | Novo |
| **Agenda (SK7)** | Respondia "ainda não está disponível" | Anota, consulta e cancela compromissos (tabela `compromissos`), feita só com `skills/agenda/` | Novo |
| **Programação (SKP)** | Qwen sem contexto, fora do orquestrador (P10) | Claude (assinatura ou API) como principal; Qwen + biblioteca de contexto como reserva | Novo |
| **Ideias e Telegram (SK8)** | — | Skill `ideias`, fila de análise pelo Claude, `Ideias/*.md` na biblioteca, bot do Telegram | Novo |
| **Testes** | 70 | 231 | Expandido |
| **Medições** | Só pelos logs | Scripts que medem o app real (`medir_v41.py`, `medir_m17.py`) e resumem o tempo por etapa (`ver_logs.py`) | Novo |

---

## 3. Arquivos Adicionados

| Área | Arquivos |
| :--- | :--- |
| Integração contínua | `.github/workflows/testes.yml`, `requirements-ci.txt` |
| Serviços | `services/esquemas.py`, `services/backup_service.py` |
| Scripts | `scripts/medir_v41.py`, `scripts/medir_m17.py`, `scripts/fazer_backup.py`, `scripts/ver_logs.py` |
| Testes | `tests/test_v41.py`, `tests/test_m17.py`, `tests/test_m11.py`, `tests/test_m26.py`, `tests/test_skills.py`, `tests/test_sk0.py`, `tests/dados/roteador_referencia.json` |
| Skills | `skills/` (7 skills, `_modelo` e `README.md`), `core/skills/` (`catalogo.py`, `seletor.py`, `motor.py`), `evals/`, `scripts/avaliar.py`, `scripts/nova_skill.py`, `scripts/validar_skills.py` |
| Claude, ideias e Telegram | `services/claude_service.py`, `services/claude_assinatura_service.py`, `services/biblioteca_service.py`, `services/ideias_service.py`, `services/telegram_service.py` |
| App dividido (SK5) | `app/ipc.py`, `app/sessao.py`, `app/voz.py` |
| Scripts de configuração | `scripts/indexar_biblioteca.py`, `scripts/testar_skp.py`, `scripts/testar_claude_assinatura.py`, `scripts/configurar_telegram.py`, `scripts/conferir_chaves.py` |
| Arquivos `.bat` | `iniciar-assistente.bat`, `instalar-claude-code.bat`, `testar-claude-assinatura.bat`, `configurar-telegram.bat`, `testar-skp.bat`, `rodar-medicao-sk0.bat`, `verificar-sk2.bat`, `conferir-chaves.bat` |
| Testes da fase | `tests/test_sk2.py`, `test_sk3.py`, `test_skp.py`, `test_sk6.py`, `test_sk7.py`, `test_ideias.py` |

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

Fase das skills, em 23/11/2026, no PC do usuário (`scripts/avaliar.py`, relatórios em `Planejamento/medicoes/`):

| Medida | Antes | Depois |
| :--- | :--- | :--- |
| Escolha da skill (48 frases) | 43/48 em 1,39 s (prompt por contextos) | 44/48 em 0,87 s (catálogo, contando a ação) |
| Tokens lidos / gerados na escolha | 1.624 / 36 | 325 / 8 (SK0, Gemma no catálogo) |
| Troca de modelo Gemma ↔ Qwen | — | 13 a 15 s; os dois não cabem juntos na VRAM |
| Claude pela assinatura | — | resposta curta em 5,5 s; análise de ideia em cerca de 20 s |

---

## 7. O que a V4.1 Ainda Não Conclui

*   **M01** (credenciais em texto puro) foi concluído em 23/11/2026: chaves trocadas e anotações substituídas por `[REVOGADA]`.
*   **M02:** a integração contínua roda a cada envio ao GitHub. Os commits da fase das skills ainda não foram enviados.
*   **SK4** (fluxos abertos com ferramentas) ficou de fora por decisão: o SK3 bastou.
*   **M27** concluído em 23/11/2026: modelos e tempos no `.env`, Python configurável no Electron, bipes sem `winsound`, script para o `requirements-lock.txt` (`fixar-versoes.bat`) e licença MIT.
*   **Extração de compras com raciocínio desligado:** ainda não medida; continua no padrão do Ollama.
*   Os problemas funcionais da V4 continuam abertos, entre eles o P1 (compras não alimentam o estoque).

A lista completa, com locais e evidências, está em `08 - Estado Atual da V4.md` (seções 11 e 12).

---

## 8. Fase das Skills (concluída em 23/11/2026)

| Etapa | Entrega | Evidência |
| :--- | :--- | :--- |
| SK0 | Medição: Gemma 4 E4B escolhe a skill pelo catálogo com 45/48 em 0,55 s; o prompt por contextos fazia 43/48 em 1,39 s | `MEDIDO` no PC |
| SK1 | Uma pasta por capacidade em `skills/` (instruções, prompts, gatilhos) | 0 diferenças em 168 decisões de referência |
| SK2 | Orquestrador escolhe pelo catálogo, com prompt fixo e saída restrita | `MEDIDO` no PC: 44/48 em 0,87 s |
| SK3 | Compras, estoque e agenda com roteiro próprio; confirmação genérica | `TESTADO` |
| SK5 | Orquestrador antigo removido; `main.py` dividido (974 → 788 linhas); nenhum `if contexto ==` no `app/` | `TESTADO` e teste de fumaça |
| SK6 | Fábrica de skills (`nova_skill.py`, `validar_skills.py` na integração contínua) | `TESTADO` |
| SK7 | Agenda funcional feita só com a pasta da skill, sem mexer no núcleo | `TESTADO` |
| SKP | Programação com o Claude (pela assinatura, `claude -p`, ou pela API) e reserva no Qwen com biblioteca de contexto | `TESTADO` no PC |
| SK8 | Ideias de projetos: salvas pelo chat ou pelo Telegram, analisadas pelo Claude e guardadas na biblioteca local | `TESTADO` no PC (análise em cerca de 20 s) |
| SK4 | Fluxos abertos com ferramentas | Não feito (opcional) |

Problemas resolvidos na fase: P9 (agenda), P10 (programação fora do orquestrador) e P23 (pedido de sugestões confundido com ideia salva).

**Decisões da fase**
- Gemma 4 E4B é o modelo residente, e a escolha da skill é feita pelo catálogo.
- O Claude recebe dados só das skills autorizadas (`programacao`, `ideias`). Compras, estoque e agenda nunca saem da máquina.
- O Claude pela assinatura é o padrão, sem cobrança à parte; ele roda sem ferramentas, numa pasta temporária.
- O bot do Telegram atende só os chats configurados e, por enquanto, só guarda ideias.

**Ficou para depois**
- O bot do Telegram ainda não conversa com o assistente inteiro.
- Aviso na hora dos compromissos e Google Agenda (V7).
- A distinção entre pergunta e ideia no Telegram é uma regra simples: uma ideia escrita como pedido pode precisar de "ideia:" na frente.

