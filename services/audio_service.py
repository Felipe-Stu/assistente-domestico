import logging
import time
import math
import struct
from services.logger_service import logger as custom_logger

# Logger do console (terminal)
logging_logger = logging.getLogger(__name__)

NOME_ASSISTENTE = "audio_service"


class AudioService:
    # Atributos de classe para integração com o runtime
    callbacks_transcricao = []
    instancia_ativa = None

    @classmethod
    def registrar_callback_transcricao(cls, cb):
        cls.callbacks_transcricao.append(cb)

    @classmethod
    def remover_callbacks(cls):
        cls.callbacks_transcricao.clear()

    def _notificar_transcricao(self, texto: str):
        if texto:
            for cb in self.callbacks_transcricao:
                try:
                    cb(texto)
                except Exception as e:
                    logging_logger.error(f"Erro no callback de transcricao: {e}")

    def __init__(self):
        """Construtor leve — NÃO inicializa microfone nem dependências de áudio."""
        AudioService.instancia_ativa = self
        self.input_externo = None
        self.deve_abortar = False
        self._mic_disponivel = False
        self._erro_inicializacao = None
        custom_logger.log_assistente(NOME_ASSISTENTE, "AudioService instanciado (lazy). Aguardando inicializar().")

    def inicializar(self) -> bool:
        """
        Verifica se há microfone disponível no sistema.
        Retorna True se um microfone foi detectado, False caso contrário.
        Nunca lança exceção.
        """
        try:
            import speech_recognition as sr
            # Tenta listar microfones disponíveis
            mic_list = sr.Microphone.list_microphone_names()
            if not mic_list:
                self._mic_disponivel = False
                self._erro_inicializacao = "Nenhum microfone detectado no sistema."
                logging_logger.warning(f"⚠️ {self._erro_inicializacao}")
                custom_logger.log_assistente(NOME_ASSISTENTE, self._erro_inicializacao)
                return False

            # Tenta criar uma instância de microfone para validar acesso real
            mic_teste = sr.Microphone()
            self._mic_disponivel = True
            self._erro_inicializacao = None
            logging_logger.info(f"🎙️ Microfone detectado. {len(mic_list)} dispositivo(s) disponível(is).")
            custom_logger.log_assistente(
                NOME_ASSISTENTE,
                f"Microfone inicializado com sucesso. Dispositivos: {mic_list[:3]}"
            )
            return True

        except OSError as e:
            self._mic_disponivel = False
            self._erro_inicializacao = f"Erro de acesso ao hardware de áudio: {e}"
            logging_logger.warning(f"⚠️ {self._erro_inicializacao}")
            custom_logger.log_assistente(NOME_ASSISTENTE, self._erro_inicializacao)
            return False
        except Exception as e:
            self._mic_disponivel = False
            self._erro_inicializacao = f"Erro inesperado ao detectar microfone: {e}"
            logging_logger.warning(f"⚠️ {self._erro_inicializacao}")
            custom_logger.log_assistente(NOME_ASSISTENTE, self._erro_inicializacao)
            return False

    def esta_disponivel(self) -> bool:
        """Retorna True se o microfone está disponível para captura."""
        return self._mic_disponivel

    def obter_erro(self) -> str:
        """Retorna a mensagem de erro da última tentativa de inicialização, ou None."""
        return self._erro_inicializacao

    def abortar_captura(self):
        self.deve_abortar = True

    @staticmethod
    def _bip(frequencia: int, duracao_ms: int) -> None:
        """Bipe pelo winsound no Windows; nos outros sistemas, silêncio (M27: nada preso ao Windows).

        O stdout é o canal com o Electron, então não se escreve o caractere de campainha nele.
        """
        try:
            import winsound
        except ImportError:
            logging_logger.debug("Bipe ignorado: winsound só existe no Windows.")
            return
        try:
            winsound.Beep(frequencia, duracao_ms)
        except Exception as e:
            logging_logger.debug(f"Erro ao emitir bip (sem hardware de áudio): {e}")

    def emitir_bip_inicial(self):
        self._bip(800, 300)

    def emitir_bip_aviso_10s(self):
        self._bip(600, 150)
        time.sleep(0.05)
        self._bip(600, 150)

    def emitir_bip_final(self) -> None:
        self._bip(440, 600)

    def capturar_audio_e_transcrever(self, tempo_limite: int = 120, ativar_trava_inicial: bool = True) -> str:
        """
        Captura o áudio do microfone gerenciando o tempo máximo global e pausas de inatividade.
        - tempo_limite: 120 segundos por padrão.
        - ativar_trava_inicial: Se True, cancela caso o usuário não fale nada em 15s.
        
        Retorna string vazia se o microfone não estiver disponível.
        """
        if not self._mic_disponivel:
            logging_logger.warning("Tentativa de captura sem microfone disponível. Ignorando.")
            return ""

        self.deve_abortar = False
        msg_inicio = "Preparando para escutar o comando de voz..."
        logging_logger.info(msg_inicio)
        custom_logger.log_assistente(NOME_ASSISTENTE, msg_inicio)

        try:
            import speech_recognition as sr

            recognizer = sr.Recognizer()
            recognizer.dynamic_energy_threshold = True
            recognizer.dynamic_energy_adjustment_damping = 0.15
            recognizer.dynamic_energy_ratio = 1.5

            microphone = sr.Microphone()
            with microphone as source:
                msg_ruido = "Calibrando ruído de fundo... (Aguarde 2 segundos)"
                logging_logger.info(msg_ruido)
                custom_logger.log_assistente(NOME_ASSISTENTE, msg_ruido)
                recognizer.adjust_for_ambient_noise(source, duration=2)

                msg_pronto = "Microfone ligado! Diga seu comando..."
                logging_logger.info(msg_pronto)
                custom_logger.log_assistente(NOME_ASSISTENTE, msg_pronto)
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
                    if self.deve_abortar:
                        logging_logger.info("Captura de áudio abortada por solicitação externa.")
                        break
                    if self.input_externo is not None:
                        texto_recebido = self.input_externo
                        self.input_externo = None
                        logging_logger.info(f"Captura de áudio interrompida por entrada de texto externo: '{texto_recebido}'")
                        self._notificar_transcricao(texto_recebido)
                        return texto_recebido

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
                                    msg_fala = "🎙️ Fala detectada! Iniciando monitoramento de pausas."
                                    logging_logger.info(msg_fala)
                                    custom_logger.log_assistente(NOME_ASSISTENTE, msg_fala)
                                    usuario_comecou_a_falar = True
                                inicio_silencio = None
                            else:
                                if usuario_comecou_a_falar:
                                    if inicio_silencio is None:
                                        inicio_silencio = time.time()

                                    segundos_em_silencio = time.time() - inicio_silencio

                                    # Corte cirúrgico após 5 segundos cravados de silêncio real
                                    if segundos_em_silencio >= 5.0:
                                        msg_corte = "🤫 5 segundos de inatividade detectados após a fala. Encerrando por conclusão."
                                        logging_logger.info(msg_corte)
                                        custom_logger.log_assistente(NOME_ASSISTENTE, msg_corte)
                                        break
                    except IOError:
                        pass

                    # Trava de segurança inicial se você esquecer o microfone aberto
                    if ativar_trava_inicial and not usuario_comecou_a_falar and tempo_decorrido >= 15.0:
                        msg_trava = "🛑 Nenhum comando foi dito nos primeiros 15 segundos. Cancelando."
                        logging_logger.info(msg_trava)
                        custom_logger.log_assistente(NOME_ASSISTENTE, msg_trava)
                        break

                    # Alerta sonoro de fim de tempo próximo aos 2 minutos
                    if tempo_decorrido >= (tempo_limite - 10) and not aviso_10s_feito:
                        msg_alerta = "⏳ Faltam 10 segundos para encerrar o tempo limite global de 2 minutos!"
                        logging_logger.info(msg_alerta)
                        custom_logger.log_assistente(NOME_ASSISTENTE, msg_alerta)
                        self.emitir_bip_aviso_10s()
                        aviso_10s_feito = True

                    # Limite de segurança global
                    if tempo_decorrido >= tempo_limite:
                        msg_limite = f"⏱️ Tempo limite global de {tempo_limite} segundos atingido. Encerrando."
                        logging_logger.info(msg_limite)
                        custom_logger.log_assistente(NOME_ASSISTENTE, msg_limite)
                        break

                self.emitir_bip_final()

                audio_data_bruto = b"".join(frames_audio)
                audio_objeto = sr.AudioData(audio_data_bruto, microphone.SAMPLE_RATE, microphone.SAMPLE_WIDTH)

                msg_proc = "Processando áudio para transcrição..."
                logging_logger.info(msg_proc)
                custom_logger.log_assistente(NOME_ASSISTENTE, msg_proc)

                texto_transcrito = recognizer.recognize_google(audio_objeto, language="pt-BR")

                msg_sucesso = f"Áudio transcrito com sucesso: '{texto_transcrito}'"
                logging_logger.info("Áudio transcrito com sucesso: '%s'", texto_transcrito)
                custom_logger.log_assistente(NOME_ASSISTENTE, msg_sucesso)
                self._notificar_transcricao(texto_transcrito)
                return texto_transcrito

        except Exception as e:
            # Se o microfone foi desconectado em runtime, atualiza o estado
            if "No Default Input Device Available" in str(e) or "Invalid input device" in str(e):
                self._mic_disponivel = False
                self._erro_inicializacao = f"Microfone desconectado durante captura: {e}"
                logging_logger.warning(f"⚠️ {self._erro_inicializacao}")
            else:
                msg_erro_geral = f"Falha ao acessar o microfone ou transcrever: {e}"
                logging_logger.error("Falha ao acessar o microfone ou transcrever: %s", e)
                custom_logger.log_assistente(NOME_ASSISTENTE, msg_erro_geral)
            return ""