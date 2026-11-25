# 06 - Evolução da V4.1 para a V5.5

Histórico das versões entre a fase das skills (V4.1, 23/11/2026) e o servidor (V5.5, 25/11/2026). Detalhes de cada entrega no `CHANGELOG.md`; situação de cada funcionalidade em `08 - Estado Atual da V4.md` (seção 25 para a V5.5).

---

## 1. Linha do tempo

| Versão | Data | Entregas | Itens do roadmap |
|---|---|---|---|
| V4.2 — medir antes de mudar | 23/11 | Origem de cada registro (`entradas`), conjunto de avaliação com histórico, nuvem só por escolha, prompt do orquestrador enxuto | M09, M13, M15, M16 (M14 descartado) |
| V4.3, parte 1 | 23/11 | Catálogo de produtos com 15 categorias fechadas, dinheiro em centavos, compras alimentando o estoque | M07, M08, M06 (fecha P1) |
| V4.3 — notas fiscais | 23/11 | NFC-e (HTML), NF-e e NFC-e coladas, PDF, foto, pasta de entrada, Telegram, 📎 e arrastar no app; perguntas do que falta antes do "sim" | — |
| V4.3, parte 3 | 23/11 | Consultas de gastos (total, por categoria, por loja, preço de produto, comparação de períodos) | M19 |
| V4.3, parte 4 | 24/11 | Correção de compras pelo chat | M10 (M35 descartado) |
| V4.3, parte 5 | 24/11 | Histórico persistente com janela e resumo | M20 |
| V4.3, parte 6 | 24/11 | Observações em compras e itens; ajustes somados antes do "sim"; aviso de compra repetida | — |
| V4.3, partes 7 e 8 | 24/11 | Foto em duas etapas (transcrição + leitor exato), modelo de imagem `qwen2.5vl:7b`, chave de acesso lida na foto | M34 |
| V4.3, parte 9 | 24/11 | Código NF, Série NF e Emissão (a emissão é a data da compra) | — |
| V5.5 — servidor | 25/11 | Núcleo como serviço de rede (API + SSE), Electron como cliente, página do celular, painel de gastos, modo demonstração, servidor MCP | M25, M23, M22, M28 (parcial), I04, I05, I06, I07 (M18 substituído) |

## 2. O que mudou na arquitetura

| Antes (V4.1) | Depois (V5.5) |
|---|---|
| Electron inicia o Python e conversa por stdin/stdout | Python roda como servidor (`app/servidor.py`, 127.0.0.1:8765); Electron e celular são clientes da mesma API |
| Fechar a janela encerra o assistente | Fechar a janela não desliga o servidor; ⏻ ou `desligar-assistente.bat` desligam |
| `app/main.py` com ~990 linhas | Dividido em `eventos.py`, `laco.py`, `documentos_app.py` (~680 linhas no `main.py`) |
| Compras só por frase | Compras por frase, nota colada, HTML, PDF e foto, com conferência antes de gravar |
| Valores em REAL | Valores em centavos inteiros (colunas REAL mantidas) |
| Estoque separado das compras | Cada item comprado soma ao estoque na mesma transação |
| Histórico só na memória do processo | Histórico gravado no SQLite, com janela de 6 trocas e resumo |
| Celular só para ideias (Telegram) | Celular com conversa, foto da nota e painel, pelo Tailscale |

## 3. Banco de dados (migrações)

| Migração | Mudança |
|---|---|
| v3 | Tabela `entradas` (origem de cada registro) e `compras.entrada_id` |
| v4 | Tabela `produtos` e `itens_compra.produto_id` (catálogo) |
| v5 | Colunas `*_centavos` em `compras` e `itens_compra` |
| v6 | Estoque alimentado pelas compras |
| v7 | `entradas.chave_documento` (nota não entra duas vezes) |
| v8 | `historico_conversas.contexto` e índice |
| v9 | `compras.observacao` e `itens_compra.observacao` |
| v10 | `compras.numero_nf`, `serie_nf`, `emissao` |

## 4. Decisões

- **Medir antes de mudar (V4.2):** a escolha da skill passou a ter histórico de medição; o classificador por similaridade (M14) foi descartado porque o catálogo já fica abaixo de 1 s no p95.
- **Leitores exatos antes do modelo:** nota fiscal com estrutura conhecida (HTML da Sefaz, texto da NFC-e ou NF-e) é lida por regra; o modelo local só torna legíveis nomes abreviados e escolhe categoria. Na foto, o modelo de imagem só transcreve.
- **O modelo não inventa:** loja, produto, valor ou observação que não aparecem na frase do usuário são descartados.
- **Dados do consumidor fora:** CPF, nome e bloco do destinatário não são lidos nem guardados.
- **Categoria original preservada (M35 descartado):** decisão do M07; as consultas usam a categoria do catálogo.
- **SSE e Starlette (V5.5):** fluxo do servidor para os clientes, sem biblioteca no navegador; Starlette é a base do FastAPI com menos dependências.
- **Acesso de fora pelo Tailscale:** nenhuma porta aberta para a internet; o servidor escuta só em 127.0.0.1.
- **Token por aparelho:** só o hash é gravado; revogável; escopo `local` (PC) e `remoto` (celular).
- **Servidor continua ligado ao fechar a janela:** o celular é o uso principal fora de casa.

## 5. Testes

Suíte de 250 testes na V4.2 para 357 na V5.5 (5 pulados quando faltam as bibliotecas do servidor; com elas, os 9 testes da API sobem um uvicorn de verdade).
