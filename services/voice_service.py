import logging
import os
import asyncio
import pygame

logger = logging.getLogger(__name__)

class VoiceService:
    def __init__(self):
        # Inicializa o mixer de áudio do pygame para tocar o som gerado
        pygame.mixer.init()
        # Definimos uma voz neural masculina em português excelente
        self.voice = "pt-BR-AntonioNeural" 
        self.output_file = "assets/temp_voice.mp3"
        
        # Garante que a pasta assets exista
        os.makedirs("assets", exist_ok=True)

    def falar(self, texto: str):
        """Método síncrono para ser chamado facilmente no main.py"""
        logger.info(f"🤖 [Assistente Falando]: '{texto}'")
        asyncio.run(self._gerar_e_tocar(texto))

    async def _gerar_e_tocar(self, texto: str):
        import edge_tts
        try:
            # Gera o áudio neural baseado no texto
            communicate = edge_tts.Communicate(texto, self.voice)
            await communicate.save(self.output_file)
            
            # Toca o áudio gerado
            pygame.mixer.music.load(self.output_file)
            pygame.mixer.music.play()
            
            # Aguarda o áudio terminar de tocar para não cortar a fala
            while pygame.mixer.music.get_busy():
                await asyncio.sleep(0.1)
                
            pygame.mixer.music.unload()
            
            # Remove o arquivo temporário para não entulhar o PC
            if os.path.exists(self.output_file):
                os.remove(self.output_file)
                
        except Exception as e:
            logger.error(f"Falha ao gerar ou reproduzir voz neural: {e}")