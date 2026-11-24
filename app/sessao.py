"""
Contexto ativo e histórico da conversa em curso (M20).

- Janela: o modelo recebe só as últimas HISTORICO_JANELA_TROCAS trocas (antes o histórico crescia sem limite).
- Resumo: as trocas que saem da janela viram um resumo curto, feito pelo modelo local em segundo plano,
  que vai no começo do histórico. Sem modelo, elas apenas saem.
- Persistência: cada troca é gravada em historico_conversas (SQLite local). Ao reabrir o app em até
  HISTORICO_RETOMAR_HORAS, a conversa continua de onde parou. "nova conversa" começa outra.
- Mudança de contexto (ex.: de compras para conversa geral) zera janela e resumo, como antes.
"""
import logging
import threading
from datetime import datetime, timedelta
from typing import Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

PREFIXO_RESUMO = "Resumo da conversa até aqui: "
CONFIRMACAO_RESUMO = "Certo, vou considerar esse contexto."


class GerenciadorDeSessao:
    def __init__(self, janela_trocas: int = 6, agora: Callable[[], datetime] = datetime.now):
        self.janela = max(1, int(janela_trocas)) * 2
        self._agora = agora
        self.contexto_ativo = None
        self.resumo: Optional[str] = None
        self._mensagens: List[Dict[str, str]] = []
        self._lock = threading.Lock()
        self._lock_resumo = threading.Lock()   # um resumo por vez, sempre sobre o resumo mais novo
        self.db = None
        self.resumir: Optional[Callable[[Optional[str], List[Dict[str, str]]], str]] = None
        self.session_id = self._novo_id()
        self.retomada = False

    # ------------------------------------------------------------------ histórico entregue ao modelo

    @property
    def historico(self) -> List[Dict[str, str]]:
        with self._lock:
            mensagens, resumo = list(self._mensagens[-self.janela:]), self.resumo
        if resumo:
            return [{"role": "user", "content": PREFIXO_RESUMO + resumo},
                    {"role": "assistant", "content": CONFIRMACAO_RESUMO}] + mensagens
        return mensagens

    @historico.setter
    def historico(self, mensagens: List[Dict[str, str]]) -> None:
        """Troca o histórico em memória (testes e compatibilidade); não grava no banco."""
        with self._lock:
            self._mensagens = list(mensagens or [])
            self.resumo = None

    # ------------------------------------------------------------------ banco

    def conectar(self, db, resumir=None, retomar_horas: float = 12) -> bool:
        """Liga a sessão ao SQLite e retoma a última conversa, se for recente. Devolve True se retomou."""
        self.db, self.resumir = db, resumir
        try:
            self.retomada = self._retomar(retomar_horas)
        except Exception as erro:   # histórico é conveniência: falha não impede o app de abrir
            logger.warning(f"Não consegui retomar a conversa anterior: {erro}")
            self.retomada = False
        return self.retomada

    def _retomar(self, horas: float) -> bool:
        ultima = self.db.executar_consulta_uma_linha(
            "SELECT session_id, contexto, timestamp FROM historico_conversas ORDER BY id DESC LIMIT 1")
        if not ultima or not ultima[2]:
            return False
        try:
            quando = datetime.fromisoformat(str(ultima[2]).replace(" ", "T"))
        except ValueError:
            return False
        if self._agora() - quando > timedelta(hours=horas):
            return False
        sessao, contexto = ultima[0], ultima[1]
        linha_resumo = self.db.executar_consulta_uma_linha(
            "SELECT id, conteudo FROM historico_conversas WHERE session_id = ? AND contexto IS ? AND papel = 'resumo' "
            "ORDER BY id DESC LIMIT 1", (sessao, contexto))
        # A janela é sempre das últimas mensagens; o resumo (gravado depois delas) cobre as que já saíram
        linhas = self.db.executar_consulta(
            "SELECT papel, conteudo FROM historico_conversas WHERE session_id = ? AND contexto IS ? "
            "AND papel IN ('user', 'assistant') ORDER BY id DESC LIMIT ?", (sessao, contexto, self.janela))
        with self._lock:
            self.session_id, self.contexto_ativo = sessao, contexto
            self.resumo = linha_resumo[1] if linha_resumo else None
            self._mensagens = [{"role": p, "content": c} for p, c in reversed(linhas)]
        logger.info(f"Conversa retomada ({len(linhas)} mensagens, contexto '{contexto}').")
        return bool(linhas) or bool(linha_resumo)

    def _gravar(self, papel: str, conteudo: str, contexto) -> None:
        if self.db is None:
            return
        try:
            self.db.executar_comando(
                "INSERT INTO historico_conversas (session_id, papel, conteudo, timestamp, contexto) VALUES (?, ?, ?, ?, ?)",
                (self.session_id, papel, conteudo, self._agora().isoformat(timespec="seconds"), contexto))
        except Exception as erro:
            logger.warning(f"Histórico da conversa não gravado: {erro}")

    # ------------------------------------------------------------------ conversa

    def atualizar_sessao(self, novo_contexto, mensagem_user, resposta_ai, mudanca_de_contexto=False):
        with self._lock:
            if mudanca_de_contexto or self.contexto_ativo != novo_contexto:
                logger.info(f"🔄 Alterando contexto de '{self.contexto_ativo}' para '{novo_contexto}'. Histórico resetado.")
                self.contexto_ativo = novo_contexto
                self._mensagens, self.resumo = [], None
            self._mensagens.append({"role": "user", "content": mensagem_user})
            self._mensagens.append({"role": "assistant", "content": resposta_ai})
            saindo = self._mensagens[:-self.janela]
            self._mensagens = self._mensagens[-self.janela:]
            contexto = self.contexto_ativo
        self._gravar("user", mensagem_user, novo_contexto)
        self._gravar("assistant", resposta_ai or "", novo_contexto)
        if saindo and self.resumir is not None:
            threading.Thread(target=self._resumir_em_segundo_plano, args=(saindo, contexto),
                             daemon=True, name="resumo-conversa").start()

    def _resumir_em_segundo_plano(self, saindo, contexto) -> None:
        with self._lock_resumo:
            self._resumir_agora(saindo, contexto)

    def _resumir_agora(self, saindo, contexto) -> None:
        with self._lock:
            if self.contexto_ativo != contexto:
                return
            resumo_anterior = self.resumo
        try:
            novo = " ".join(str(self.resumir(resumo_anterior, saindo) or "").split())[:1200]
        except Exception as erro:
            logger.warning(f"Resumo da conversa não gerado: {erro}")
            return
        if not novo:
            return
        with self._lock:
            if self.contexto_ativo != contexto:   # a conversa mudou de assunto enquanto o resumo era feito
                return
            self.resumo = novo
        self._gravar("resumo", novo, contexto)

    def nova_conversa(self) -> None:
        with self._lock:
            self.session_id = self._novo_id()
            self.contexto_ativo, self.resumo, self._mensagens = None, None, []
        self.retomada = False

    def _novo_id(self) -> str:
        return self._agora().strftime("%Y%m%d-%H%M%S-%f")
