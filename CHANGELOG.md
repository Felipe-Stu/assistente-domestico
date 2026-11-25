# CHANGELOG

## [V5.5] — Servidor: o núcleo como serviço de rede (2026-11-25)

Detalhes e passo a passo em `Sobre a Versão/09 - Servidor, Celular e Painel (V5.5).md`.

### Adicionado
- **M25 — main.py dividido:** `app/eventos.py` (barramento de eventos), `app/laco.py` (partida e laço de comandos), `app/documentos_app.py` (notas fiscais). `main.py` caiu de 987 para cerca de 680 linhas. `emitir_electron` publica no barramento e, só na ponte antiga, imprime na saída padrão.
- **M23 — API:** `app/servidor.py` (Starlette + uvicorn + SSE), em 127.0.0.1:8765. Rotas de saúde, mensagens, comandos, anexos (até 20 MB, 5 por vez, formatos de nota), eventos (histórico recente + fluxo), resumo de gastos, `/entrar` (cookie HttpOnly/SameSite) e as páginas. Cabeçalhos de segurança (CSP, X-Frame-Options, nosniff) em toda resposta.
  - `services/dispositivos_service.py`: token por aparelho, só o hash SHA-256 gravado, revogável; escopo `local` (PC: voz, mudo, arquivo pelo caminho, desligar) e `remoto` (celular: conversa, foto, painel).
  - `scripts/dispositivos.py` (novo, listar, revogar) e `novo-dispositivo.bat`, que monta o link pelo nome do PC no Tailscale.
  - `iniciar-servidor.bat`: assistente no ar sem a janela.
- **Electron como cliente** (`cliente-api.js`): inicia o servidor se ele não estiver no ar, lê os eventos por SSE (com reconexão e sem duplicar o histórico) e envia por POST. `ASSISTENTE_PONTE=stdin` volta à ponte antiga. Fechar a janela não desliga o servidor (o celular continua funcionando); desligar é pelo botão ⏻ (com confirmação) ou por `desligar-assistente.bat`.
- **M22 — resposta em fluxo** na conversa geral: `assistant_delta` a cada 120 ms no máximo, estado `RESPONDING`.
- **M28 — interface:** Markdown seguro (`web/formatar.js`, usado pelo PC e pelo celular), botões de sim/não/pular, erros no chat, mensagens do celular marcadas (📱), CSP na janela e fonte local (saiu o Google Fonts).
- **I04 — página do celular (PWA):** `web/` com conversa, foto/arquivo pela câmera, botões, fluxo, instalável (manifesto, ícones, service worker que não guarda dados da API).
- **I06 — painel de gastos:** `/painel` com total, média, gastos por mês (SVG), por categoria e por loja e últimas compras; botão 📊 na janela do PC (token num cookie da sessão do Electron, fora da URL).
- **I07 — modo demonstração:** `ASSISTENTE_DEMO=1` usa `core/database/demo/` (banco, memória, anexos, ideias), desliga o Telegram e roda na porta 8766; `scripts/criar_demo.py` cria ~140 compras fictícias com semente fixa; `iniciar-demo.bat`.
- **I05 — servidor MCP** (`app/mcp_casa.py`): 6 consultas somente leitura para o Claude; desligado por padrão (ligar abre exceção à regra de que compras não saem do PC).
- Dependências: starlette, uvicorn, sse-starlette, python-multipart, mcp, Pillow.
- Testes: `tests/test_v55_servidor.py` (barramento, tokens e a API com uvicorn de verdade) e `tests/test_v55_extras.py` (painel, demonstração, MCP, formatação). Suíte: 357 (5 pulados sem as dependências do servidor; com elas, os 9 testes do servidor passaram). Fora da suíte: 25 verificações da API e 4 do cliente do Electron (Node) contra o servidor.

### Corrigido (revisão antes do envio)
- Servidor reiniciado com o celular ou a janela abertos: a numeração dos eventos recomeçava e as mensagens novas eram descartadas como repetidas. O barramento ganhou um identificador de instância; o cliente zera o contador quando ele muda.
- Anexos enviados pelo celular ficavam acumulados em `_recebidos/`: agora são apagados depois de importados (a cópia fica em `Anexos/`).
- Página do celular: 📷 forçava a câmera e impedia escolher da galeria, PDF ou HTML; agora há 📷 (câmera) e 📎 (arquivos). Sem conexão com o PC aparecia "aparelho sem acesso"; agora a mensagem diz que falta conexão e a página tenta de novo.
- Se o núcleo parasse (ex.: banco inacessível), o servidor seguia aceitando pedidos sem resposta; agora encerra.
- Corpo JSON que não é objeto em `/api/mensagens` e `/api/comandos` dava erro 500; agora 400.
- Segundo servidor na mesma porta: sai sem iniciar outro núcleo (evita Telegram e pasta de entrada em dobro).
- Dispositivo criado com o servidor ligado só valia depois de reiniciar (e podia ser apagado): o servidor relê o arquivo quando ele muda.

### Repositório
- Branch `v5.5` criada a partir da `v4.1` (que fica como histórico); integração contínua também roda nela.
- Tags de versão: `v4.2.0`, `v4.3.0` e `v5.5.0`, no último commit de cada versão.
- `enviar-github.bat` (fora do Git) envia a branch atual e as tags.

### Decisões
- Fechar a janela do PC não desliga o servidor (o celular é o uso principal fora de casa).
- SSE em vez de WebSocket: o fluxo é do servidor para os clientes; funciona no navegador sem biblioteca e passa pelo `tailscale serve`.
- Starlette em vez de FastAPI: é a base do FastAPI, com menos dependências; a troca é direta se for preciso.
- Acesso de fora de casa pelo Tailscale; servidor no PC atual; M18 marcado como substituído pelas skills.

### Pendente
- Testar no PC: `instalar-dependencias.bat`, abrir o assistente (o Electron sobe o servidor), Tailscale e `novo-dispositivo.bat` no celular.
- Áudio pela página do celular (depende da transcrição local, V6.5); atualizar o Electron (M28).

## [V4.3, parte 9] — Código NF, Série NF e Emissão (2026-11-24)

### Adicionado
- Migração v10: `compras.numero_nf` (Código NF), `serie_nf` (Série NF) e `emissao` (data e hora, AAAA-MM-DDTHH:MM:SS).
- `nfce_service.identificacao`: lê Número, Série e Emissão nos formatos da NFC-e ("Número: 62867 Série: 31 Emissão: 13/11/2026 16:10:51") e da NF-e ("Série 1 Número 758 Data/Hora da emissão …"), com ou sem dois-pontos e negrito.
  - Vale para HTML, texto colado e foto. **A emissão é a data da compra.**
- O resumo mostra "🧾 NF 62867 série 31, emitida em 13/11/2026 às 16:10".
- Foto lida pelo modelo de texto: desconto da nota distribuído nos itens quando a conta fecha (soma − desconto = valor a pagar).
- `tests/test_nota_identificacao.py` (5 testes). Suíte: 342 testes.

### Corrigido
- `ocultar_consumidor` apagava a linha "Número … Série … Emissão … - Via Consumidor" (a data da compra se perdia e virava a de hoje). Agora só sai a linha que identifica o consumidor ("CONSUMIDOR - CPF/CNPJ/Nome…") e qualquer CPF.

## [V4.3, parte 8] — Modelo de imagem qwen2.5vl:7b e chave de acesso lida na foto (2026-11-24)

### Alterado
- `OLLAMA_MODELO_VISAO` passa a ser `qwen2.5vl:7b`. Medição de 24/11 (`comparar-modelos-visao.bat`, nota da moto):
  - qwen2.5vl:7b: loja, data e hora de emissão, CNPJ, chave de acesso, protocolo e valor certos (13,2 s);
  - gemma3:4b: loja, ano, CNPJ e chave errados (5,9 s).
- `instalar-modelo-visao.bat` baixa o qwen2.5vl:7b.

### Adicionado
- `nfce_service.chave_valida` (dígito verificador, módulo 11) e `chave_no_texto`: a chave de acesso lida na transcrição da foto só vale se o dígito conferir.
  - Com chave válida, a nota já registrada é recusada ("mesma chave de acesso, lida na foto") e a chave é gravada na entrada.
- Suíte: 337 testes.

## [V4.3, parte 7] — M34: foto de nota em duas etapas, com conferência (2026-11-24)

### Adicionado
- `services/imagem_service.py`: recorta as margens brancas, divide cupom comprido em faixas com sobreposição (até 6) e amplia imagem pequena antes de enviar ao modelo.
- `LocalLLMProvider.gerar_texto_imagem`: transcrição com limite de tokens e penalidade de repetição (o gemma3:4b entrou em laço "C/C/C…" na nota da moto).
- **Duas etapas** em `DocumentosService._importar_imagem`:
  1. o modelo de imagem só transcreve o texto (faixa por faixa);
  2. a transcrição passa pelos leitores exatos de NFC-e/NF-e, quando reconhecida, ou pelo modelo de texto (gemma4), que é melhor com estrutura. Sem transcrição útil, cai na leitura direta em JSON de antes.
  - A transcrição fica guardada na origem do registro (`entradas.texto`).
- **Conferência antes do "sim"** para compras lidas de foto: "Li a loja como X. Está certo?" e, quando a data parece errada (no futuro ou com mais de um ano), "Qual é a data certa?". Nessas perguntas, "sim" mantém o valor e segue.
- `testar_visao.py --modelos a,b` e `comparar-modelos-visao.bat` (gemma3:4b × qwen2.5vl:7b, com download opcional).
- **Teste no PC (24/11, nota da moto):** transcrição completa, sem laço, valor certo. Dois problemas corrigidos em seguida:
  - o gemma4 trocou a data lida ("06/11/2020") pela de hoje, e a conferência não perguntou. Agora vale a data da transcrição (a de emissão primeiro) e a pergunta aparece se ela parecer errada;
  - a transcrição guardada trazia o bloco do destinatário. `nfce_service.ocultar_consumidor` tira o destinatário, a linha do consumidor e qualquer CPF do texto guardado e do texto enviado ao modelo (também no texto colado). Os textos já gravados no banco de teste foram limpos.
- `tests/test_m34.py` (8 testes). Suíte: 336 testes.

## [V4.3, parte 6] — Observações e ajustes inteligentes nas compras (2026-11-24)

### Adicionado
- **Observações** (migração v9: `compras.observacao`, `itens_compra.observacao`):
  - na compra inteira ("adicione uma observação nessa compra: \"JAVEP | Royal Enfield | Classic 650\"") ou num item ("no vinho anote \"presente da Ana\""), ou em todos os itens;
  - acrescentar (padrão), trocar ou apagar;
  - aparecem com 📝 nos resumos e na lista de compras das consultas.
  - Texto da observação que não está na frase é descartado (o modelo não inventa); sem modelo, regras leem o texto entre aspas ou depois de "obs:".
- **Ajustes somados antes do "sim":**
  - com uma correção esperando confirmação, outro pedido ("e adicione a observação…") entra na mesma proposta;
  - com uma compra nova esperando confirmação (nota, foto, texto), pedidos de ajuste (observação, nome, valor, data, loja, tirar item) são aplicados a ela, mesmo no meio das perguntas de loja ou nome cortado.
- **Aviso de compra repetida:** nota sem chave de acesso (foto, PDF digitalizado) com o mesmo valor de uma compra dos últimos 120 dias recebe o aviso "Pode ser repetida: a compra #N…".
- `tests/test_observacoes.py` (7 testes). Suíte: 328 testes.

### Alterado
- Gatilho "observação/obs" leva à correção de compras. Registro de correção passa a `edicao-v2` (guarda todos os pedidos somados).

### Contexto
- No PC, a foto da nota da moto (lida pelo `gemma3:4b`) gravou a compra #9, repetida da #8, com loja e produto mal lidos ("VAGA MOTORS SERVIÇOS", "C.C. 1000") e data de hoje. O aviso de repetida teria apontado a #8.

## [V4.3, parte 5] — M20: histórico persistente com janela (2026-11-24)

### Adicionado
- `app/sessao.py` reescrito:
  - **Janela:** o modelo recebe só as últimas `HISTORICO_JANELA_TROCAS` trocas (padrão 6). Antes o histórico crescia sem limite enquanto o assunto não mudava.
  - **Resumo:** as trocas que saem da janela viram um resumo curto feito pelo modelo local em segundo plano (não atrasa a resposta); ele vai no começo do histórico. Se o modelo falhar, as trocas antigas só saem.
  - **Gravação:** cada troca vai para `historico_conversas` (SQLite local). Ao reabrir o app em até `HISTORICO_RETOMAR_HORAS` (padrão 12), a conversa continua, com aviso no chat.
  - "nova conversa" (ou "limpar a conversa", "esqueça essa conversa") começa do zero; o que foi gravado fica no banco, numa sessão encerrada.
- Migração v8: coluna `contexto` e índice em `historico_conversas`.
- `tests/test_m20.py` (6 testes). Suíte: 321 testes.

### Alterado (M34)
- `OLLAMA_MODELO_VISAO` passa a ser `gemma3:4b`. Medição de 24/11 com `testar-visao.bat`: o `gemma4:e4b` descreveu como "arte abstrata, sem texto" até uma imagem de controle com texto grande em fundo branco; é o problema aberto no Ollama para Windows (issue 16597), em que o gemma3 lê a mesma imagem.
- `instalar-modelo-visao.bat`: baixa o `gemma3:4b` (≈ 3,3 GB) e roda o teste.

### Mantido
- Mudar de assunto (contexto) zera janela e resumo, como antes.
- A nuvem continua recebendo histórico só quando a conversa em curso é de contexto liberado (`geral`, `outro`).

## [V4.3, parte 4] — M10: corrigir compras (2026-11-24)

### Adicionado
- **Correção de compras pelo chat:** "o vinho custou 35", "renomeie c... para moto", "eram 2 litros de leite", "a compra do Muffato foi dia 13/11", "tire o detergente da última compra", "a loja era o Moreschi".
  - `skills/compras/prompts/edicao.md` + `ESQUEMA_EDICAO_COMPRA`: o modelo só diz o que mudar (campo, item, valor).
  - `services/edicao_compra.py`: localiza a compra (número citado, loja, data ou item; sem pista, a última registrada), acha o item, refaz as contas (total = unitário × quantidade) e descreve o antes e depois. Sem modelo, regras cobrem as frases comuns.
  - Número que não está na frase é descartado (o modelo não inventa valor).
  - `DatabaseService.obter_compra` e `editar_compra`: grava numa transação só depois do "sim"; o estoque perde o que o item antigo somou e recebe o novo; o total da compra é refeito pela soma dos itens; renomear liga o item ao produto certo do catálogo.
  - A correção fica registrada em `entradas` (tipo `edicao`, com a compra antes e depois).
- Gatilhos de "corrigir" na skill compras (corrija/edite/altere, renomeie, "na verdade … custou", "tire … da compra").
- `tests/test_m10.py` (8 testes); `evals/casos.jsonl` r54–r57. Suíte: 315 testes.

### Alterado
- Pergunta do nome cortado ficou mais clara ("Qual produto você comprou? … em <loja>"): no teste do usuário, o nome da loja foi dado como nome do produto.
- `tests/dados/roteador_referencia.json`: "Corrige a compra de ontem…" agora é decidido por regra (corrigir), não mais pelo modelo.

### Decisões
- **M35 descartado:** a categoria original de cada item continua guardada (decisão do M07, coberta por teste); a categoria fechada vem do catálogo `produtos`, que é o que as consultas usam.

### Limitações
- A memória por significado (ChromaDB) guarda o nome antigo do item corrigido até a próxima reconstrução dos embeddings.

## [V4.3, parte 3] — M19: consultas de gastos (2026-11-23)

### Adicionado
- `services/periodos.py`: períodos em português viram datas por regra fixa ("2026", "novembro", "mês passado", "últimos 30 dias", "de 01/10 a 15/11", "ultimamente"...). Abreviações curtas ("mar", "dez") só contam perto de "de/em".
- `services/consultas_service.py`: consultas prontas e parametrizadas, em centavos:
  - listar compras (as 10 mais recentes + total), total gasto, gastos por categoria e por loja, preço de um produto (último, menor, média e onde), comparação de períodos.
  - Loja e produto comparados sem acento e por trecho ("muffato" acha "Irmãos Muffato").
  - Categoria vem do catálogo (M07); itens antigos usam a categoria do item, normalizada.
- `skills/compras/prompts/consulta.md` + `ESQUEMA_CONSULTA_GASTOS`: o modelo só preenche o formulário (tipo, categoria, loja, produto); não escreve SQL nem datas.
  - Sem modelo (Ollama fora), regras escolhem o tipo.
  - Loja ou produto que não aparece na pergunta é descartado (o modelo às vezes copia o exemplo do prompt).
- `evals/consultas.jsonl` (15 casos) e `avaliar.py --so-consultas`; `medir-consultas.bat`.
- `tests/test_m19.py` (13 testes). Suíte: 306 testes.

### Alterado
- "Consultar" da skill compras deixou de responder "ainda não disponível".

## [V4.3] — Notas fiscais por arquivo: NFC-e (HTML), PDF, foto, pasta de entrada e Telegram (2026-11-23)

### Adicionado
- `services/nfce_service.py`: leitor da página da NFC-e da Sefaz (HTML), sem IA.
  - Lê estabelecimento, CNPJ, data de emissão, itens (código, quantidade, unidade, unitário, total), desconto, valor pago, forma de pagamento e chave de acesso.
  - **Não lê os dados do consumidor** (CPF, nome).
  - O desconto é distribuído entre os itens, proporcionalmente e em centavos, de modo que a soma dos itens fica igual ao valor pago.
  - O tamanho da embalagem é lido do nome ("500ML" vira 0,5 litro no estoque).
- `services/documentos_service.py`: importa HTML da NFC-e, PDF (texto via `pypdf`) e foto (modelo local que entende imagem, `OLLAMA_MODELO_VISAO`).
  - O modelo local só torna legíveis os nomes abreviados do cupom e escolhe a categoria.
  - O original é copiado para `Anexos/AAAA-MM/`; a chave de acesso impede registrar a mesma nota duas vezes (migração v7: `entradas.chave_documento`).
  - Foto e PDF vêm marcados para revisão.
- `services/pasta_entradas_service.py`: a pasta `E:\Agente IA\Entradas` é vigiada.
  - A nota salva ali vira um resumo com "sim/não"; depois o arquivo vai para `processados/` ou `com_erro/`.
- **Telegram:** arquivos e fotos mandados ao bot vão para a pasta de entrada; o resumo volta ao chat do celular e a confirmação é feita no PC.
- `LocalLLMProvider.gerar_json_imagem`.
- **App (Electron):** botão 📎 no chat e arrastar-e-soltar para enviar HTML da nota, PDF ou foto (JPG, PNG, WEBP).
  - O arquivo continua onde estava (só os da pasta de entrada são movidos); o original vai para `Anexos/`.
  - Com uma confirmação já pendente, o app avisa e mostra o resumo depois do "sim" ou "não".
- **PDF sem texto** (página salva como imagem): a imagem de dentro do PDF vai para o leitor de fotos.
- **Foto sem itens reconhecidos:** a resposta do modelo fica no registro de eventos (`imagem_sem_itens`) e a mensagem sugere mandar o HTML da página da Sefaz.
- `scripts/testar_visao.py` + `testar-visao.bat` (arrastar a imagem sobre o .bat): mostra o que o modelo de imagem enxerga.
- **Texto da nota colado no chat:** usa o mesmo leitor exato do HTML (desconto distribuído, confirmação antes de gravar).
- **NF-e (modelo 55) colada no chat** (compra em loja: moto, eletrônico, móvel): leitor exato da consulta da Sefaz — loja (emitente), CNPJ, data, itens, total e chave. Os dados do destinatário não são lidos.
- Mensagens dizem "loja" em vez de "mercado" ("Loja não informada.").
- `services/perguntas_compra.py`: antes do "sim", o assistente **pergunta o que falta** — a loja (quando não veio) e o nome de cada produto cortado ("C...").
  - A resposta preenche o campo e puxa a próxima pergunta; no fim mostra "Ficou assim" e pede "sim" ou "não".
  - "pular" mantém o que veio na nota; "sim" grava como está; "não" descarta.
  - Vale para texto colado, arquivo (app, pasta, Telegram) e compra digitada sem loja.
  - Descrição cortada pela própria Sefaz ("C...") não vai ao modelo local (ele inventaria um nome).
- `tests/test_documentos.py` (14 testes, com a sua nota real e o CPF trocado por um fictício). Suíte: 294 testes.

### Pendente no PC
- Testar PDF e foto pelo app e pelo Telegram (pypdf já instalado; texto colado testado e aprovado).
- Confirmar se o `gemma4:e4b` lê fotos no seu Ollama; se não, definir outro modelo de visão em `OLLAMA_MODELO_VISAO`.

## [V4.3, parte 1] — Catálogo, centavos e estoque: M07, M08, M06 (2026-11-23)

### Adicionado
- **M07 — catálogo de produtos e categorias fechadas** (migração v4):
  - 15 categorias fechadas, no esquema de saída e no prompt da extração.
  - Tabela `produtos`: "Leite 1L", "leite" e "leites" são o mesmo produto.
  - Produto novo é cadastrado sozinho, e cada item aponta para ele (`itens_compra.produto_id`).
  - Itens antigos entram no catálogo na migração, com a categoria deduzida do nome do produto. O texto original fica preservado.
- **M08 — dinheiro em centavos inteiros** (migração v5):
  - Colunas `*_centavos` em `compras` e `itens_compra`, preenchidas na entrada e na migração (meio centavo para cima).
  - Total da compra somado em centavos; exibição em `R$ 1.234,56`.
  - As colunas REAL antigas continuam preenchidas.
- **M06 — compras alimentam o estoque** (migração v6):
  - Cada item gravado soma ao estoque do produto na mesma transação, em unidade base (kg, litro, un); embalagens são convertidas ("2 pacotes de 5 kg" → 10 kg).
  - O ritmo de consumo é aprendido na recompra; desfazer a compra tira do estoque.
  - "Ainda tenho leite?" responde com quantidade e unidade, sem depender de acentos.

### Corrigido
- **P1:** compras não alimentavam o estoque.

### Testes
- `tests/test_m07.py`, `test_m08.py`, `test_m06.py`. Suíte: 271 testes.
- Migrações v3 a v6 conferidas numa cópia do banco real: 4 compras e 11 itens preservados, totais em centavos iguais à soma dos itens.

### Limitações
- O estoque começa vazio: compras antigas não entram, porque sem ritmo conhecido apareceriam como estoque cheio.
- Sem perguntas de confirmação de sobras (P8); o código antigo de estoque por voz continua sem uso.

## [V4.2] — Medir antes de mudar: M09, M13, M15, M16 (2026-11-23)

### Adicionado
- **M09 — origem de cada registro:** tabela `entradas` (migração v3) com, para cada pedido de compra:
  - texto original e canal (`chat` ou `voz`);
  - o que o modelo devolveu, o modelo, a versão do prompt (hash de 8 caracteres) e a duração.
  - É gravada na mesma transação da compra (`compras.entrada_id`); descartadas e desfeitas também ficam registradas.
- **M13 — conjunto de avaliação:**
  - `scripts/avaliar.py` guarda o histórico de cada medição em `Planejamento/medicoes/historico-avaliacao.jsonl` e mostra as últimas no relatório.
  - Mede o acerto da extração por campo (itens, total, mercado, embalagem) e registra a versão dos prompts do orquestrador e da extração.
  - As medições de 23/11 (SK0 e SK2) entraram no histórico.

### Alterado
- **M16 — nuvem por escolha:** a conversa geral responde localmente por padrão. O Gemini entra quando a pessoa pede ("pergunta pro Gemini", "pesquisa na internet", "procura no Google") ou quando o modelo local falha. O campo `dificuldade` saiu do prompt e do esquema do orquestrador.
- **M15 — prompt enxuto:** registrado como feito pelo SK2 (prompt fixo pelo catálogo: 1.624 → 325 tokens lidos); com o M16, o prompt ficou ainda menor.

### Testes
- `tests/test_m09.py` (8), M16 em `test_sk2.py` e `test_fase1.py`, M13 em `test_sk0.py`. Suíte: 250 testes.

### Medido no PC (23/11, 19:48)
- Escolha da skill com o prompt sem `dificuldade`: 50/53 (antes 44/48), p50 0,75 s e p95 0,83 s (antes 0,87 e 1,01 s), 16 tokens gerados (antes 27).
- Os 3 erros restantes:
  - r53 ("me dê ideias de melhorias...") vai para `ideias`, mas no app o encaminhamento do P23 manda à conversa geral;
  - r43 e r47 são capacidades futuras.

### Decisões
- M14 (classificador por similaridade) descartado: o catálogo já atinge a meta de p95 abaixo de 1 s.

## [V4.1] — M27: configuração e portabilidade; M02: integração contínua na v4.1 (2026-11-23)

### Adicionado
- Configuração no `.env` (`core/config.py`):
  - `OLLAMA_MODELO_PADRAO` e `OLLAMA_MODELO_AVANCADO`.
  - `OLLAMA_TIMEOUT` e `OLLAMA_KEEP_ALIVE`.
  - `RETRY_TENTATIVAS` e `RETRY_ESPERA_S`.
  - O endereço do servidor continua em `OLLAMA_HOST`.
- Electron escolhe o Python assim: `ASSISTENTE_PYTHON`, senão `.venv` do projeto, senão `python` (Windows) ou `python3`.
- `scripts/fixar_versoes.py` e `fixar-versoes.bat`: geram `requirements-lock.txt` com as versões exatas instaladas das dependências.
- `LICENSE` (MIT) e `"license": "MIT"` no `package.json`.
- `tests/test_m27.py` (7 testes). Suíte: 238 testes.

### Alterado
- `llm_provider.py` e `app/main.py` leem modelos, tempos e repetição da configuração (antes fixos no código).
- Bipes do modo voz: `winsound` só no Windows; nos outros sistemas, silêncio, sem erro.
- Integração contínua também roda em push na `v4.1`.
- `requests` entra no `requirements-ci.txt` (usado pelo Claude e pelo Telegram).

### Corrigido
- P16: Python ausente derrubava o Electron sem aviso; agora o erro aparece na interface com a orientação.

## [V4.1] — P23: pedido de sugestões não é ideia salva (2026-11-23)

### Corrigido
- P23, no chat: "Me dê ideias de melhorias para a documentação" ia para a skill `ideias` e respondia "Não encontrei essa ideia".
  - A skill só consulta quando o pedido se refere a uma ideia salva ("minhas ideias", "ideia 3", "a ideia do...", "que salvei"); o resto vai para a conversa geral.
  - Pedido ou pergunta também não é salvo como ideia.
- P23, no Telegram: perguntas e pedidos ("analise a documentação...", "me diga como está o projeto") viravam ideias. Agora o bot explica que não salvou.

### Adicionado
- `Resposta.encaminhar` no motor das skills: um roteiro pode devolver o pedido a uma skill de execução `nucleo` (hoje, a conversa geral).
- No Telegram, "ideia: ..." e "/ideia ..." salvam sempre, mesmo que o texto pareça pergunta.
- `tests/test_ideias.py`: 4 testes do P23. Suíte: 231 testes.

### Alterado
- A descrição da skill `ideias` deixa claro que pedir ideias ou sugestões ao assistente não é com ela.

## [V4.1] — Ideias de projetos, Claude pela assinatura e bot do Telegram (2026-11-23)

### Adicionado
- Skill `ideias`:
  - "tive uma ideia: ..." salva no SQLite na hora (tabela `ideias`).
  - "minhas ideias" e "ver ideia 3" listam e mostram.
  - "como sigo a ideia X?" é respondida pelo modelo local com a análise salva, sem internet.
- `services/ideias_service.py`:
  - Fila de análise em segundo plano: o Claude devolve título, resumo, MVP, como construir, riscos, próximos passos e perguntas (`skills/ideias/prompts/analise.md`).
  - Sem Claude disponível, a ideia fica pendente e é tentada de novo a cada `IDEIAS_RETESTE_MIN`.
  - A análise vai para o banco e para `Ideias/ideia-NNNN-*.md` (fora do Git), que entra na biblioteca local.
- `services/claude_assinatura_service.py` (`CLAUDE_MODO=assinatura`, padrão): usa o Claude Code logado no plano (`claude -p`), sem chave de API.
  - Sem ferramentas: `--tools ""` e sem MCP.
  - Roda numa pasta temporária, sem gravar sessão, e com `ANTHROPIC_API_KEY` retirada do ambiente.
  - Limite do plano: reteste em `CLAUDE_ASSINATURA_RETESTE_MIN`. Sem login: reteste na manhã seguinte.
  - O modo `api` continua disponível.
- `services/telegram_service.py`: bot opcional para mandar ideias do celular.
  - Long polling, sem expor o PC; só os chats de `TELEGRAM_CHAT_IDS` são atendidos.
  - Comandos `/ideias`, `/ver N`, `/reanalisar N`.
  - A análise volta para o chat de origem. O token nunca vai para os logs.
- `testar-claude-assinatura.bat` (instalação, login e resposta) e `configurar-telegram.bat` (descobre o número do chat).
- `tests/test_ideias.py` (20 testes) e 4 casos de avaliação. Suíte: 226 testes.

### Alterado
- `CLAUDE_SKILLS` padrão: `programacao,ideias`.
- A biblioteca aceita pastas extras, lidas a cada indexação.

### Validação no PC (23/11)
- Claude Code instalado e logado no plano (`instalar-claude-code.bat`): resposta em 5,5 s.
- Três ideias mandadas pelo Telegram foram analisadas em cerca de 20 s cada, e as análises voltaram ao chat.

### Privacidade
- O texto da ideia vai ao Claude; a consulta sobre a ideia fica local.
- Pelo Telegram, a mensagem passa pelos servidores do Telegram.

## [V4.1] — SK7: agenda (2026-11-23)

### Adicionado
- Agenda funcional, feita só com `skills/agenda/` (sem alteração em `core/` ou `app/`), no SQLite local (tabela `compromissos`, criada pela skill).
  - Anotar: o modelo local extrai título, data e hora (`prompts/extracao.md`, com a data de hoje); o código valida; sem data, pergunta "para quando?" e a resposta completa o pedido.
  - Consultar: sem modelo; hoje, amanhã, dia da semana, data (26/11), mês; padrão: próximos 7 dias.
  - Cancelar o último compromisso, com confirmação.
- Gatilhos novos: "o que tenho hoje/amanhã/na semana", "na agenda" e "cancelar compromisso".
- `skills/agenda/exemplos.jsonl` e `tests/test_sk7.py` (8 testes). Suíte: 206 testes.

### Corrigido
- P9: a agenda grava e consulta compromissos.

### Limitações
- Sem aviso na hora do compromisso (precisa de agendador no núcleo) e sem Google Agenda: ficam para a V7.

## [V4.1] — SK6: fábrica de skills (2026-11-23)

### Adicionado
- `skills/_modelo/` e `scripts/nova_skill.py`: cria `skills/<nome>/` com `SKILL.md`, `roteiro.py` e `exemplos.jsonl` já válidos; recusa nome inválido, skill existente, descrição curta e contexto já usado, sem deixar pasta pela metade.
- `scripts/validar_skills.py`: cabeçalhos, roteiros importáveis, marcadores dos prompts e `exemplos.jsonl`. Novo passo **Validar skills** na integração contínua.
- `scripts/avaliar.py --skill <nome>`: mede no PC se o orquestrador escolhe a skill para os exemplos dela.
- Serviço `llm_local` (modelo residente) entregue a toda skill, para que uma skill nova use o modelo sem mudar o núcleo.
- `tests/test_sk6.py` (7 testes). Suíte: 198 testes.

### Alterado
- O catálogo ignora pastas que começam com `_` ou `.` (o modelo `skills/_modelo` não é uma skill).

## [V4.1] — SK5: remoção do código antigo e divisão do main.py (2026-11-23)

### Removido
- Orquestrador por contextos fixos (prompt de ~250 linhas) e a opção `ORQUESTRADOR_MODO`: o orquestrador pelo catálogo foi confirmado no PC (44/48 em 0,87 s contra 43/48 em 1,39 s). O código antigo está no histórico do Git até o commit `d128516`.
- `ESQUEMA_ORQUESTRADOR` e as listas de valores do orquestrador antigo em `services/esquemas.py`.
- No assistente local, os ramos de compras e agenda que ficaram inalcançáveis (essas skills têm roteiro). Também `PROMPT_PROGRAMACAO` e `_sanitizar_resposta_json` do `gemma_service.py`, sem uso.
- `services/gemma_service.py`: 373 → 159 linhas.

### Alterado
- A skill `documentar-projeto` passou a ter roteiro (`skills/documentar-projeto/roteiro.py`). O `app/main.py` não tem mais nenhum `if contexto ==`: todas as skills, exceto `conversa-geral`, executam o próprio roteiro.
- Os contextos válidos na decisão do orquestrador vêm do catálogo (`gemma_service.valores_permitidos()`). Antes eram uma lista fixa, e uma skill nova com contexto próprio seria recusada quando escolhida pelo modelo.
- `app/main.py` dividido (974 → 788 linhas): `app/ipc.py` (UTF-8, pipe do Electron isolado e `emitir_electron`), `app/sessao.py` (`GerenciadorDeSessao`) e `app/voz.py` (modo voz e laço do microfone, classe base do runtime). O pipeline continua no `main.py`.

### Decisões (23/11/2026)
- O código de estoque nunca ligado ao app (validação por voz, baixa direta; P8 e P20) fica até a V4.3, que refaz o estoque dentro da skill.
- Divisão segura do `main.py`: o pipeline e o orquestrador continuam onde estão, para não reescrever os testes.

### Testes
- 191 de 191 aprovados. Saíram 5 testes do orquestrador antigo e entrou 1: o contexto de uma skill nova é aceito quando o modelo a escolhe.
- Teste de fumaça do processo real, numa cópia do projeto: `app/main.py` por pipe (como o Electron), com respostas de estoque, desfazer compra e agenda pelos roteiros, sem erros.

## [V4.1] — SKP: programação com Claude (API) e Qwen local como reserva (2026-11-23)

### Adicionado
- `services/claude_service.py`: chamada à API do Claude com `requests` (sem pacote novo). Sem chave, fica desligado.
  - Cota esgotada, teto de gasto, cobrança ou chave recusada (429 sem `retry-after`, 402, 401/403, 400 de limite de gasto) deixam o Claude indisponível até a **primeira solicitação depois das 8h** (`CLAUDE_HORA_RETESTE`). Com `retry-after`, até o horário indicado.
  - Sobrecarga, timeout, erro interno e falha de rede afetam só a solicitação em curso.
  - Gasto do mês estimado pelos tokens de cada resposta; ao passar de `CLAUDE_LIMITE_MENSAL_USD` (padrão US$ 5), o Claude volta no mês seguinte.
  - Estado em `core/database/estado_claude.json`, ignorado pelo Git; nenhuma chave é registrada.
- `services/biblioteca_service.py` e `scripts/indexar_biblioteca.py`: biblioteca de contexto no ChromaDB (coleção `biblioteca_projeto`), com reindexação só do que mudou. Fontes: README, CHANGELOG, `Sobre a Versão`, skills e a documentação gerada pelo ProjectAnalyzer. A pasta de planejamento fica de fora.
- `skills/programacao/roteiro.py`: busca de 6 trechos na biblioteca → Claude → Qwen local (`qwen2.5-coder:7b`), informando o motivo quando o Qwen responde no lugar do Claude.
- `scripts/testar_skp.py` e `testar-skp.bat`: chamada mínima ao Claude, indexação e a mesma pergunta pelos dois provedores, com relatório.
- Opções no `.env`: `ANTHROPIC_API_KEY`, `CLAUDE_MODELO` (padrão `claude-sonnet-5-5`), `CLAUDE_LIMITE_MENSAL_USD`, `CLAUDE_PRECO_ENTRADA`, `CLAUDE_PRECO_SAIDA`, `CLAUDE_HORA_RETESTE`, `CLAUDE_SKILLS`.
- Privacidade `claude` no cabeçalho das skills. A política fica no núcleo: o serviço do Claude só é entregue às skills de `CLAUDE_SKILLS` (padrão: `programacao`) que declaram `privacidade: claude`, e um teste garante que as duas listas concordam.
- `tests/test_skp.py` (18 testes). Suíte: 195 testes.

### Alterado
- A skill `programacao` passou a ser executada pelo próprio roteiro, com privacidade `claude`. Antes usava o modelo ativo (Gemma ou Qwen) com o prompt de programação.
- `scripts/conferir_chaves.py` informa se a chave do Claude está no `.env`, sem exibi-la.

### Decisões (23/11/2026)
- Só a skill de programação pode enviar dados ao Claude; compras, estoque e agenda nunca saem da máquina.
- Acesso por API com chave própria. Endpoint, cabeçalhos e erros conforme a documentação oficial (https://platform.claude.com/docs/en/api/errors).
- Reteste na primeira solicitação depois das 8h, e não em horário fixo: funciona mesmo com o PC desligado de manhã.

### Não verificado
- Chamada real ao Claude e a biblioteca no ChromaDB: dependem do PC (`testar-skp.bat`).

## [V4.1] — SK3: compras, estoque e agenda executam o roteiro da própria skill (2026-11-23)

### Adicionado
- `core/skills/motor.py`: carrega `skills/<nome>/roteiro.py` e executa `executar(ctx, texto, decisao)`; `responder_pendencia(ctx, texto, dados)` trata a resposta a um pedido de confirmação. O roteiro recebe só os serviços e a política de repetição do núcleo (`Contexto`), sem acesso ao runtime, ao Electron ou à política de nuvem.
- Campo `execucao` no cabeçalho das skills: `roteiro` (passos em `roteiro.py`, em ordem fixa) ou `nucleo` (ainda executada por `app/main.py`).
- `skills/compras/roteiro.py`, `skills/estoque/roteiro.py` e `skills/agenda/roteiro.py`, com a lógica e os textos que estavam no `main.py`.
- `tests/test_sk3.py` (7 testes), entre eles: uma compra registrada usa **uma** chamada ao modelo; uma skill nova com confirmação funciona sem mudar o núcleo. Suíte: 177 testes.

### Alterado
- `app/main.py`: os ramos de compras, estoque e agenda foram substituídos por uma chamada ao roteiro da skill do contexto; `_processar_compras` e `_responder_confirmacao_compra` saíram do arquivo.
- A compra aguardando confirmação virou uma pendência genérica (`self.pendencia = (skill, dados)`): a próxima mensagem vai para a skill que perguntou, sem passar pelo orquestrador. `compra_pendente` continua disponível para leitura.

### Testes
- 177 de 177 aprovados (Python 3.10, dependências externas simuladas). O texto enviado ao modelo e a extração não mudaram; a medição do SK0 continua valendo.

## [V4.1] — SK2: o orquestrador escolhe a skill pelo catálogo (2026-11-23)

### Medição que motivou (SK0, 23/11/2026, PC do usuário)

| Configuração | Acerto (48 frases) | Tempo da escolha (mediana) | Tokens lidos / gerados |
|---|---|---|---|
| Gemma 4, prompt por contextos (antes) | 43/48 | 1,39 s | 1.624 / 36 |
| **Gemma 4, catálogo (adotado)** | **45/48** | **0,55 s** | 325 / 8 |
| Qwen 2.5 Coder, catálogo | 45/48 | 0,55 s | 375 / 11 |
| Qwen 2.5 Coder, chamada nativa de ferramentas | 31/48 (não chamou nenhuma em 34 de 34) | — | — |

Extração de compras: 6/8 nos dois modelos (as mesmas duas falhas), sem diferença entre raciocínio ligado e desligado. Troca de modelo na VRAM: 13 a 15 s; os dois modelos não cabem juntos.

### Alterado
- `gemma_service.orquestrar_requisicao`: depois dos comandos e dos gatilhos, o modelo escolhe a **skill** pelo catálogo (`core/skills/seletor.py`), com prompt fixo (nome e descrição de cada skill, sem a frase do usuário dentro) e esquema `{skill, acao, dificuldade}`. A resposta é convertida para o formato de decisão que o resto do app já usa.
- Opção `ORQUESTRADOR_MODO` no `.env`: `catalogo` (padrão) ou `contextos` (prompt anterior, mantido como reserva).
- Skill `compras`: gatilho para pesquisa e comparação de preços entre mercados. Na medição, "Pesquise na internet o preço do frango e compare três mercados" ia para a conversa geral, a única skill que pode ir à nuvem.
- O evento `decisao` do registro de eventos traz a skill escolhida.
- `scripts/avaliar.py`: o modo "atual" mede o orquestrador do app no modo configurado e o relatório informa qual.

### Corrigido
- **P10:** `programacao` e `projetos` não estavam entre as opções do orquestrador e só eram alcançadas por regra. Agora todas as skills do catálogo podem ser escolhidas pelo modelo.

### Decisões (23/11/2026)
- **Gemma 4 E4B é o modelo residente**: escolha da skill, compras, estoque, agenda e conversa. Mesmo acerto do Qwen, mais leve, e a troca de modelo custa 13 a 15 s.
- Programação vira modo sob demanda: Claude (API, só a skill de programação) como principal e Qwen com biblioteca de contexto como reserva (etapa SKP, ainda não feita; depende da troca das chaves, M01).
- A opção "não sei" (perguntar ao usuário quando a escolha for incerta) ficou de fora: muda o comportamento medido e precisa de medição própria.

### Testes
- `tests/test_sk2.py` (10 testes). Suíte: 170 de 170 aprovados (Python 3.10, dependências externas simuladas).
- `tests/dados/roteador_referencia.json`: 3 decisões atualizadas de propósito (a frase de pesquisa de preço), com o motivo registrado em cada uma.
- **Confirmado no PC** (23/11/2026, `scripts/avaliar.py --modos atual`, Gemma 4): 44/48 acertos (32/33 nas capacidades atuais) em 0,87 s de mediana, contra 43/48 (28/33) em 1,39 s do prompt anterior, contando também a ação. Os 4 erros ficaram em skills locais (nenhum foi para a conversa geral).

## [V4.1] — Skills: formato, catálogo e ferramenta de medição (SK0 e SK1) (2026-11-23)

Primeiras etapas do roadmap das skills (planejamento, fora do repositório): base para que cada capacidade nova seja uma pasta, sem mexer no núcleo.

### Adicionado
- **SK1 — skills:** pasta `skills/` com seis skills (`compras`, `estoque`, `agenda`, `documentar-projeto`, `programacao`, `conversa-geral`). Cada uma tem `SKILL.md` (cabeçalho YAML com nome, descrição, contextos, estado, privacidade, entradas, saídas e gatilhos, mais as instruções) e, quando usa modelo, `prompts/*.md`. Formato em `skills/README.md`.
- `core/skills/`: carregador e catálogo. Valida cada cabeçalho (campos, nome igual à pasta, regex, prioridades e contextos únicos) e aponta o arquivo e o campo com erro. Os campos `entradas` e `saidas` já aceitam `pdf`, `imagem`, `audio`, `relatorio` e `acao`.
- **SK0 — medição:** `evals/casos.jsonl` (48 frases com a skill esperada, 15 delas de capacidades futuras: PDF, relatórios, Spotify, câmeras, casa) e `evals/compras.jsonl` (8 compras).
- `scripts/avaliar.py`: no PC com o Ollama, mede a escolha da skill em três modos (orquestrador atual, enum do catálogo e chamada nativa de ferramentas) para cada modelo, a extração de compras com o raciocínio desligado e ligado, e o tempo de troca de modelo na VRAM. Relatório em JSON e Markdown.
- `core/skills/seletor.py`: protótipo dos modos "catálogo" e "nativo", usado só pelo `avaliar.py`; não está ligado ao app.
- `tests/test_skills.py` (13 testes) e `tests/test_sk0.py` (10). A suíte passa a ter 160 testes.
- `tests/dados/roteador_referencia.json`: 168 decisões do roteador por regras gravadas antes da mudança; o teste aponta qualquer decisão que mudar.
- `PyYAML>=6.0` em `requirements.txt` e `requirements-ci.txt` (já vinha instalado junto com o ChromaDB; agora é declarado).

### Alterado
- `services/intent_router.py`: as expressões regulares saíram do código e foram para os gatilhos das skills; o módulo aplica o primeiro gatilho que casar, em ordem de prioridade (101 → 46 linhas).
- `services/gemma_service.py`: `PROMPT_PROGRAMACAO` é lido de `skills/programacao/prompts/sistema.md`; o assistente local usa o prompt da skill do contexto (503 → 352 linhas).
- `services/shopping_assistant.py`: o prompt de extração é lido de `skills/compras/prompts/extracao.md` (531 → 422 linhas).
- Os prompts perderam a indentação de 8 espaços que vinha das strings Python; o texto é o mesmo.

### Decisões
- Nomes `compras` e `estoque` em vez de `registrar-compras` e `gerenciar-estoque` (do plano): as duas skills também respondem a consultas.
- A política de nuvem continua no núcleo (`CONTEXTOS_NUVEM`); o campo `privacidade` declara a intenção e um teste garante que os dois concordam.
- Comandos de modo (Qwen) e de análise de projeto com caminho continuam em `gemma_service.py`, antes dos gatilhos; saem no SK2.

### Testes
- 160 de 160 aprovados (Python 3.10, com `ollama`, `python-dotenv` e `google-genai` simulados). Equivalência conferida antes de apagar o código antigo: 0 diferenças nas 168 decisões do roteador e prompts com o mesmo texto.
- `avaliar.py` exercitado de ponta a ponta com um Ollama falso; a medição real (SK0) depende do PC com o Ollama.

## [V4.1] — Cópia de segurança automática e registro de eventos estruturado (2026-11-22)

### Adicionado
- **M11 — cópia de segurança automática:** `services/backup_service.py`. Uma vez por dia, em segundo plano, grava em `core/database/backups/auto/AAAA-MM-DD/` o banco (`VACUUM INTO`, conferido com `PRAGMA integrity_check`), a pasta do ChromaDB compactada (`chroma_db.zip`; o `chroma.sqlite3` é copiado pela API de backup do SQLite) e um `manifesto.json` com tamanhos e SHA-256. A cópia é montada em `AAAA-MM-DD.parcial` e só recebe o nome final quando termina. Retenção: as 7 cópias mais recentes e a mais nova de cada uma das 4 semanas anteriores. Cópias manuais fora de `auto/` não são tocadas. Com o app aberto de um dia para o outro, a verificação se repete a cada hora.
- `scripts/fazer_backup.py`: cópia manual (`--forcar` refaz a de hoje, `--listar` mostra as guardadas).
- **M26 — registro de eventos estruturado:** cada evento vira uma linha JSON em `Logs/eventos-AAAA-MM-DD.jsonl` com `ts`, `nivel`, `componente`, `evento`, `mensagem` e campos extras. Cada solicitação recebe um identificador (`req`) que acompanha todos os eventos dela, com início, fim e duração total. Etapas medidas: `roteamento`, `extracao_compras`, `banco`, `assistente_local`, `nuvem`, `consulta_estoque`, `voz`, `memoria` e `analise_projeto`. Cada tentativa do `execute_with_retry` aparece como uma etapa.
- `scripts/ver_logs.py`: mostra os eventos de um dia em formato legível, filtra por requisição, componente ou nível e resume o tempo por etapa (`--etapas`: mediana, p95 e máximo).
- Opções no `.env`: `LOG_CONTEUDO` (`0` grava só o tamanho do texto do usuário), `LOG_RETENCAO_DIAS` (30), `LOGS_DIR`, `BACKUP_ATIVO`, `BACKUP_DIR`, `BACKUP_DIARIOS` (7) e `BACKUP_SEMANAIS` (4).
- `tests/test_m11.py`: 18 testes; `tests/test_m26.py`: 13 testes; 1 teste de integração em `tests/test_fase1.py`. A suíte passa a ter 137 testes.

### Alterado
- `services/logger_service.py` reescrito sobre o `logging` padrão. `log_geral` e `log_assistente` continuam funcionando; o nível dessas chamadas é deduzido do texto (palavras como "erro" e "falha" viram `ERROR`). Os arquivos `Logs/<módulo>/log.txt` deixam de receber linhas e ficam como histórico.
- A rotação é por arquivo diário, sem renomear arquivos: no Windows, renomear um log aberto por outro processo falha.
- Textos do usuário registrados por `main.py`, `ai_service`, `inventory_assistant`, `shopping_assistant` e `memory_service` passam por `logger.conteudo()`, que respeita `LOG_CONTEUDO`.

### Corrigido
- **P13:** `scripts/rebuild_embeddings.py` apagava a coleção inteira e só recriava compras e estoque, perdendo as memórias `mem_*`. Agora faz uma cópia de segurança, exporta as memórias para `backups/memorias-AAAAMMDD-HHMMSS.json`, reindexa e regrava as memórias com o modelo atual. Se não conseguir ler as memórias, não apaga nada; se não conseguir regravá-las, avisa e mantém a exportação.
- **P22:** `with get_connection()` confirmava a transação, mas não fechava a conexão SQLite. A conexão agora é criada com uma fábrica (`_ConexaoQueFecha`) que fecha ao sair do bloco, inclusive em caso de erro. Os `ResourceWarning` do SQLite sumiram da suíte.

### Decisões
- A cópia roda ao abrir o app, e não em horário fixo, porque o assistente não fica ligado o tempo todo. Uma pasta por dia, com manifesto, permite conferir e restaurar sem ferramenta.
- Um único arquivo de eventos por dia, com o componente em cada linha, em vez de um arquivo por módulo: uma requisição atravessa vários módulos e precisa ser lida em ordem.

### Medições (22/11/2026, ambiente de desenvolvimento)
- Cópia dos dados reais (copiados para uma pasta temporária): 12 ms; banco com 36,9 kB e ChromaDB compactado com 73,7 kB. Contagens iguais à origem em todas as tabelas (4 compras, 11 itens) e 14 de 14 embeddings; `integrity_check` ok no banco e no `chroma.sqlite3` restaurado.

### Não verificado
- Execução no PC do usuário: a primeira cópia automática e o arquivo de eventos aparecem na próxima vez que o app for aberto.
- Cópia do ChromaDB durante uma gravação de memória: o `chroma.sqlite3` é copiado de forma consistente, mas os arquivos do índice HNSW são copiados como estão.
- A suíte foi executada com `ollama`, `python-dotenv` e `google-genai` simulados (sem rede para instalar).

## [V4.1] — Base de engenharia: integração contínua, saída estruturada e início rápido (2026-11-17)

### Adicionado
- `.github/workflows/testes.yml`: a cada push na `V4` e a cada pull request, verifica a sintaxe (Python e JavaScript) e roda a suíte. O linter (ruff) roda em modo informativo, sem reprovar.
- `requirements-ci.txt`: dependências mínimas da suíte (`ollama`, `python-dotenv`, `google-genai`).
- `services/esquemas.py`: JSON Schema das respostas do orquestrador e da extração de compras.
- `tests/test_v41.py`: 25 testes; `tests/test_m17.py`: 7 testes; 3 testes do M17 em `tests/test_fase1.py`. A suíte passa a ter 105 testes.
- Opção `OLLAMA_SAIDA_ESTRUTURADA` (`.env`): `0` volta ao modo JSON simples.
- Opção `OLLAMA_RACIOCINIO` (`.env`): vazio segue o código, `0` desliga e `1` liga o raciocínio (`think`) em todas as chamadas locais. Quando preenchida, prevalece sobre o código.
- `LocalLLMProvider.gerar_json` aceita `raciocinio` e registra tokens e tempos do Ollama em `ULTIMA_CHAMADA`. Modelo sem suporte a `think` recebe a chamada repetida sem o parâmetro.
- **M17 — falhar rápido quando o Ollama está fora:** `garantir_ollama_disponivel()` consulta `/api/tags` com timeout de 2 s antes de chamar o modelo (resultado positivo vale por 30 s). Erro de conexão vira `OllamaIndisponivelException`, tratada como fatal pelo `execute_with_retry`: sem as 3 tentativas e as 2 esperas de 3 s. JSON inválido continua sendo repetido.
- Resposta `MSG_OLLAMA_FORA` com o botão "Tentar de novo" no chat, que reenvia o mesmo texto (`tentar_novamente` no evento `assistant_message`). Pergunta geral com o Ollama fechado segue para a nuvem quando permitido; compras e demais contextos restritos não.
- Aviso no terminal interno, logo após o início, se o Ollama não responder.
- `scripts/medir_m17.py`: abre o app por pipe, envia uma frase e mede o tempo até a resposta, com o Ollama fechado ou aberto.
- `scripts/medir_v41.py`: mede início (M04), orquestrador e extração (M03) contra o Ollama real. Opções `--modelo gemma|qwen`, `--raciocinio padrao|nao|sim`, `--modos` e `--so-orquestrador`; o relatório traz tokens gerados, caracteres de raciocínio e tempos de prompt e geração. Resultados em `Planejamento/medicoes`.

### Alterado
- `LocalLLMProvider.gerar_json` aceita `esquema` e o envia no parâmetro `format` do Ollama. O orquestrador e o `ShoppingAssistant` passam a usá-lo; valores fora das listas permitidas deixam de ser gerados. A validação em Python foi mantida.
- `EmbeddingService`: o construtor não carrega mais o modelo. O runtime inicia a carga em segundo plano e o chat fica disponível antes dela; enquanto carrega, a busca semântica é ignorada (resposta sem RAG).
- A memória de longo prazo passa a ser gravada depois da entrega da resposta.
- `requirements.txt`: `ollama>=0.4.0` (versão a partir da qual `format` aceita esquema).
- O orquestrador chama o Gemma 4 com o raciocínio desligado (`raciocinio=False`). Com ele ligado, padrão do Ollama para o `gemma4:e4b`, cada decisão gerava cerca de 450 tokens, quase todos de raciocínio, para devolver um JSON de quatro campos.

### Corrigido
- `VectorStoreService.upsert_documents` não grava quando os embeddings não puderam ser gerados; antes, o ChromaDB receberia documentos sem vetor próprio.
- A carga da memória semântica em segundo plano travava quando o back-end recebia os comandos por pipe (Electron e `scripts/medir_v41.py`): no Windows, a thread que espera a próxima linha bloqueia outras consultas ao mesmo pipe, e a importação do modelo só seguia na mensagem seguinte. O runtime passa a ler os comandos por um descritor privado (`ENTRADA_IPC`) e troca a entrada padrão por `os.devnull`. Pelo terminal, a memória ficava pronta em 14 s; por pipe, não ficava pronta em 150 s.
- O modelo de embeddings ia para a GPU (`cuda:0`) apesar de o log dizer CPU. Agora usa `EMBEDDING_DEVICE` (`.env`, padrão `cpu`).
- O modelo de embeddings passa a carregar só do cache local (`local_files_only`); antes fazia cerca de 30 consultas ao Hugging Face a cada início. Sem cache, carrega com rede como antes.

### Decisões
- Com biblioteca `ollama` antiga, que recusa o esquema, o provedor repete a chamada com `format="json"` e registra o aviso. Erros de conexão não geram segunda chamada.
- Os esquemas oferecem ao modelo os mesmos valores descritos no prompt; `programacao`, `projetos` e `chavear_modo` continuam restritos às regras (P10 permanece aberto).

### Medições (17/11/2026, PC do usuário, `scripts/medir_v41.py`)
Início do sistema (1 rodada):

| | Antes da V4.1 | V4.1 |
|---|---|---|
| Chat pronto | ≈ 18 s (logs) | 3,5 s |
| Memória semântica pronta | junto com o chat | 13,0 s, em segundo plano |

Orquestrador (8 frases × 2 repetições, modo esquema):

| Configuração | Acertos | Mediana | Tokens gerados (mediana) |
|---|---|---|---|
| Gemma 4 E4B, raciocínio ligado (comportamento anterior) | 16/16 | 8,1 s | 448 |
| **Gemma 4 E4B, raciocínio desligado (adotado)** | **16/16** | **1,2 s** | 36 |
| Qwen 2.5 Coder 7B | 16/16 | 1,5 s | 42 |

Esquema × JSON simples, com raciocínio ligado: orquestrador 14/16 × 15/16 (mediana 8,7 s nos dois); extração de compras 6/6 nos dois (10,8 s × 11,6 s). O Qwen não aceita `think`; foi medido sem o parâmetro.

M17, Ollama fechado (app real, `scripts/medir_m17.py`): resposta em 2,38 s com o botão "Tentar de novo" e aviso no terminal interno; chat pronto em 3,0 s. Pelo código anterior, eram no mínimo 6 s (3 tentativas e 2 esperas de 3 s) e até ≈ 6 min com o Ollama travado. No Windows, a conexão recusada em localhost leva ~2 s para falhar, daí o valor próximo do limite da verificação. Com o Ollama aberto, a mesma frase foi respondida em 18,9 s, sem o botão.

### Não verificado
- Execução do fluxo no GitHub Actions: depende do repositório publicado.
- Extração de compras com o raciocínio desligado: continua no padrão do Ollama até ser medida (`--so-extracao --raciocinio nao`).
- A suíte foi executada no ambiente de desenvolvimento com as dependências externas simuladas; no PC do usuário, só as medições acima.

## [V4] — Correção de acentuação na entrada (2026-11-16)

### Corrigido
- `app/main.py`: a entrada (stdin) do back-end passa a ser lida em UTF-8, como a saída. Antes, no Windows, textos com acento enviados pelo Electron chegavam corrompidos ("café" virava "cafÃ©" no chat e no banco).

## [V4] — Revisão de credenciais (2026-11-16)

### Segurança
- Varredura do código e do histórico Git de todas as branches: nenhuma chave, senha ou token real encontrado. O único token nos testes é falso e montado em partes.
- `.gitignore` passa a cobrir `.env.*`, `*secret*.json`, `*credentials*.json`, `*.pem`, `*.key`, `*.p12` e `*.pfx`.
- `.env.example` documenta as variáveis sem valores reais; o README orienta copiá-lo para `.env`.

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
