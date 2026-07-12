import logging
import time
import winsound
import math
import struct
from core.config import RECORD_SECONDS

logger = logging.getLogger(__name__)

class AudioService:
    def __init__(self):
        pass

    def emitir_bip_inicial(self):
        try:
            winsound.Beep(800, 300)
        except Exception as e:
            logger.debug(f"Erro ao emitir bip: {e}")

    def emitir_bip_aviso_10s(self):
        try:
            winsound.Beep(600, 150)
            time.sleep(0.05)
            winsound.Beep(600, 150)
        except Exception as e:
            logger.debug(f"Erro ao emitir bip: {e}")

    def emitir_bip_final(self) -> None:
        try:
            winsound.Beep(440, 600)
        except Exception as e:
            logger.debug(f"Erro ao emitir bip: {e}")

    def capturar_audio_e_transcrever(self, tempo_limite: int = 120, ativar_trava_inicial: bool = True) -> str:
        """
        Captura o áudio do microfone gerenciando o tempo máximo global e pausas de inatividade.
        - tempo_limite: 120 segundos por padrão.
        - activar_trava_inicial: Se True, cancela caso o usuário não fale nada em 15s.
        """
        logger.info("Preparando para escutar o comando de voz...")
        
        try:
            import speech_recognition as sr
            
            recognizer = sr.Recognizer()
            recognizer.dynamic_energy_threshold = True
            recognizer.dynamic_energy_adjustment_damping = 0.15
            recognizer.dynamic_energy_ratio = 1.5
            
            microphone = sr.Microphone()
            with microphone as source:
                logger.info("Calibrando ruído de fundo... (Aguarde 2 segundos)")
                recognizer.adjust_for_ambient_noise(source, duration=2)
                
                logger.info("Microfone ligado! Diga seu comando...")
                self.emitir_bip_inicial()
                
                frames_audio = []
                aviso_10s_feito = False
                inicio_silencio = None
                usuario_comecou_a_falar = False
                
                # Definindo uma margem segura baseada no ruído real calibrado
                limiar_energia = recognizer.energy_threshold * 1.3
                
                audio_stream = microphone.stream
                inicio_gravacao = time.time()
                
                while True:
                    tempo_decorrido = time.time() - inicio_gravacao
                    
                    try:
                        buffer_chunk = audio_stream.read(microphone.CHUNK)
                        if buffer_chunk:
                            frames_audio.append(buffer_chunk)
                            
                            # Cálculo preciso de volume (RMS) para evitar que estática impeça o corte
                            count = len(buffer_chunk) / 2
                            format_string = f"<{int(count)}h"
                            shorts = struct.unpack(format_string, buffer_chunk)
                            
                            soma_quadrados = sum(sample ** 2 for sample in shorts)
                            volume_atual = math.sqrt(soma_quadrados / count) if count > 0 else 0
                            
                            if volume_atual > limiar_energia:
                                if not usuario_comecou_a_falar:
                                    logger.info("🎙️ Fala detectada! Iniciando monitoramento de pausas.")
                                    usuario_comecou_a_falar = True
                                inicio_silencio = None  
                            else:
                                if usuario_comecou_a_falar:
                                    if inicio_silencio is None:
                                        inicio_silencio = time.time()
                                    
                                    segundos_em_silencio = time.time() - inicio_silencio
                                    
                                    # Corte cirúrgico após 5 segundos cravados de silêncio real
                                    if segundos_em_silencio >= 5.0:
                                        logger.info("🤫 5 segundos de inatividade detectados após a fala. Encerrando por conclusão.")
                                        break
                    except IOError:
                        pass

                    # Trava de segurança inicial se você esquecer o microfone aberto
                    if ativar_trava_inicial and not usuario_comecou_a_falar and tempo_decorrido >= 15.0:
                        logger.info("🛑 Nenhum comando foi dito nos primeiros 15 segundos. Cancelando.")
                        break

                    # Alerta sonoro de fim de tempo próximo aos 2 minutos
                    if tempo_decorrido >= (tempo_limite - 10) and not aviso_10s_feito:
                        logger.info("⏳ Faltam 10 segundos para encerrar o tempo limite global de 2 minutos!")
                        self.emitir_bip_aviso_10s()
                        aviso_10s_feito = True

                    # Limite de segurança global
                    if tempo_decorrido >= tempo_limite:
                        logger.info(f"⏱️ Tempo limite global de {tempo_limite} segundos atingido. Encerrando.")
                        break
                
                self.emitir_bip_final()
                
                audio_data_bruto = b"".join(frames_audio)
                audio_objeto = sr.AudioData(audio_data_bruto, microphone.SAMPLE_RATE, microphone.SAMPLE_WIDTH)
                
                logger.info("Processando áudio para transcrição...")
                texto_transcrito = recognizer.recognize_google(audio_objeto, language="pt-BR")
                logger.info("Áudio transcrito com sucesso: '%s'", texto_transcrito)
                return texto_transcrito
                
        except sr.UnknownValueError:
            logger.warning("Google Speech Recognition não entendeu o áudio.")
            return ""
        except Exception as e:
            logger.error("Falha ao acessar o microfone ou transcrever: %s", e)
            return self._obter_comando_simulado()

    def _obter_comando_simulado(self) -> str:
        return "Anotar que gastei no restaurante costela de chão o valor de 150 reais em um almoço de família na categoria passeios"