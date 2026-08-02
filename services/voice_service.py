import logging
import os
import asyncio
import pygame
from services.logger_service import logger as custom_logger

# Logger do console (terminal)
logger = logging.getLogger(__name__)

# Identificador do serviço para o logger estruturado em arquivo
NOME_ASSISTENTE = "voice_service"

class VoiceService:
    def __init__(self):
        # Inicializa o mixer de áudio do pygame para tocar o som gerado
        pygame.mixer.init()
        # Definimos uma voz neural masculina em português excelente
        self.voice = "pt-BR-AntonioNeural" 
        self.output_file = "assets/temp_voice.mp3"
        
        # Garante que a pasta assets exista
        os.makedirs("assets", exist_ok=True)
        
        custom_logger.log_assistente(
            NOME_ASSISTENTE, 
            f"Inicialização do VoiceService (Voz: {self.voice}, Arquivo temporário: {self.output_file})."
        )

    def falar(self, texto: str):
        """Método síncrono para ser chamado facilmente no main.py"""
        msg_fala = f"🤖 [Assistente Falando]: '{texto}'"
        logger.info(msg_fala)
        custom_logger.log_assistente(NOME_ASSISTENTE, msg_fala)
        
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
            pygame.mixer.music.load(self.output_file)
            pygame.mixer.music.play()
            
            # Aguarda o áudio terminar de tocar para não cortar a fala
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.1)
                
            pygame.mixer.music.unload()
            custom_logger.log_assistente(NOME_ASSISTENTE, "Reprodução de áudio concluída.")
            
            # Remove o arquivo temporário para não entulhar o PC
            if os.path.exists(self.output_file):
                os.remove(self.output_file)
                custom_logger.log_assistente(NOME_ASSISTENTE, f"Arquivo temporário '{self.output_file}' removido com sucesso.")
                
        except Exception as e:
            msg_erro = f"Falha ao gerar ou reproduzir voz neural: {e}"
            logger.error(msg_erro)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_erro)