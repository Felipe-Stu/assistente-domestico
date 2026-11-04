# 08 - Estado Atual da V4

Retrato técnico da **Versão 4 (V4)** do **Assistente Doméstico Inteligente** em **03/11/2026**, na branch `V4`, a partir do commit `c754a6a`, incluindo as correções da seção 6 e a Fase 1. Este documento registra o que funciona de fato, o que existe apenas no código e o que ainda não foi construído.

> [!IMPORTANT]
> Quando houver conflito entre este documento e descrições mais antigas, vale o que está aqui: ele foi escrito a partir do código e de testes executados. Havendo novas alterações de código, confira novamente.

**Legenda de evidência:** `TESTADO` (executado nesta análise) · `CÓDIGO` (confirmado pela leitura do código) · `DADOS` (confirmado no banco ou nos logs locais) · `NÃO TESTADO` (depende de hardware ou serviço indisponível na análise).

---

## 1. Resumo

A V4 é um assistente doméstico desktop: Electron na interface, Python no back-end, Ollama como IA local e Gemini como contingência na nuvem. A base está organizada e o back-end inicia e encerra corretamente, inclusive sem a chave do Gemini. O **registro de compras** e a **Skill ProjectAnalyzer** são os fluxos mais completos.

A Fase 1 concluiu a base confiável: frases conhecidas são roteadas por regras, compras têm validação e gravação segura, e somente perguntas gerais podem ir à nuvem. A gestão preditiva de estoque **ainda não funciona de ponta a ponta**, pois as compras gravadas não chegam à tabela de estoque (Fase 4).

| Indicador | Valor |
|---|---|
| Código versionado (Python, JS, HTML, CSS) | ≈ 8.070 linhas |
| Testes automatizados | 70 (22 do ProjectAnalyzer, 7 do orquestrador e 41 da Fase 1); **70 aprovados** |
| Testes de estoque, serviços vetoriais reais e IPC | Nenhum |
| Dados reais em `assistente_casa.db` (schema v2) | 4 compras, 11 itens, **0 em `controle_consumo`** |
| Problemas abertos | 14 (1 alto, 7 médios, 6 baixos); 8 resolvidos |

---

## 2. Situação das funcionalidades

### Implementado e operante

| Funcionalidade | Observação | Evidência |
|---|---|---|
| Back-end com inicialização Text-First | Chega a `READY` e encerra com código 0 | `TESTADO` |
| Interface Electron com chat, modo voz, mudo e terminal de debug | Contrato IPC revisado; janela não aberta nesta análise | `CÓDIGO` |
| Registro de compras por LLM local, com gravação no SQLite e vetorização | Extração testada com o Gemma real; preço por embalagem e datas conferidos | `TESTADO` |
| Confirmação de compras em caso de dúvida e comando "desfazer última compra" | Desfazer vale para o último registro da sessão | `TESTADO` |
| Roteamento por regras, com o orquestrador apenas para casos ambíguos | 9 de 10 frases medidas foram roteadas sem IA, em menos de 0,1 s | `TESTADO` |
| Política da nuvem | Só `geral` e `outro` vão ao Gemini, fora do Modo Qwen e sem histórico ou memórias restritos | `TESTADO` |
| Skill ProjectAnalyzer sem LLM | Analisou este projeto em 0,2 s | `TESTADO` |
| Memória semântica no ChromaDB e contexto RAG no assistente genérico e no Gemini | Funciona, com filtro permissivo (P19) | `CÓDIGO` + `DADOS` |
| Modo Qwen por comando de texto ou voz | Ativação, desativação e retorno por inatividade testados com troca de modelo simulada | `TESTADO` |

### Parcial

| Funcionalidade | O que falta | Problemas |
|---|---|---|
| Consulta de estoque por texto | A lógica existe, mas a tabela consultada nunca é preenchida | P1 |
| Consultas de gastos e preços | São reconhecidas, mas respondem que a função ainda não existe (Fase 3) | — |
| Modo Qwen como assistente de programação | Não libera a VRAM por completo, não usa de forma garantida o prompt de programação e não executa ferramentas | P7, P10 |
| Agenda | Reconhece o pedido e informa que a função ainda não existe; nada é gravado | P9 |
| Modo voz | Código presente; depende de microfone, Google Speech e Edge TTS | `NÃO TESTADO` |

### Existe no código, mas não está ligado ao fluxo

| Funcionalidade | Situação |
|---|---|
| Ajuste de estoque em nova compra (`processar_estoque_nova_compra`) | Nenhuma chamada no projeto |
| Baixa voluntária (`registrar_fim_estoque_direto`) | Nenhuma chamada no projeto |
| Perguntas de validação por voz | Inalcançáveis na prática (P8) |
| Busca híbrida SQLite + ChromaDB (`busca_hibrida_compra`) | Usada apenas em `scripts/validate_vector_database.py` (P12) |
| `CloudLLMProvider` | Criado em `app/main.py:162`, mas nunca entregue a um assistente |
| Tabela `historico_conversas` | Criada, nunca escrita nem lida |

### Planejado (`OBJETIVO DA VERSÃO.txt`), sem implementação

- Envio de arquivos de texto pelo chat. A interface tem apenas um campo de mensagem.
- Botão ou função "QWEN" no Electron.
- Troca de IA por intenção ("vou programar"). Hoje só frases exatas funcionam.
- Leitura de tela e pesquisa no Google (objetivo futuro).

---

## 3. Arquitetura em uso

```mermaid
graph TD
    USER["Usuário"] --> UI["Electron<br>main.js, preload.js, renderer.js"]
    UI -->|"JSON por stdin/stdout"| RT["AssistenteRuntime<br>app/main.py"]
    RT --> ORQ{"Regras, depois orquestrador<br>gemma_service"}
    ORQ -->|"Regra: Qwen"| QW["Troca de modelo"]
    ORQ -->|"Regra: projeto"| PA["ProjectAnalyzer<br>sem nuvem"]
    ORQ -->|"compras"| SH["ShoppingAssistant"]
    ORQ -->|"inventario"| INV["consultar_estoque<br>somente leitura"]
    ORQ -->|"agenda"| AG["Aviso: ainda indisponível"]
    ORQ -->|"geral, outro, programacao"| LOCAL["executar_assistente_local"]
    ORQ -->|"geral ou outro, se difícil"| NUVEM["Gemini"]
    LOCAL -->|"falha em geral ou outro"| NUVEM
    SH --> SQL[("SQLite<br>compras, itens_compra")]
    SH --> CH[("ChromaDB")]
    INV --> CC[("controle_consumo<br>0 registros")]
    LOCAL --> OLL["Ollama"]
    SH --> OLL
    ORQ --> OLL
    PA --> OLL
```

| Modelo | Papel | Situação local |
|---|---|---|
| `gemma4:e4b` | Orquestrador e assistente padrão | Baixado; Ollama desligado na análise |
| `qwen2.5-coder:7b` | Modo Qwen e ProjectAnalyzer | Baixado; não executado na análise |
| `gemini-2.5-flash` | Perguntas gerais difíceis e contingência delas | Chamada real não executada |
| `paraphrase-multilingual-MiniLM-L12-v2` | Embeddings na CPU | Em cache; carregou com sucesso |

**Dados que saem da máquina:** perguntas gerais enviadas ao Gemini, com histórico e memórias apenas de `geral` e `outro`; e, no modo voz, áudio enviado ao Google Speech e texto enviado ao Edge TTS. Compras, estoque, agenda, programação e documentação não vão ao Gemini. Com o Ollama parado, frases sem regra também não vão, pois não há como saber se são privadas.

---

## 4. Ambiente e execução

| Item | Verificado em 03/11/2026 |
|---|---|
| Python / Node / Electron | 3.13.5 / 22.15.0 / 31.7.7 |
| Dependências Python principais | Instaladas |
| `GEMINI_API_KEY` | Definida no ambiente do sistema; **não existe `.env`** no projeto. A chave é opcional |
| Cópia do banco antes da Fase 1 | `core/database/backups/assistente_casa_pre_fase1_2026-11-03.db` |
| Ollama | Instalado, serviço parado |

```bash
ollama serve
```

```bash
npm start
```

Executar somente o back-end, sem interface:

```bash
python app/main.py
```

Executar os testes:

```bash
python -m unittest discover -s tests -v
```

**Git:** a branch `V4` existe só nesta máquina, sem cópia no GitHub. O `V3` remoto contém o commit `a8ad2ca`, que ainda não foi baixado para este repositório.

---

## 5. Validação executada

Os testes usam bancos temporários e LLM simulado. No banco real, foram feitas apenas a migração para o schema v2 e a remoção autorizada da compra nº 5, depois de uma cópia de segurança.

| Verificação | Resultado |
|---|---|
| `python -m unittest discover -s tests` | 70 de 70 aprovados |
| Início do back-end **sem** `GEMINI_API_KEY`, com pedidos de agenda e gastos | `system_ready`, respostas corretas e saída com código 0 |
| Teste real com Gemma (10 frases) | 9 por regras em menos de 0,1 s; "Vou programar agora" ficou local, em 22 s |
| Teste real de extração (4 compras) | Arroz gravaria R$ 27,90 (5 kg na embalagem); "ontem" resultou em 02/11/2026; mercado ausente gerou confirmação |
| `tests/test_gemma_service.py` antes das correções | Falhou nos casos de P2, P6 e P17, confirmando os defeitos |
| Compilação de `app`, `core`, `services` e `scripts` com `SyntaxWarning` como erro | Sem ocorrências |
| ProjectAnalyzer com Qwen real em `services/vector` | 7 chamadas em 81,5 s, cerca de 12 s por chamada |
| ProjectAnalyzer `--sem-llm` neste repositório | 70 arquivos, 5 achados, sem alterações no repositório |
| Reprodução de P1, P2, P4, P5, P6, P11 e P20 | Confirmados antes das correções (seção 6) |

**Não testado:** janela do Electron, chamada real ao Gemini, microfone, TTS e reconhecimento de voz. Amostras reais pequenas não garantem acerto em toda frase ou compra.

O achado de gravidade alta do ProjectAnalyzer é um **falso positivo**: trata-se do token fictício `TOKEN_FALSO`, usado no teste de ocultação de segredos.

---

## 6. Problemas conhecidos

### Gravidade alta

| ID | Problema | Local | Efeito | Evidência |
|---|---|---|---|---|
| P1 | **Compras não alimentam o estoque.** Não existe `INSERT` em `controle_consumo`, e o `ShoppingAssistant` não chama o `InventoryAssistant`. | `services/shopping_assistant.py:245` | Consulta sempre vazia; varredura sem itens; gestão preditiva inoperante | `TESTADO` + `DADOS` |

### Gravidade média

| ID | Problema | Local | Efeito | Evidência |
|---|---|---|---|---|
| P7 | Assistentes usam Gemma fixo mesmo no modo Qwen. | `app/main.py:170` | Os dois modelos podem ocupar a VRAM ao mesmo tempo | `CÓDIGO` |
| P8 | A varredura roda só no início, com o modo voz ainda desligado, e `validacao_pendente` nunca vira pergunta. | `app/main.py:691`, `services/inventory_assistant.py:307` | Validação por voz inalcançável | `CÓDIGO` |
| P9 | Agenda não persiste dados. | `app/main.py` (rota `agenda`) | Nenhum compromisso salvo; o usuário recebe esse aviso | `CÓDIGO` |
| P10 | `programacao` não está entre os contextos oferecidos ao orquestrador. | `services/gemma_service.py:388` | `PROMPT_PROGRAMACAO` só é usado se o modelo devolver esse valor por conta própria | `CÓDIGO` |
| P12 | Vetores de compras em tempo real não têm `entity_id`, e a busca híbrida não está ligada ao fluxo. | `services/shopping_assistant.py:500` | Sem hidratação de valores exatos do SQLite | `CÓDIGO` |
| P13 | `rebuild_embeddings.py` apaga a coleção inteira, mas só recria dados vindos do SQLite. | `scripts/rebuild_embeddings.py:25` | **Perda definitiva das memórias `mem_*`** | `CÓDIGO` |
| P14 | Migração e fluxo em tempo real usam IDs diferentes para o mesmo item. | `scripts/migrate_vector_database.py:58`, `services/shopping_assistant.py:491` | Itens duplicados no ChromaDB | `CÓDIGO` |

### Gravidade baixa

| ID | Problema | Local | Evidência |
|---|---|---|---|
| P16 | Sem tratamento do evento `error` do processo Python; falha ao iniciar `python` não é informada na interface. | `main.js:48` | `CÓDIGO` |
| P18 | Erros aparecem apenas no terminal interno, não no chat. | `renderer.js:282` | `CÓDIGO` |
| P19 | Toda frase com 4 ou mais palavras vira memória de longo prazo. | `services/vector/memory_service.py:48` | `CÓDIGO` |
| P20 | Heurística confunde respostas: "sim, mas sobraram dois" e "assim que abri acabou" viram `CONFIRMACAO`. Efeito futuro, pois o fluxo está inativo. | `services/inventory_assistant.py:175` | `TESTADO` |
| P21 | Chat só fica disponível depois da carga do modelo de embeddings (15 a 50 s nos logs). Mensagens enviadas antes aguardam, sem aviso. | `app/main.py:154` | `DADOS` |
| P22 | `with get_connection()` confirma a transação, mas não fecha a conexão SQLite; os testes emitem `ResourceWarning`. | `services/db_service.py` | `TESTADO` |

### Resolvidos em 03/11/2026

| ID | Problema | Correção | Validação |
|---|---|---|---|
| P2 | `desativar qwen` ativava o Qwen, pois o texto contém "ativar qwen" | Comandos de desativação são avaliados primeiro; `desativar modo qwen` foi incluído | `tests/test_gemma_service.py` |
| P6 | Inatividade de 30 minutos nunca desativava o Qwen, pois o horário era renovado antes da verificação | A verificação ocorre antes da renovação do horário | `tests/test_gemma_service.py` |
| P17 | Sequências de escape inválidas em `PROMPT_PROGRAMACAO`, incluindo `\a`, que virava caractere de controle | O prompt passou a ser string raw | `tests/test_gemma_service.py` |
| P3 | Gemini usava prompt fixo de compras, e falhas locais de compras podiam parecer registradas | Prompt geral; compras não vão à nuvem e a falha é informada | `tests/test_fase1.py` |
| P4 | Consultas de compras eram tratadas como registro | A rota respeita `acao`; consulta nunca grava | `tests/test_fase1.py` |
| P5 | Nova tentativa duplicava compras | Só a extração é repetida; a gravação ocorre uma vez, em transação única | `tests/test_fase1.py` |
| P11 | Sem chave do Gemini, o sistema não iniciava | Cliente criado no primeiro uso; sem chave, tudo fica local | `tests/test_fase1.py` e início real |
| P15 | Erros de cota não eram convertidos | A rota usa `chamar_llm` e não repete em cota esgotada | `tests/test_fase1.py` |

A verificação de inatividade ocorre na solicitação seguinte, não em segundo plano. Enquanto isso, o Ollama libera o modelo ocioso pelo próprio `keep_alive`.

---

## 7. Código sem uso e dívida técnica

- **Sem chamadas no projeto:** `parse_json_com_fallback`, `classificar_intencao_usuario`, `enviar_prompt_json`, `salvar_compra_da_ia`, `obter_itens_expirados_para_validacao`, `obter_dados_produto_por_nome`, `atualizar_recompra_e_ritmo`, `zerar_estoque_item`, `zerar_estoque_por_nome`, `pre_carregar_modelo` e os callbacks de áudio e voz.
- **Duplicado:** `_sanitizar_resposta_json` em `gemma_service.py` (sem uso) e nos dois provedores de LLM.
- **Configurações sem uso:** `SAMPLE_RATE`, `CHANNELS`, `CHUNK_SIZE`, `RECORD_SECONDS` e `GEMINI_API_KEY` em `core/config.py`.
- **Dependência sem uso direto:** `requests`.
- **Estado de interface sem origem:** o back-end nunca emite `RESPONDING`.
- **Cobertura:** roteamento, compras, política da nuvem e parte do runtime têm testes. Faltam estoque, serviços vetoriais reais, voz e IPC.

---

## 8. Objetivo da versão × entrega

| Item do `OBJETIVO DA VERSÃO.txt` | Situação |
|---|---|
| Electron com chat de texto | Entregue |
| Ligar e desligar microfone | Entregue (não testado com hardware) |
| Enviar arquivos de texto pelo chat | Não entregue |
| Segunda IA local (Qwen 2.5-Coder 7B) | Parcial |
| Trocar de IA por comando de texto ou voz | Entregue para frases exatas |
| Trocar de IA por função no Electron | Não entregue |
| Voltar ao Gemma ao pedir | Entregue para frases exatas |
| Voltar ao Gemma ao reiniciar | Entregue (estado apenas em memória) |
| Voltar ao Gemma após 30 min sem atividade | Entregue, com aplicação na solicitação seguinte |

---

## 9. Documentação do projeto

| Documento | Situação em 03/11/2026 |
|---|---|
| `01` a `05` nesta pasta | Atualizados para a V4 nesta revisão |
| `06 - Evolução da V3 para a V4.md` | Criado nesta revisão |
| `07 - Skill ProjectAnalyzer.md` | Correto |
| `README.md` | **Desatualizado:** descreve a V3 e omite Electron e `npm start` |
| `CHANGELOG.md` | Atualizado com as correções de 03/11/2026; a lista completa de problemas está neste documento |

---

## 10. Próximos passos recomendados

Ordem aprovada em 03/11/2026:

1. **Fase 1, base confiável:** concluída.
2. **Fase 2, documentação:** pedidos naturais, leitura de `.md` e `.txt` e mais contexto para os modelos.
3. **Fase 3, consultas de compras:** gastos por mês, mercado e categoria, além de histórico de preços.
4. **Fase 4, estoque (P1):** catálogo de produtos, itens recorrentes, conversão de unidades e ritmo de consumo.
5. **Fase 5, lista e previsões:** lista de compras e comparação entre mercados.

Pendências paralelas: concluir o modo Qwen (P7, P10, botão e troca por intenção), definir o envio de arquivos pelo chat e a agenda, publicar a branch `V4` e atualizar `README.md`.
