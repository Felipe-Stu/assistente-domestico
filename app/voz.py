"""
Modo voz do runtime: ativar e desativar o hardware e o laço do microfone.
Usado como classe base de AssistenteRuntime; os atributos (voice_service, audio_service,
voice_mode_active, estado, fila, deve_encerrar) são do runtime.
"""
import logging
import time

from app.ipc import emitir_electron

logger = logging.getLogger(__name__)


class ModoVoz:
    def _ativar_modo_voz(self):
        """
        Tenta inicializar VoiceService (TTS) e AudioService (Microfone).
        Retorna dict com status detalhado para o frontend.
        Nunca lança exceção.
        """
        emitir_electron("debug_log", {"message": "Ativando modo voz... Verificando hardware..."})

        tts_ready = False
        mic_ready = False
        erro = None

        # TTS (Síntese de Voz)
        if self.voice_service:
            tts_ready = self.voice_service.inicializar()
            if not tts_ready:
                erro = self.voice_service.obter_erro()
                emitir_electron("debug_log", {"message": f"⚠️ TTS indisponível: {erro}"})
            else:
                emitir_electron("debug_log", {"message": "✓ TTS (síntese de voz) ativado."})

        # Microfone (Captura de Áudio)
        if self.audio_service:
            mic_ready = self.audio_service.inicializar()
            if not mic_ready:
                mic_erro = self.audio_service.obter_erro()
                if not erro:
                    erro = mic_erro
                else:
                    erro += f" | {mic_erro}"
                emitir_electron("debug_log", {"message": f"⚠️ Microfone indisponível: {mic_erro}"})
            else:
                emitir_electron("debug_log", {"message": "✓ Microfone detectado e pronto."})

        available = tts_ready or mic_ready
        self.voice_mode_active = available

        status = {
            "available": available,
            "tts_ready": tts_ready,
            "mic_ready": mic_ready,
            "error": erro
        }

        if available:
            emitir_electron("debug_log", {"message": "Modo voz ativado com sucesso."})
        else:
            emitir_electron("debug_log", {"message": "Modo voz indisponível — nenhum hardware detectado."})

        return status

    def _desativar_modo_voz(self):
        """Desativa o modo voz e aborta capturas em andamento."""
        self.voice_mode_active = False

        if self.audio_service:
            self.audio_service.abortar_captura()

        emitir_electron("debug_log", {"message": "Modo voz desativado."})

        return {
            "available": False,
            "tts_ready": self.voice_service.esta_disponivel() if self.voice_service else False,
            "mic_ready": self.audio_service.esta_disponivel() if self.audio_service else False,
            "error": None
        }

    def _loop_microfone(self):
        """Thread daemon para captação contínua do microfone físico."""
        while not self.deve_encerrar:
            if (self.voice_mode_active 
                and self.audio_service 
                and self.audio_service.esta_disponivel() 
                and self.estado == "WAITING_INPUT"):
                
                emitir_electron("voice_mode_status", {
                    "available": True,
                    "tts_ready": self.voice_service.esta_disponivel() if self.voice_service else False,
                    "mic_ready": True,
                    "listening": True,
                    "error": None
                })
                
                try:
                    transcricao = self.audio_service.capturar_audio_e_transcrever(ativar_trava_inicial=True)
                    if transcricao and transcricao.strip():
                        if self.voice_mode_active and self.estado == "WAITING_INPUT":
                            self.fila.put({"type": "voice_input", "payload": {"text": transcricao}})
                except Exception as e:
                    logger.error(f"Erro no loop do microfone: {e}")
                    # Se o mic foi desconectado em runtime, atualiza estado
                    if self.audio_service and not self.audio_service.esta_disponivel():
                        self.voice_mode_active = False
                        emitir_electron("voice_mode_status", {
                            "available": False,
                            "tts_ready": self.voice_service.esta_disponivel() if self.voice_service else False,
                            "mic_ready": False,
                            "listening": False,
                            "error": "Microfone desconectado durante uso."
                        })
                        emitir_electron("debug_log", {"message": "⚠️ Microfone desconectado. Voltando ao modo texto."})
                    time.sleep(1)
                finally:
                    emitir_electron("voice_mode_status", {
                        "available": self.voice_mode_active,
                        "tts_ready": self.voice_service.esta_disponivel() if self.voice_service else False,
                        "mic_ready": self.audio_service.esta_disponivel() if self.audio_service else False,
                        "listening": False,
                        "error": None
                    })
            else:
                time.sleep(0.3)
