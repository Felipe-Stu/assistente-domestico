"""Roteiro da skill estoque (SK3): consulta por regras, sem modelo; alterações ainda não existem."""
from core.skills.motor import Resposta
from services.logger_service import logger as custom_logger


def executar(ctx, texto, decisao):
    if decisao.get("acao") in ("criar", "corrigir"):
        # Alteração de estoque por texto ainda não implementada (depende de diálogo por chat)
        return Resposta(
            "Por enquanto consigo apenas consultar o estoque por texto. "
            "Alterações de estoque ainda não estão disponíveis neste modo."
        )
    with custom_logger.etapa("consulta_estoque"):
        return Resposta(ctx.servico("inventory_assistant").consultar_estoque(texto))
