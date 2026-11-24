"""
Roteiro da skill compras (SK3): passos em ordem fixa.

registrar: extrair (modelo, uma chamada) → validar (código) → gravar, ou pedir confirmação se houver dúvida
desfazer:  apagar o último registro
consultar: formulário do modelo (tipo, categoria, loja, produto) + período lido pelo código → consulta pronta (M19)
corrigir:  formulário do modelo (o que mudar) → o código localiza a compra, refaz as contas e pede "sim" (M10)
"""
import json
import re

from core.skills.motor import Resposta
from services.intent_router import normalizar_texto
from core.skills import obter_catalogo
from services import edicao_compra, perguntas_compra
from services.consultas_service import TIPOS, ConsultasGastos, Filtro
from services.esquemas import ESQUEMA_CONSULTA_GASTOS, ESQUEMA_EDICAO_COMPRA
from services.periodos import encontrar_periodos
from services.produtos_service import normalizar_categoria
from services.nfce_service import parece_nfce_texto, parece_nfe_texto
from services.logger_service import logger as custom_logger

RESPOSTAS_CONFIRMAR = {"sim", "s", "ok", "confirmo", "confirmar", "correto", "pode", "pode gravar", "pode salvar",
                       "gravar", "salvar", "grava", "salva"}
RESPOSTAS_CANCELAR = {"nao", "n", "cancela", "cancelar", "descarta", "descartar", "nao grava", "nao gravar", "nao salve"}


def executar(ctx, texto, decisao):
    compras = ctx.servico("shopping_assistant")
    acao = decisao.get("acao", "")
    parametros = decisao.get("parametros") or {}

    if parametros.get("operacao") == "desfazer":
        return Resposta(compras.desfazer_ultimo_registro())

    if acao == "corrigir":
        return editar(ctx, texto)

    if acao == "consultar":
        return consultar(ctx, texto)

    if acao != "criar":
        return Resposta("Não entendi o que fazer com as compras. Nada foi registrado.")

    documentos = ctx.servicos.get("documentos")
    if documentos is not None and (parece_nfce_texto(texto) or parece_nfe_texto(texto)):
        # Texto copiado da nota fiscal: leitor exato (desconto, data, mercado), sempre com confirmação
        try:
            preparada = documentos.importar_texto(texto, ctx.servicos.get("canal") or "chat")
        except Exception as erro:
            return Resposta(f"Reconheci uma nota fiscal, mas não consegui lê-la: {erro}. Nada foi registrado.")
        aberta = perguntas_compra.abrir("📄 Nota fiscal reconhecida:", documentos.resumo(preparada, com_duvidas=False),
                                        preparada["compras"], preparada["origem"], preparada.get("duvidas"))
        return Resposta(aberta["texto"], fala="Reconheci uma nota fiscal. Confira o resumo no chat.",
                        pendencia=aberta["pendencia"])

    preparada = ctx.repetir(
        custom_logger.cronometrado("extracao_compras", compras.preparar_compra),
        (texto, ctx.servicos.get("canal") or "chat"),
        mensagem_espera_voz="Estou tentando entender sua compra novamente.",
        nome_servico="ShoppingAssistant",
    )

    origem = preparada.get("origem")
    if not preparada["compras"]:
        compras.descartar(origem)
        return Resposta("Não identifiquei itens de compra nessa mensagem. Nada foi registrado.")

    if preparada["duvidas"]:
        aberta = perguntas_compra.abrir("Antes de gravar, confira esta compra:", compras.formatar_resumo(preparada["compras"]),
                                        preparada["compras"], origem, preparada["duvidas"])
        return Resposta(aberta["texto"], fala="Tenho uma dúvida sobre esta compra. Confira no chat.",
                        pendencia=aberta["pendencia"])

    return Resposta(compras.registrar_compras(preparada["compras"], origem)["mensagem"])


def responder_pendencia(ctx, texto, pendente):
    """Resposta do usuário a uma compra (ou correção) aguardando confirmação."""
    if isinstance(pendente, dict) and "edicao" in pendente:
        return _responder_edicao(ctx, texto, pendente)
    # Formato antigo (lista de compras) continua aceito
    compras_pendentes, origem = (pendente["compras"], pendente.get("origem")) if isinstance(pendente, dict) else (pendente, None)
    servico = ctx.servico("shopping_assistant")
    resposta = normalizar_texto(texto).strip(" .,!")
    perguntas = list(pendente.get("perguntas") or []) if isinstance(pendente, dict) else []
    # "sim" no meio das perguntas grava como está; "não" descarta; qualquer outra resposta preenche o campo
    if perguntas and resposta not in RESPOSTAS_CANCELAR and resposta not in RESPOSTAS_CONFIRMAR:
        # Ainda falta um dado (loja ou nome cortado): a resposta preenche o campo da pergunta atual
        atual = perguntas.pop(0)
        if resposta not in perguntas_compra.RESPOSTAS_PULAR:
            perguntas_compra.aplicar_resposta(compras_pendentes, atual, texto)
        novo = dict(pendente, compras=compras_pendentes, perguntas=perguntas)
        if perguntas:
            return Resposta(perguntas_compra.texto_pergunta(perguntas[0], compras_pendentes), pendencia=novo)
        return Resposta(f"Ficou assim:\n{servico.formatar_resumo(compras_pendentes)}\n\n{perguntas_compra.PEDIR_CONFIRMACAO}",
                        fala="Confira o resumo no chat e responda sim ou não.", pendencia=novo)
    if resposta in RESPOSTAS_CONFIRMAR:
        return Resposta(servico.registrar_compras(compras_pendentes, origem)["mensagem"])
    if resposta in RESPOSTAS_CANCELAR:
        servico.descartar(origem)
        return Resposta("Compra descartada. Nada foi gravado.")
    return Resposta(
        "Ainda há uma compra aguardando confirmação. Responda \"sim\" para gravar ou \"não\" para descartar.",
        pendencia=pendente,
    )


# ---------------------------------------------------------------------------
# Consultas de gastos (M19)
# ---------------------------------------------------------------------------

_RE_LISTA_DE_COMPRAS = re.compile(r"\b(lista de compras|(?:preciso|tenho que|devo) comprar)\b")


def _tipo_por_regra(normal: str, periodos) -> str:
    """Plano B quando o modelo não responde: palavras da pergunta decidem o tipo."""
    if len(periodos) >= 2 and re.search(r"\b(mais|menos|compar\w*|diferenca|versus|vs)\b", normal):
        return "comparar"
    if re.search(r"\b(preco|paguei n[oa]|mais barat[oa])\b", normal):
        return "preco_produto"
    if re.search(r"\bpor categoria|com o que\b", normal):
        return "por_categoria"
    if re.search(r"\bpor (loja|mercado)|em qual (loja|mercado)|onde (mais )?gast", normal):
        return "por_loja"
    if re.search(r"\bquanto\b", normal):
        return "total"
    return "listar"


def _formulario(ctx, texto: str) -> dict:
    modelo = ctx.servicos.get("llm_local")
    if modelo is None:
        return {}
    prompt = obter_catalogo().skill("compras").prompt("consulta")
    try:
        dados = custom_logger.cronometrado("consulta_gastos", modelo.gerar_json)(prompt, texto, esquema=ESQUEMA_CONSULTA_GASTOS)
    except Exception as erro:  # Ollama fora ou resposta ruim: a regra decide
        custom_logger.evento("compras", "consulta_sem_modelo", erro=type(erro).__name__, nivel="WARNING")
        return {}
    return dados if isinstance(dados, dict) else {}


def _limpo(valor):
    valor = " ".join(str(valor or "").split()).strip(" .,!?\"'")
    if not valor or valor.lower() in ("null", "none", "nenhum", "nenhuma"):
        return None
    return valor[:60]


def consultar(ctx, texto: str) -> Resposta:
    normal = normalizar_texto(texto)
    if _RE_LISTA_DE_COMPRAS.search(normal):
        return Resposta("Ainda não monto lista de compras. Para ver o que está acabando, pergunte \"o que está acabando no estoque?\".")
    periodos = encontrar_periodos(texto)
    form = _formulario(ctx, texto)
    tipo = form.get("tipo") if form.get("tipo") in TIPOS else _tipo_por_regra(normal, periodos)
    categoria = normalizar_categoria(form.get("categoria")) if form.get("categoria") else None
    produto = _limpo(form.get("produto"))
    loja = _limpo(form.get("loja"))
    if categoria == "outros" and str(form.get("categoria")).lower() != "outros":
        categoria = None
    # A loja só vale se aparecer na pergunta (o modelo às vezes repete o exemplo do prompt)
    if loja and normalizar_texto(loja) not in normal:
        loja = None
    if produto and normalizar_texto(produto).split()[0] not in normal:
        produto = None
    if produto and categoria:
        categoria = None   # o produto já define o que procurar; a categoria do modelo só restringiria (medição de 24/11)
    if tipo == "comparar" and len(periodos) < 2:
        tipo = "total"
    filtro = Filtro(periodo=periodos[0] if periodos and tipo != "comparar" else None,
                    categoria=categoria, loja=loja, produto=produto)
    consultas = ConsultasGastos(ctx.servico("db_service"))
    if tipo == "comparar":
        resultado = consultas.comparar(filtro, periodos)
    else:
        resultado = getattr(consultas, tipo)(filtro)
    custom_logger.evento("compras", "consulta", tipo=tipo, categoria=categoria, loja=bool(loja), produto=bool(produto),
                         periodos=len(periodos))
    return Resposta(resultado.texto)


# ---------------------------------------------------------------------------
# Correção de compras (M10)
# ---------------------------------------------------------------------------

AJUDA_EDICAO = ("Não entendi o que corrigir. Exemplos: \"o vinho custou 35\", \"renomeie c... para moto\", "
                "\"eram 2 litros de leite\", \"a compra do Muffato foi dia 13/11\", \"tire o detergente da última compra\".")
_CAMPOS_NUMERICOS = ("quantidade", "valor_total", "valor_unitario")


def _formulario_edicao(ctx, texto: str) -> dict:
    modelo = ctx.servicos.get("llm_local")
    if modelo is None:
        return {}
    prompt = obter_catalogo().skill("compras").prompt("edicao")
    try:
        dados = custom_logger.cronometrado("edicao_compra", modelo.gerar_json)(prompt, texto, esquema=ESQUEMA_EDICAO_COMPRA)
    except Exception as erro:  # Ollama fora ou resposta ruim: as regras tentam
        custom_logger.evento("compras", "edicao_sem_modelo", erro=type(erro).__name__, nivel="WARNING")
        return {}
    return dados if isinstance(dados, dict) else {}


def _mudancas_validas(form: dict, texto: str) -> list:
    """Descarta o que o modelo inventou: número que não está na frase, campo desconhecido."""
    numeros_da_frase = re.findall(r"\d+", texto)
    validas = []
    for m in form.get("alteracoes") or []:
        if not isinstance(m, dict) or m.get("campo") not in edicao_compra.CAMPOS:
            continue
        if m["campo"] in _CAMPOS_NUMERICOS and not any(d in numeros_da_frase for d in re.findall(r"\d+", str(m.get("valor") or ""))):
            continue
        validas.append({"campo": m["campo"], "item": m.get("item") or None, "valor": m.get("valor")})
    return validas


def _nome_modelo(ctx):
    nome = getattr(ctx.servicos.get("llm_local"), "modelo", None)
    return nome if isinstance(nome, str) else None


def _rotulo_compra(compra: dict) -> str:
    return f"{edicao_compra._data_br(compra['data_compra'])} · {compra['estabelecimento']}"


def editar(ctx, texto: str) -> Resposta:
    db = ctx.servico("db_service")
    form = _formulario_edicao(ctx, texto)
    mudancas = _mudancas_validas(form, texto) or edicao_compra.mudancas_por_regra(texto)
    if not mudancas:
        return Resposta(AJUDA_EDICAO + " Nada foi alterado.")
    compra_id = edicao_compra.localizar_compra(db, texto, mudancas, form.get("loja_da_compra"))
    if compra_id is None:
        return Resposta("Não achei a compra para corrigir. Diga a loja, a data ou o número da compra. Nada foi alterado.")
    compra = db.obter_compra(compra_id)
    try:
        nova, linhas = edicao_compra.aplicar(compra, mudancas)
    except edicao_compra.EdicaoError as erro:
        return Resposta(f"{erro} Nada foi alterado.")
    from services.shopping_assistant import ShoppingAssistant
    visivel = dict(nova, itens=[i for i in nova["itens"] if not i.get("remover")])
    custom_logger.evento("compras", "edicao_proposta", compra=compra_id, campos=[m["campo"] for m in mudancas],
                         origem="modelo" if form.get("alteracoes") else "regra")
    return Resposta(
        f"✏️ Correção da compra de {_rotulo_compra(compra)}:\n" + "\n".join(f"- {linha}" for linha in linhas)
        + f"\n\nFica assim:\n{ShoppingAssistant.formatar_resumo([visivel])}\n\n"
          "Responda \"sim\" para gravar a correção ou \"não\" para manter como está.",
        fala="Preparei a correção. Confira no chat e responda sim ou não.",
        pendencia={"edicao": {"compra_id": compra_id, "antes": compra, "nova": nova, "texto": texto,
                              "modelo": _nome_modelo(ctx) if form.get("alteracoes") else None}},
    )


def _responder_edicao(ctx, texto: str, pendente: dict) -> Resposta:
    dados = pendente["edicao"]
    resposta = normalizar_texto(texto).strip(" .,!")
    if resposta in RESPOSTAS_CANCELAR:
        return Resposta("Correção descartada. A compra continua como estava.")
    if resposta not in RESPOSTAS_CONFIRMAR:
        return Resposta("Há uma correção aguardando confirmação. Responda \"sim\" para gravar ou \"não\" para manter a compra como está.",
                        pendencia=pendente)
    entrada = {"tipo": "edicao", "canal": ctx.servicos.get("canal") or "chat", "texto": dados.get("texto", "")[:20000],
               "resposta_json": json.dumps({"compra_id": dados["compra_id"], "antes": dados["antes"], "depois": dados["nova"]},
                                           ensure_ascii=False)[:20000],
               "modelo": dados.get("modelo"), "versao_prompt": "edicao-v1"}
    try:
        ctx.servico("db_service").editar_compra(dados["compra_id"], dados["nova"], entrada)
    except Exception as erro:
        return Resposta(f"Não consegui gravar a correção ({type(erro).__name__}). A compra continua como estava.")
    nova = dados["nova"]
    return Resposta(f"✅ Compra corrigida: {_rotulo_compra(nova)}, total "
                    f"{edicao_compra.formatar_reais(nova['valor_total_compra'])}.")
