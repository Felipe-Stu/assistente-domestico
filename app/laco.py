"""
Partida e laço de comandos do núcleo (M25).

rodar() inicia os serviços, as tarefas de fundo e o laço que consome self.fila. Os comandos chegam
pela ponte antiga (stdin do Electron, ler_stdin=True) ou pelo servidor (app/servidor.py, que só enfileira).
"""
import json
import logging
import queue
import threading

import services.llm_provider as llm_provider_estado
from core.config import BACKUP_ATIVO, BACKUP_DIARIOS, BACKUP_DIR, BACKUP_SEMANAIS, CHROMA_DIR, DB_PATH
from services.ai_service import TokenExhaustedException
from services.audio_service import AudioService
from services.backup_service import BackupService
from services.voice_service import VoiceService

logger = logging.getLogger(__name__)


class LacoDeComandos:
    # -------------------------------------------------------------------------
    # Threads de Leitura
    # -------------------------------------------------------------------------

    def _leitor_stdin(self):
        """Thread daemon para ler comandos do Electron (pipe isolado em ENTRADA_IPC)."""
        while not self.deve_encerrar:
            try:
                from app.ipc import ENTRADA_IPC
                linha = ENTRADA_IPC.readline()
                if not linha:
                    logger.info("Stdin fechado (EOF). Encerrando processo Python.")
                    self.deve_encerrar = True
                    self.fila.put({"type": "shutdown"})
                    break

                conteudo = linha.strip()
                if not conteudo:
                    continue

                try:
                    cmd = json.loads(conteudo)
                    self.fila.put(cmd)
                except json.JSONDecodeError:
                    # Se não for JSON, trata como texto puro (entrada manual no terminal)
                    self.fila.put({"type": "send_text", "payload": {"text": conteudo}})
            except Exception as e:
                logger.error(f"Erro ao processar stdin: {e}")

    # -------------------------------------------------------------------------
    # Loop Principal
    # -------------------------------------------------------------------------

    def _iniciar_backup_diario(self):
        if not BACKUP_ATIVO:
            self._emitir("debug_log", {"message": "Cópia de segurança automática desativada (BACKUP_ATIVO=0)."})
            return
        servico = BackupService(
            db_path=DB_PATH,
            chroma_dir=CHROMA_DIR,
            pasta_backups=BACKUP_DIR,
            diarios=BACKUP_DIARIOS,
            semanais=BACKUP_SEMANAIS,
        )
        servico.iniciar_em_segundo_plano(
            deve_parar=lambda: self.deve_encerrar,
            ao_gravar=lambda pasta: self._emitir("debug_log", {"message": f"✓ Cópia de segurança do dia gravada em '{pasta}'."}),
            ao_falhar=lambda erro: self._emitir("debug_log", {"message": f"⚠️ Cópia de segurança falhou: {erro}"}),
        )

    def rodar(self, ler_stdin: bool = True):
        """Entrypoint principal do runtime. ler_stdin=False no servidor: os comandos chegam pela API."""
        logger.info("Iniciando Assistente Doméstico (Modelo Text-First)")

        # =====================================================================
        # FASE 1: Serviços Essenciais (Chat disponível imediatamente depois)
        # =====================================================================
        self._inicializar_servicos_essenciais()

        # Ponte antiga: comandos do Electron pela entrada padrão
        if ler_stdin:
            threading.Thread(target=self._leitor_stdin, daemon=True).start()

        # Inicia thread do microfone (ficará em espera até voice_mode_active=True)
        t_mic = threading.Thread(target=self._loop_microfone, daemon=True)
        t_mic.start()

        # Varredura inicial do estoque (em background para não bloquear)
        def _varredura_background():
            try:
                self._emitir("debug_log", {"message": "Executando varredura preditiva de estoque inicial..."})
                self.inventory_assistant.verificar_itens_expirados_inicializacao()
                self._emitir("debug_log", {"message": "✓ Varredura inicial de estoque concluída."})
            except Exception as e:
                logger.error(f"Erro na varredura inicial de estoque: {e}")
                self._emitir("debug_log", {"message": f"⚠️ Erro na varredura de estoque: {e}"})

        t_varredura = threading.Thread(target=_varredura_background, daemon=True)
        t_varredura.start()

        # Avisa logo no início se o Ollama estiver fechado (M17), sem atrasar o chat
        def _verificar_ollama_inicio():
            erro = llm_provider_estado.verificar_ollama()
            if erro:
                self._emitir("debug_log", {"message": "⚠️ Ollama não respondeu. Abra o Ollama antes de conversar com a IA local."})
            else:
                self._emitir("debug_log", {"message": "✓ Ollama em execução."})

        threading.Thread(target=_verificar_ollama_inicio, daemon=True).start()

        # Cópia de segurança do dia (M11), em segundo plano: o chat não espera por ela
        self._iniciar_backup_diario()

        # Fila de análise das ideias e bot do Telegram, em segundo plano
        self._iniciar_ideias_e_telegram()

        # Pasta de entrada de notas fiscais (HTML da NFC-e, PDF, foto)
        self._iniciar_pasta_entradas()

        # =====================================================================
        # SISTEMA PRONTO PARA TEXTO — Chat desbloqueado!
        # =====================================================================
        self._set_estado("READY")
        self._emitir("system_ready")
        import core.config as config_app
        if config_app.DEMO:
            self._emitir("assistant_message", {"text": "🎬 **Modo demonstração**: os dados são fictícios e ficam separados dos reais. "
                                                        "O bot do Telegram fica desligado."})
        if getattr(self, "_aviso_retomada", False):
            trocas = sum(1 for m in self.sessao.historico if m["role"] == "user" and not m["content"].startswith("Resumo da conversa"))
            self._emitir("assistant_message", {"text": f"Continuei a conversa anterior ({trocas} troca(s) recentes na memória). "
                                                          "Diga \"nova conversa\" para começar do zero."})
        self._set_estado("WAITING_INPUT")

        logger.info("🟢 Assistente pronto no MODO TEXTO. Chat desbloqueado para o usuário.")
        self._emitir("debug_log", {"message": "Sistema pronto! Modo texto ativo. Digite suas mensagens."})

        # =====================================================================
        # EVENT LOOP PRINCIPAL
        # =====================================================================
        while not self.deve_encerrar:
            try:
                cmd = self.fila.get(timeout=1.0)
            except queue.Empty:
                continue

            tipo = cmd.get("type")
            payload = cmd.get("payload", {})

            logger.info(f"Comando recebido: {cmd}")

            # -----------------------------------------------------------------
            # SHUTDOWN
            # -----------------------------------------------------------------
            if tipo == "shutdown":
                logger.info("Comando de shutdown recebido do Electron. Encerrando...")
                self.deve_encerrar = True
                break

            # -----------------------------------------------------------------
            # TEXTO DO CHAT
            # -----------------------------------------------------------------
            elif tipo in ["send_text", "user_message", "text"]:
                text = payload.get("text", "").strip()
                if not text:
                    continue

                # Comandos manuais de saída
                if text.lower() in ["sair", "exit", "quit"]:
                    logger.info("Encerrando o Assistente Doméstico...")
                    self.deve_encerrar = True
                    break

                # Aborta captura de áudio se houver uma em andamento
                if self.audio_service:
                    self.audio_service.abortar_captura()

                # Echo para todas as telas conectadas (PC, celular), com o canal de origem
                canal = payload.get("canal") or "chat"
                self._emitir("user_message", {"text": text, "canal": canal})

                try:
                    self._processar_solicitacao(text, canal=canal)
                except TokenExhaustedException as e:
                    logger.warning(f"AVISO DE TOKENS: {e}")
                    self._falar_se_permitido("Limite de cota atingido para processamento na nuvem.")
                    self._emitir("error", {"message": f"Limite de cota atingido: {e}"})
                except Exception as e:
                    logger.error(f"Falha ao processar solicitação: {e}")
                    self._emitir("error", {"message": f"Falha ao processar solicitação: {e}"})
                finally:
                    self._set_estado("WAITING_INPUT")

            # -----------------------------------------------------------------
            # INPUT DE VOZ (vindo da thread do microfone)
            # -----------------------------------------------------------------
            elif tipo == "documento":
                self._importar_documento(payload.get("caminho", ""), payload.get("canal", "pasta"),
                                         bool(payload.get("aguardando")))

            elif tipo == "voice_input":
                text = payload.get("text", "").strip()
                if not text:
                    continue

                # Echo para a UI (transcrição de voz)
                self._emitir("user_message", {"text": text})

                if self.audio_service:
                    self.audio_service.abortar_captura()

                try:
                    self._processar_solicitacao(text, canal="voz")
                except TokenExhaustedException as e:
                    logger.warning(f"AVISO DE TOKENS: {e}")
                    self._falar_se_permitido("Limite de cota atingido para processamento na nuvem.")
                except Exception as e:
                    logger.error(f"Falha ao processar solicitação por voz: {e}")
                    self._emitir("error", {"message": f"Falha ao processar: {e}"})
                finally:
                    self._set_estado("WAITING_INPUT")

            # -----------------------------------------------------------------
            # TOGGLE MODO VOZ (ativação/desativação dinâmica)
            # -----------------------------------------------------------------
            elif tipo == "toggle_voice_mode":
                enabled = payload.get("enabled", False)

                if enabled:
                    status = self._ativar_modo_voz()
                else:
                    status = self._desativar_modo_voz()

                self._emitir("voice_mode_status", status)

            # -----------------------------------------------------------------
            # TOGGLE MUTE (apenas controla TTS, não afeta microfone)
            # -----------------------------------------------------------------
            elif tipo == "toggle_mute":
                self.is_muted = payload.get("muted", not self.is_muted)
                logger.info(f"🔊 Estado do Áudio alterado: Mudo = {self.is_muted}")
                self._emitir("debug_log", {
                    "message": f"{'🔇 Áudio silenciado.' if self.is_muted else '🔊 Áudio ativado.'}"
                })

            # -----------------------------------------------------------------
            # COMPATIBILIDADE: toggle_microphone antigo → redireciona
            # -----------------------------------------------------------------
            elif tipo == "toggle_microphone":
                enabled = payload.get("enabled", False)
                logger.info(f"toggle_microphone recebido (compatibilidade) → redirecionando para toggle_voice_mode")
                self.fila.put({"type": "toggle_voice_mode", "payload": {"enabled": enabled}})

            else:
                logger.warning(f"Comando desconhecido recebido: {tipo}")

        # =====================================================================
        # SHUTDOWN GRACEFUL
        # =====================================================================
        logger.info("Iniciando shutdown graceful...")
        self._set_estado("STOPPING")

        if self.audio_service:
            self.audio_service.abortar_captura()
        if self.voice_service:
            self.voice_service.encerrar()

        AudioService.remover_callbacks()
        VoiceService.remover_callbacks()

        logger.info("Runtime finalizado com sucesso.")
