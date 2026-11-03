import logging
import os
from services.logger_service import logger as custom_logger

# Logger do console (terminal)
logger = logging.getLogger(__name__)

# Identificador do serviço para o logger estruturado em arquivo
NOME_ASSISTENTE = "voice_service"


class VoiceService:
    # Atributos de classe para integração com o runtime
    callbacks_fala = []

    @classmethod
    def registrar_callback_fala(cls, cb):
        cls.callbacks_fala.append(cb)

    @classmethod
    def remover_callbacks(cls):
        cls.callbacks_fala.clear()

    def __init__(self):
        """Construtor leve — NÃO inicializa pygame nem dependências pesadas."""
        self._inicializado = False
        self._erro_inicializacao = None
        self.voice = "pt-BR-AntonioNeural"
        self.output_file = "assets/temp_voice.mp3"

        # Garante que a pasta assets exista
        os.makedirs("assets", exist_ok=True)

        custom_logger.log_assistente(
            NOME_ASSISTENTE,
            f"VoiceService instanciado (lazy). Voz: {self.voice}. Aguardando inicializar()."
        )

    def inicializar(self) -> bool:
        """
        Inicializa o mixer do pygame e marca o serviço como disponível.
        Retorna True se bem-sucedido, False se falhar.
        Nunca lança exceção — falhas são logadas e armazenadas.
        """
        if self._inicializado:
            return True

        try:
            import pygame
            pygame.mixer.init()
            self._pygame = pygame
            self._inicializado = True
            self._erro_inicializacao = None

            custom_logger.log_assistente(
                NOME_ASSISTENTE,
                "pygame.mixer inicializado com sucesso. TTS disponível."
            )
            logger.info("🔊 VoiceService inicializado com sucesso (TTS pronto).")
            return True

        except Exception as e:
            self._inicializado = False
            self._erro_inicializacao = str(e)
            logger.warning(f"⚠️ VoiceService não pôde ser inicializado: {e}")
            custom_logger.log_assistente(
                NOME_ASSISTENTE,
                f"Falha ao inicializar pygame.mixer: {e}. TTS indisponível."
            )
            return False

    def esta_disponivel(self) -> bool:
        """Retorna True se o serviço de voz está pronto para uso."""
        return self._inicializado

    def obter_erro(self) -> str:
        """Retorna a mensagem de erro da última tentativa de inicialização, ou None."""
        return self._erro_inicializacao

    def falar(self, texto: str):
        """
        Método síncrono para síntese de voz.
        Retorna silenciosamente se o serviço não estiver inicializado.
        """
        if not self._inicializado:
            logger.debug("VoiceService.falar() ignorado — serviço não inicializado.")
            return

        for cb in self.callbacks_fala:
            try:
                cb(texto)
            except Exception as e:
                logger.error(f"Erro no callback de fala: {e}")

        msg_fala = f"🤖 [Assistente Falando]: '{texto}'"
        logger.info(msg_fala)
        custom_logger.log_assistente(NOME_ASSISTENTE, msg_fala)

        import asyncio
        asyncio.run(self._gerar_e_tocar(texto))

    async def _gerar_e_tocar(self, texto: str):
        import edge_tts
        try:
            custom_logger.log_assistente(NOME_ASSISTENTE, "Sintetizando áudio neural com edge_tts...")

            # Gera o áudio neural baseado no texto
            communicate = edge_tts.Communicate(texto, self.voice)
            await communicate.save(self.output_file)

            custom_logger.log_assistente(NOME_ASSISTENTE, "Arquivo de áudio gerado. Iniciando reprodução com pygame...")

            # Toca o áudio gerado
            self._pygame.mixer.music.load(self.output_file)
            self._pygame.mixer.music.play()

            # Aguarda o áudio terminar de tocar para não cortar a fala
            import asyncio
            while self._pygame.mixer.music.get_busy():
                await asyncio.sleep(0.1)

            self._pygame.mixer.music.unload()
            custom_logger.log_assistente(NOME_ASSISTENTE, "Reprodução de áudio concluída.")

            # Remove o arquivo temporário para não entulhar o PC
            if os.path.exists(self.output_file):
                os.remove(self.output_file)
                custom_logger.log_assistente(NOME_ASSISTENTE, f"Arquivo temporário '{self.output_file}' removido com sucesso.")

        except Exception as e:
            msg_erro = f"Falha ao gerar ou reproduzir voz neural: {e}"
            logger.error(msg_erro)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_erro)

    def encerrar(self):
        """Encerra o mixer do pygame e libera recursos."""
        if self._inicializado:
            try:
                self._pygame.mixer.quit()
                logger.info("VoiceService encerrado (pygame.mixer liberado).")
            except Exception as e:
                logger.debug(f"Erro ao encerrar pygame.mixer: {e}")
            finally:
                self._inicializado = False