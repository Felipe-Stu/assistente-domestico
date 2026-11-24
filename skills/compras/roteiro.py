"""
Roteiro da skill compras (SK3): passos em ordem fixa.

registrar: extrair (modelo, uma chamada) → validar (código) → gravar, ou pedir confirmação se houver dúvida
desfazer:  apagar o último registro
consultar / corrigir: ainda não implementados; a resposta informa e nada é gravado
"""
from core.skills.motor import Resposta
from services.intent_router import normalizar_texto
from services.nfce_service import parece_nfce_texto
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

    if acao != "criar":
        return Resposta("As consultas de gastos e preços ainda não estão disponíveis. Nada foi registrado.")

    documentos = ctx.servicos.get("documentos")
    if documentos is not None and parece_nfce_texto(texto):
        # Texto copiado da nota fiscal: leitor exato (desconto, data, mercado), sempre com confirmação
        try:
            preparada = documentos.importar_texto(texto, ctx.servicos.get("canal") or "chat")
        except Exception as erro:
            return Resposta(f"Reconheci uma nota fiscal, mas não consegui lê-la: {erro}. Nada foi registrado.")
        return Resposta(
            f"📄 Nota fiscal reconhecida:\n{documentos.resumo(preparada)}\n\nResponda \"sim\" para gravar ou \"não\" para descartar.",
            fala="Reconheci uma nota fiscal. Confira o resumo no chat e responda sim ou não.",
            pendencia={"compras": preparada["compras"], "origem": preparada["origem"]},
        )

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
        duvidas = "\n".join(f"- {d}" for d in preparada["duvidas"])
        resumo = compras.formatar_resumo(preparada["compras"])
        return Resposta(
            f"Antes de gravar, confira esta compra:\n{resumo}\n\nPontos de dúvida:\n{duvidas}\n\n"
            "Responda \"sim\" para gravar ou \"não\" para descartar.",
            fala="Tenho uma dúvida sobre esta compra. Confira no chat e responda sim ou não.",
            pendencia={"compras": preparada["compras"], "origem": origem},
        )

    return Resposta(compras.registrar_compras(preparada["compras"], origem)["mensagem"])


def responder_pendencia(ctx, texto, pendente):
    """Resposta do usuário a uma compra aguardando confirmação."""
    # Formato antigo (lista de compras) continua aceito
    compras_pendentes, origem = (pendente["compras"], pendente.get("origem")) if isinstance(pendente, dict) else (pendente, None)
    servico = ctx.servico("shopping_assistant")
    resposta = normalizar_texto(texto).strip(" .,!")
    if resposta in RESPOSTAS_CONFIRMAR:
        return Resposta(servico.registrar_compras(compras_pendentes, origem)["mensagem"])
    if resposta in RESPOSTAS_CANCELAR:
        servico.descartar(origem)
        return Resposta("Compra descartada. Nada foi gravado.")
    return Resposta(
        "Ainda há uma compra aguardando confirmação. Responda \"sim\" para gravar ou \"não\" para descartar.",
        pendencia=pendente,
    )
