"""Contexto ativo e histórico da conversa em curso."""
import logging

logger = logging.getLogger(__name__)


class GerenciadorDeSessao:
    def __init__(self):
        self.contexto_ativo = None
        self.historico = []

    def atualizar_sessao(self, novo_contexto, mensagem_user, resposta_ai, mudanca_de_contexto=False):
        if mudanca_de_contexto or self.contexto_ativo != novo_contexto:
            logger.info(f"🔄 Alterando contexto de '{self.contexto_ativo}' para '{novo_contexto}'. Histórico resetado.")
            self.contexto_ativo = novo_contexto
            self.historico = []

        self.historico.append({"role": "user", "content": mensagem_user})
        self.historico.append({"role": "assistant", "content": resposta_ai})
