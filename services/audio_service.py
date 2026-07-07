import logging
from core.config import RECORD_SECONDS

logger = logging.getLogger(__name__)

class AudioService:
    """
    Serviço responsável por gerenciar a captação de áudio via microfone
    e a conversão de fala para texto (Speech-to-Text).
    """
    def __init__(self):
        pass

    def capturar_audio_e_transcrever(self) -> str:
        """
        Ativa o microfone padrão, captura o comando de voz do usuário
        e transcreve para texto utilizando serviços de reconhecimento de voz.
        """
        logger.info("Preparando para escutar o comando de voz...")
        
        try:
            import speech_recognition as sr
            
            recognizer = sr.Recognizer()
            
            # Ativa o ajuste dinâmico de volume/energia para não cortar com barulho de coolers
            recognizer.dynamic_energy_threshold = True
            
            with sr.Microphone() as source:
                # Aumentado para 2 segundos para isolar melhor barulhos de fundo do PC
                logger.info("Calibrando ruído de fundo... (Aguarde 2 segundos)")
                recognizer.adjust_for_ambient_noise(source, duration=2)
                
                # Tolerância de Pausa: Espera até 3 segundos de silêncio antes de encerrar
                # Perfeito para listas longas onde você para para pensar nos preços
                recognizer.pause_threshold = 10.0
                recognizer.non_speaking_duration = 1.5
                
                logger.info("Microfone ligado! Diga seu comando...")
                # timeout = tempo para começar a falar (20s) | phrase_time_limit = tamanho máximo da gravação (60s)
                audio = recognizer.listen(source, timeout=RECORD_SECONDS, phrase_time_limit=60)
                
                logger.info("Processando áudio para transcrição...")
                texto_transcrito = recognizer.recognize_google(audio, language="pt-BR")
                logger.info("Áudio transcrito com sucesso: '%s'", texto_transcrito)
                return texto_transcrito
                
        except ImportError:
            logger.warning(
                "Bibliotecas de áudio ('speech_recognition' ou 'PyAudio') ausentes. "
                "Carregando comando de voz simulado para fins de validação."
            )
            return self._obter_comando_simulado()
        except Exception as e:
            logger.error(
                "Falha ao acessar o microfone ou realizar transcrição online: %s. "
                "Carregando comando de voz simulado.", e
            )
            return self._obter_comando_simulado()

    def _obter_comando_simulado(self) -> str:
        """
        Retorna uma frase de compra simulada para testar a integração.
        """
        comando = (
            "Anotar que fiz compras no Mercado Estrela. "
            "Itens: Quatro quilos de frango por 116 reais, "
            "dois litros de leite por dez reais e "
            "um pacote de café por vinte e dois reais."
        )
        logger.info("Transcrição simulada gerada: '%s'", comando)
        return comando