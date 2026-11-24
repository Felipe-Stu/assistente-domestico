"""
Roteiro da skill compras (SK3): passos em ordem fixa.

registrar: extrair (modelo, uma chamada) → validar (código) → gravar, ou pedir confirmação se houver dúvida
desfazer:  apagar o último registro
consultar: formulário do modelo (tipo, categoria, loja, produto) + período lido pelo código → consulta pronta (M19)
corrigir:  ainda não implementado; a resposta informa e nada é gravado
"""
import re

from core.skills.motor import Resposta
from services.intent_router import normalizar_texto
from core.skills import obter_catalogo
from services import perguntas_compra
from services.consultas_service import TIPOS, ConsultasGastos, Filtro
from services.esquemas import ESQUEMA_CONSULTA_GASTOS
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
        return Resposta("Ainda não consigo editar compras. Use \"desfazer última compra\" e registre novamente.")

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
    """Resposta do usuário a uma compra aguardando confirmação."""
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
