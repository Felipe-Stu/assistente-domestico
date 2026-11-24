"""
AssistenteRuntime: ciclo de vida, filas e pipeline de cada solicitação
(orquestrador → skill → resposta). IPC em app/ipc.py, sessão em app/sessao.py, modo voz em app/voz.py.
"""
import logging
import json
import queue
import sys
import threading
from pathlib import Path

# 1. sys.path primeiro: os módulos do app vêm da raiz do projeto
ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

# 2. UTF-8 nos fluxos e pipe do Electron isolado, antes de qualquer outra importação (ver app/ipc.py)
from app.ipc import ENTRADA_IPC, emitir_electron  # noqa: E402
from app.sessao import GerenciadorDeSessao  # noqa: E402
from app.voz import ModoVoz  # noqa: E402

# 3. Importações organizadas — apenas serviços essenciais no topo
from services.ai_service import AIService, ServiceUnavailableException, TokenExhaustedException
from services.db_service import DatabaseService
from services.gemma_service import executar_assistente_local, orquestrar_requisicao
from core.skills import Contexto, obter_catalogo
from core.skills import motor as motor_skills
from services.intent_router import pede_nuvem
from services.inventory_assistant import InventoryAssistant
from services.llm_provider import LocalLLMProvider, CloudLLMProvider, MODELO_PADRAO, alternar_modelo_vram
import services.llm_provider as llm_provider_estado
from core.config import (
    BACKUP_ATIVO,
    BACKUP_DIARIOS,
    BACKUP_DIR,
    BACKUP_SEMANAIS,
    CHROMA_DIR,
    CLAUDE_SKILLS,
    DB_PATH,
    PROJECT_ANALYZER_MODEL,
    PROJECT_ANALYZER_OUTPUT_DIR,
)
from services.backup_service import BackupService
from services.biblioteca_service import BibliotecaService
from services.claude_assinatura_service import ClaudeAssinaturaService
from services.claude_service import ClaudeService
from services.documentos_service import DocumentoError, DocumentosService
from services.ideias_service import IdeiasService
from services.pasta_entradas_service import PastaEntradas
from services.telegram_service import TelegramService
import core.config as config_app
from services.project_analyzer import ProjectAnalyzer
from services.logger_service import logger as custom_logger
from services.resilience_service import (
    InvalidOrchestratorOutputException,
    MaxRetriesExceededException,
    OllamaIndisponivelException,
    execute_with_retry,
)
from services.shopping_assistant import ShoppingAssistant

# Serviços Vetoriais e RAG (Memória Semântica e Contextual)
from services.vector.vector_store_service import VectorStoreService
from services.vector.memory_service import MemoryService
from services.vector.context_retrieval_service import ContextRetrievalService
from services.vector.semantic_search_service import SemanticSearchService

# Serviços de voz/áudio — importados mas NÃO instanciados no startup
from services.voice_service import VoiceService
from services.audio_service import AudioService

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

TEMPO_RETRY = config_app.RETRY_ESPERA_S
MAX_TENTATIVAS = config_app.RETRY_TENTATIVAS

MSG_IA_LOCAL_INDISPONIVEL = (
    "A IA local não respondeu. Nada foi gravado nem enviado à nuvem. "
    "Verifique se o Ollama está em execução e tente novamente."
)
MSG_OLLAMA_FORA = (
    "O Ollama não está em execução, então a IA local não pode responder. "
    "Nada foi gravado nem enviado à nuvem. Abra o Ollama e use \"Tentar de novo\"."
)


# =============================================================================
# EMISSÃO IPC PADRONIZADA
# =============================================================================



# =============================================================================
# GERENCIADOR DE SESSÃO
# =============================================================================



# =============================================================================
# RUNTIME PRINCIPAL — TEXT-FIRST COM ATIVAÇÃO DINÂMICA DE VOZ
# =============================================================================

class AssistenteRuntime(ModoVoz):
    """
    Runtime unificado do Assistente Doméstico.
    
    Modelo Text-First:
    - Fase 1: Serviços essenciais (DB, AI, LLM) → chat disponível imediatamente.
    - Fase 2: Serviços de voz (VoiceService, AudioService) → lazy, sob demanda.
    """

    def __init__(self):
        self.estado = "STARTING"
        self.is_muted = False
        self.voice_mode_active = False
        self.deve_encerrar = False
        self.fila = queue.Queue()
        self.sessao = GerenciadorDeSessao()
        # (nome da skill, dados) aguardando confirmação: a próxima mensagem volta para essa skill
        self.pendencia = None

        # Serviços essenciais (inicializados na Fase 1)
        self.db_service = None
        self.ai_service = None
        self.local_llm = None
        self.cloud_llm = None
        self.inventory_assistant = None
        self.shopping_assistant = None
        self.claude_service = None
        self.biblioteca = None
        self.ideias = None
        self.telegram = None
        self.documentos = None
        self.pasta_entradas = None

        # Serviços de voz (inicializados sob demanda na Fase 2)
        self.voice_service = None
        self.audio_service = None

        # Emite estado inicial
        self._set_estado("STARTING")

    # -------------------------------------------------------------------------
    # Estado & Emissão
    # -------------------------------------------------------------------------

    def _set_estado(self, novo_estado: str):
        self.estado = novo_estado
        emitir_electron("state_changed", {"state": self.estado})
        logger.info(f"Estado do sistema alterado para: {self.estado}")

    # -------------------------------------------------------------------------
    # FASE 1: Inicialização Essencial (Text-First)
    # -------------------------------------------------------------------------

    def _inicializar_servicos_essenciais(self):
        """
        Inicializa apenas serviços necessários para o modo texto.
        Falha aqui = erro fatal (sem DB/AI não há funcionalidade).
        """
        self._set_estado("INITIALIZING")
        emitir_electron("debug_log", {"message": "Inicializando serviços essenciais (Modo Texto)..."})

        try:
            # 1. Serviços de Infraestrutura
            self.db_service = DatabaseService()
            emitir_electron("debug_log", {"message": "✓ Banco de dados relacional (SQLite) conectado."})

            self.vector_store = VectorStoreService()
            self.memory_service = MemoryService(vector_store=self.vector_store)
            self.semantic_search = SemanticSearchService(
                vector_store=self.vector_store,
                db_service=self.db_service
            )
            self.context_retrieval = ContextRetrievalService(
                semantic_search_service=self.semantic_search,
                memory_service=self.memory_service
            )
            emitir_electron("debug_log", {"message": "✓ Banco vetorial (ChromaDB) conectado. Carregando a memória semântica em segundo plano..."})
            # O modelo de embeddings leva vários segundos: o chat não espera por ele
            self.vector_store.embedding_service.carregar_em_segundo_plano(ao_concluir=self._avisar_memoria_carregada)

            self.ai_service = AIService()

            # SKP: Claude (assinatura ou API; sem ele, a reserva local responde) e biblioteca de contexto
            self.claude_service = self._criar_claude()
            self.biblioteca = BibliotecaService(
                vector_store=self.vector_store,
                raiz=ROOT_DIR,
                arquivo_indice=config_app.DB_DIR / "biblioteca_indice.json",
                pastas_extras=[config_app.IDEIAS_DIR],
            )
            # Ideias de projetos: salvas na hora, analisadas pelo Claude em segundo plano
            self.ideias = IdeiasService(
                db=self.db_service,
                claude=self.claude_service if "ideias" in CLAUDE_SKILLS else None,
                pasta=config_app.IDEIAS_DIR,
                prompt_analise=lambda: obter_catalogo().skill("ideias").prompt("analise"),
                biblioteca=self.biblioteca,
                intervalo_reteste_s=config_app.IDEIAS_RETESTE_MIN * 60,
            )
            emitir_electron("debug_log", {"message": "✓ Serviço de IA inicializado."})

            # 2. Provedores LLM
            self.local_llm = LocalLLMProvider(modelo=MODELO_PADRAO)
            self.cloud_llm = CloudLLMProvider(ai_service=self.ai_service)
            emitir_electron("debug_log", {"message": "✓ Provedores LLM configurados."})

            # 3. Serviços de voz em modo lazy (construtor leve, sem init de hardware).
            #    Criados antes dos assistentes para serem compartilhados com eles.
            self.voice_service = VoiceService()
            self.audio_service = AudioService()

            # 4. Assistentes de Domínio
            self.inventory_assistant = InventoryAssistant(
                db_service=self.db_service,
                llm_provider=self.local_llm,
                ai_service=self.ai_service,
                voice_service=self.voice_service,
                audio_service=self.audio_service,
                modo_voz_ativo=lambda: self.voice_mode_active
            )

            self.shopping_assistant = ShoppingAssistant(
                ai_service=self.ai_service,
                db_service=self.db_service,
                llm_provider=self.local_llm,
                vector_store=self.vector_store
            )
            # Notas fiscais em HTML, PDF ou foto (pasta de entrada e Telegram)
            self.documentos = DocumentosService(
                db=self.db_service,
                compras=self.shopping_assistant,
                pasta_anexos=config_app.ANEXOS_DIR,
                llm_nomes=LocalLLMProvider(temperatura=0.1),
                llm_visao=LocalLLMProvider(modelo=config_app.OLLAMA_MODELO_VISAO, temperatura=0.1),
                tamanho_max_mb=config_app.ENTRADAS_TAMANHO_MAX_MB,
            )
            emitir_electron("debug_log", {"message": "✓ Assistentes de domínio prontos."})

            # 5. Skill ProjectAnalyzer — 100% local; escreve somente na pasta de saída
            self.project_analyzer = ProjectAnalyzer(
                llm_provider=LocalLLMProvider(modelo=PROJECT_ANALYZER_MODEL, temperatura=0.1),
                pasta_saida=str(PROJECT_ANALYZER_OUTPUT_DIR),
                nome_modelo=PROJECT_ANALYZER_MODEL,
                preparar_modelo=self._preparar_vram_analise,
                liberar_modelo=self._liberar_vram_analise,
                progresso=lambda m: emitir_electron("debug_log", {"message": m})
            )

        except Exception as e:
            logger.critical(f"Erro fatal na inicialização dos serviços essenciais: {e}")
            emitir_electron("error", {"message": f"Erro fatal na inicialização: {e}"})
            self._set_estado("ERROR")
            sys.exit(1)

    @staticmethod
    def _avisar_memoria_carregada(sucesso: bool, erro: str = None):
        """Informa no terminal interno o fim da carga do modelo de embeddings."""
        if sucesso:
            emitir_electron("debug_log", {"message": "✓ Memória semântica pronta."})
        else:
            emitir_electron("debug_log", {"message": f"⚠️ Memória semântica indisponível nesta sessão: {erro}"})

    # -------------------------------------------------------------------------
    # FASE 2: Ativação Dinâmica de Voz (Lazy, sob demanda)
    # -------------------------------------------------------------------------

    # -------------------------------------------------------------------------
    # Falar (resposta por voz) — condicional
    # -------------------------------------------------------------------------

    def _falar_se_permitido(self, texto):
        """Executa TTS apenas se: modo voz ativo + não mutado + voice_service disponível."""
        if self.is_muted:
            return
        if not self.voice_mode_active:
            return
        if self.voice_service and self.voice_service.esta_disponivel():
            try:
                with custom_logger.etapa("voz", caracteres=len(texto or "")):
                    self.voice_service.falar(texto)
            except Exception as e:
                logger.error(f"Erro ao reproduzir áudio: {e}")

    # -------------------------------------------------------------------------
    # Memória Semântica (RAG) — falhas nunca interrompem o pipeline
    # -------------------------------------------------------------------------

    # Contextos que geram JSON estruturado não recebem contexto RAG no prompt
    CONTEXTOS_SEM_RAG = {"compras", "agenda"}
    # Compras já são vetorizadas pelo ShoppingAssistant; consultas de estoque e agenda não são fatos
    CONTEXTOS_SEM_MEMORIA = {"compras", "inventario", "agenda", "projetos", "ideias"}
    # Somente perguntas gerais podem ir ao Gemini; os demais contextos permanecem locais
    CONTEXTOS_NUVEM = {"geral", "outro"}

    def _enriquecer_com_memoria(self, texto: str, contexto: str, para_nuvem: bool = False) -> str:
        """
        Anexa memórias semânticas relevantes à instrução enviada à LLM.
        Para a nuvem, usa apenas memórias de contextos que podem sair da máquina.
        """
        if contexto in self.CONTEXTOS_SEM_RAG:
            return texto
        try:
            assistentes = sorted(self.CONTEXTOS_NUVEM) if para_nuvem else None
            bloco = self.context_retrieval.montar_contexto_recuperado(texto, assistant=assistentes)
        except Exception as e:
            logger.warning(f"Falha ao recuperar contexto semântico (seguindo sem RAG): {e}")
            return texto
        if not bloco:
            return texto
        return f"{bloco}\nSolicitação do usuário: {texto}"

    def _registrar_memoria(self, texto: str, contexto: str):
        """Persiste a fala do usuário na memória de longo prazo (o MemoryService filtra o que é irrelevante)."""
        if contexto in self.CONTEXTOS_SEM_MEMORIA:
            return
        try:
            with custom_logger.etapa("memoria"):
                self.memory_service.salvar_memoria_longo_prazo(
                    conteudo=texto,
                    assistant=contexto,
                    category="conversa",
                    source="user"
                )
        except Exception as e:
            logger.warning(f"Falha ao salvar memória semântica: {e}")

    # -------------------------------------------------------------------------
    # Skill ProjectAnalyzer
    # -------------------------------------------------------------------------

    def _preparar_vram_analise(self):
        """Mesmo mecanismo do modo Qwen: libera o Gemma da VRAM antes de carregar o modelo da análise."""
        if not llm_provider_estado.MODO_QWEN_ATIVO and PROJECT_ANALYZER_MODEL != MODELO_PADRAO:
            alternar_modelo_vram(MODELO_PADRAO)

    def _liberar_vram_analise(self):
        """Libera o modelo da análise; o Gemma volta a ser carregado na próxima solicitação."""
        if not llm_provider_estado.MODO_QWEN_ATIVO and PROJECT_ANALYZER_MODEL != MODELO_PADRAO:
            alternar_modelo_vram(PROJECT_ANALYZER_MODEL)

    # -------------------------------------------------------------------------
    # Compras
    # -------------------------------------------------------------------------

    @property
    def compra_pendente(self):
        """Compras aguardando confirmação (leitura; o estado fica em self.pendencia)."""
        if self.pendencia and self.pendencia[0] == "compras":
            dados = self.pendencia[1]
            return dados["compras"] if isinstance(dados, dict) else dados
        return None

    def _repetir(self, func, args=(), mensagem_espera_voz=None, nome_servico="Skill"):
        """Política de repetição do núcleo, entregue às skills: Ollama fora é fatal, o resto é repetido."""
        return execute_with_retry(
            func=func,
            args=args,
            max_tentativas=MAX_TENTATIVAS,
            tempo_espera=TEMPO_RETRY,
            voice_service=self.voice_service if self.voice_mode_active else None,
            mensagem_espera_voz=mensagem_espera_voz,
            excecoes_fatais=(OllamaIndisponivelException,),
            nome_servico=nome_servico,
        )

    def _criar_claude(self):
        if config_app.CLAUDE_MODO == "api":
            return ClaudeService(
                api_key=config_app.ANTHROPIC_API_KEY,
                modelo=config_app.CLAUDE_MODELO,
                versao_api=config_app.CLAUDE_API_VERSAO,
                arquivo_estado=config_app.CLAUDE_ESTADO_ARQUIVO,
                limite_mensal_usd=config_app.CLAUDE_LIMITE_MENSAL_USD,
                preco_entrada=config_app.CLAUDE_PRECO_ENTRADA,
                preco_saida=config_app.CLAUDE_PRECO_SAIDA,
                hora_reteste=config_app.CLAUDE_HORA_RETESTE,
                max_tokens=config_app.CLAUDE_MAX_TOKENS,
            )
        return ClaudeAssinaturaService(
            comando=config_app.CLAUDE_COMANDO,
            modelo=config_app.CLAUDE_MODELO_ASSINATURA,
            arquivo_estado=config_app.CLAUDE_ESTADO_ASSINATURA_ARQUIVO,
            hora_reteste=config_app.CLAUDE_HORA_RETESTE,
            reteste_minutos=config_app.CLAUDE_ASSINATURA_RETESTE_MIN,
            timeout=config_app.CLAUDE_ASSINATURA_TIMEOUT,
        )

    def _avisar_ideia_analisada(self, ideia):
        emitir_electron("debug_log", {"message": f"💡 Ideia #{ideia['id']} analisada pelo Claude: {ideia['titulo']}."})
        origem = ideia.get("origem") or ""
        if origem.startswith("telegram:") and self.telegram is not None:
            self.telegram.enviar(int(origem.split(":", 1)[1]), f"💡 Análise da ideia #{ideia['id']}\n\n{ideia['analise']}")

    def _iniciar_ideias_e_telegram(self):
        if self.ideias is None:
            return
        self.ideias.iniciar_em_segundo_plano(deve_parar=lambda: self.deve_encerrar, notificar=self._avisar_ideia_analisada)
        telegram = TelegramService(
            token=config_app.TELEGRAM_BOT_TOKEN,
            chats_permitidos=config_app.TELEGRAM_CHAT_IDS,
            arquivo_offset=config_app.TELEGRAM_OFFSET_ARQUIVO,
            ao_receber=lambda chat, texto: self.ideias.responder_mensagem(texto, f"telegram:{chat}"),
            ao_receber_arquivo=self._receber_arquivo_telegram,
        )
        if not telegram.configurado():
            if config_app.TELEGRAM_BOT_TOKEN:
                emitir_electron("debug_log", {"message": "⚠️ Telegram sem TELEGRAM_CHAT_IDS: rode configurar-telegram.bat."})
            return
        self.telegram = telegram
        telegram.iniciar_em_segundo_plano(deve_parar=lambda: self.deve_encerrar)
        emitir_electron("debug_log", {"message": "✓ Bot do Telegram ativo para receber ideias."})

    def _iniciar_pasta_entradas(self):
        if self.documentos is None:
            return
        self.pasta_entradas = PastaEntradas(
            config_app.ENTRADAS_DIR,
            ao_encontrar=lambda caminho, canal: self.fila.put({"type": "documento", "payload": {"caminho": str(caminho), "canal": canal}}),
            intervalo_s=config_app.ENTRADAS_INTERVALO_S,
        )
        self.pasta_entradas.iniciar_em_segundo_plano(deve_parar=lambda: self.deve_encerrar)
        emitir_electron("debug_log", {"message": f"✓ Pasta de notas fiscais vigiada: {config_app.ENTRADAS_DIR}"})

    def _importar_documento(self, caminho: str, canal: str = "pasta"):
        """Nota fiscal encontrada na pasta de entrada: vira compra aguardando "sim" ou "não"."""
        arquivo = Path(caminho)
        if self.pendencia is not None:
            # Já há uma confirmação esperando: a nota volta para a fila daqui a pouco
            threading.Timer(10, lambda: self.fila.put({"type": "documento", "payload": {"caminho": caminho, "canal": canal}})).start()
            return None
        chat = self._chat_do_arquivo(arquivo)
        ok = False
        try:
            with custom_logger.requisicao(canal=canal, caracteres=0):
                preparada = self.documentos.importar(arquivo, canal)
            self.pendencia = ("compras", {"compras": preparada["compras"], "origem": preparada["origem"]})
            texto = (f"📄 Nota fiscal recebida ({arquivo.name}):\n{self.documentos.resumo(preparada)}\n\n"
                     "Responda \"sim\" para gravar ou \"não\" para descartar.")
            ok = True
        except DocumentoError as erro:
            texto = f"Não consegui importar {arquivo.name}: {erro}"
        except Exception as erro:
            logger.error(f"Falha ao importar documento: {erro}")
            texto = f"Não consegui importar {arquivo.name} ({type(erro).__name__})."
        finally:
            if self.pasta_entradas is not None and arquivo.exists():
                self.pasta_entradas.mover(arquivo, ok)
        emitir_electron("assistant_message", {"text": texto})
        if chat is not None and self.telegram is not None:
            aviso = texto.replace('Responda "sim" para gravar ou "não" para descartar.', "Confirme no assistente do PC (sim ou não).")
            self.telegram.enviar(chat, aviso)
        return texto

    @staticmethod
    def _chat_do_arquivo(arquivo: Path):
        partes = arquivo.name.split("_", 2)
        return int(partes[1]) if len(partes) == 3 and partes[0] == "telegram" and partes[1].lstrip("-").isdigit() else None

    def _receber_arquivo_telegram(self, chat: int, mensagem: dict) -> str:
        """Arquivo ou foto mandado ao bot: vai para a pasta de entrada e é importado no PC."""
        documento = mensagem.get("document") or (mensagem.get("photo") or [None])[-1]
        if not documento:
            return "Por enquanto eu entendo texto, arquivos (HTML da nota, PDF) e fotos."
        if (documento.get("file_size") or 0) > 20 * 1024 * 1024:
            return "Arquivo grande demais: o Telegram só deixa o bot baixar até 20 MB."
        nome = documento.get("file_name") or f"foto_{mensagem.get('message_id', 'cupom')}.jpg"
        nome = "".join(c if c.isalnum() or c in "._-" else "_" for c in nome)[-80:]
        destino = config_app.ENTRADAS_DIR / f"telegram_{chat}_{nome}"
        self.telegram.baixar(documento["file_id"], destino)
        return "Recebi o arquivo. O resumo da compra vai aparecer aqui e no assistente do PC para você confirmar."

    def _contexto_skill(self, skill=None) -> Contexto:
        """O que as skills podem usar: serviços e a política de repetição. Nada de runtime ou IPC."""
        servicos = {
            "shopping_assistant": self.shopping_assistant,
            "inventory_assistant": self.inventory_assistant,
            "db_service": self.db_service,
            "project_analyzer": getattr(self, "project_analyzer", None),
            "progresso": lambda mensagem: emitir_electron("debug_log", {"message": mensagem}),
            "ideias": getattr(self, "ideias", None),
            "canal": getattr(self, "_canal_atual", "chat"),
            # Modelo local residente, para qualquer skill (SK6): uma skill nova não precisa mudar o núcleo
            "llm_local": LocalLLMProvider(temperatura=0.1),
        }
        if skill is not None and skill.nome == "programacao":
            servicos.update({
                "historico": list(self.sessao.historico),
                "biblioteca": getattr(self, "biblioteca", None),
                "llm_programacao": LocalLLMProvider(modelo=llm_provider_estado.MODELO_AVANCADO, temperatura=0.2),
            })
        # Política do núcleo: o Claude só é entregue às skills autorizadas e que o declaram no cabeçalho
        if skill is not None and skill.privacidade == "claude" and skill.nome in CLAUDE_SKILLS:
            servicos["claude"] = getattr(self, "claude_service", None)
        return Contexto(servicos=servicos, repetir=self._repetir)

    def _responder_pendencia(self, texto: str):
        """Encaminha a resposta do usuário à skill que pediu confirmação."""
        nome, dados = self.pendencia
        self.pendencia = None
        skill = obter_catalogo().skill(nome)
        resposta = motor_skills.responder_pendencia(skill, self._contexto_skill(skill), texto, dados)
        if resposta.pendencia is not None:
            self.pendencia = (nome, resposta.pendencia)
        return self._entregar_resposta(resposta.texto, resposta.fala)

    # -------------------------------------------------------------------------
    # Processamento de Solicitação (Orquestração)
    # -------------------------------------------------------------------------

    def _pode_usar_nuvem(self, contexto: str) -> bool:
        """O Gemini só atende perguntas gerais, fora do Modo Qwen e com chave configurada."""
        return (
            contexto in self.CONTEXTOS_NUVEM
            and not llm_provider_estado.MODO_QWEN_ATIVO
            and self.ai_service.disponivel()
        )

    def _avisar_ollama_fora(self, texto_original: str):
        """Resposta imediata quando o Ollama está fechado; a interface oferece reenviar o mesmo texto."""
        logger.warning("⚠️ Ollama indisponível. Solicitação não processada.")
        custom_logger.log_geral("Ollama indisponível: solicitação não processada nem enviada à nuvem.")
        self._falar_se_permitido("O Ollama não está em execução. Abra o Ollama e tente de novo.")
        emitir_electron("assistant_message", {"text": MSG_OLLAMA_FORA, "tentar_novamente": texto_original})
        self._set_estado("WAITING_INPUT")
        return MSG_OLLAMA_FORA

    def _entregar_resposta(self, resposta_texto: str, fala_texto: str = None):
        """Fala e exibe a resposta e devolve o sistema à espera de entrada."""
        logger.info(f"🗣️ [Resposta Final]: {resposta_texto}")
        self._falar_se_permitido(fala_texto or resposta_texto)
        emitir_electron("assistant_message", {"text": resposta_texto})
        self._set_estado("WAITING_INPUT")
        return resposta_texto

    def _processar_solicitacao(self, transcricao: str, canal: str = "chat"):
        """Abre uma requisição no registro de eventos (M26) e executa o pipeline. canal: 'chat' ou 'voz' (M09)."""
        self._canal_atual = canal
        with custom_logger.requisicao(canal=canal, caracteres=len(transcricao or "")):
            return self._executar_pipeline(transcricao)

    def _executar_pipeline(self, transcricao: str):
        """Pipeline completo de processamento: Orquestração → Execução → Resposta."""
        solicitacao_original = transcricao

        logger.info(f"👤 [Usuário]: '{solicitacao_original}'")
        custom_logger.log_geral(f"Entrada recebida: '{custom_logger.conteudo(solicitacao_original)}'")

        self._set_estado("PROCESSING")

        if self.pendencia is not None:
            return self._responder_pendencia(solicitacao_original)

        # =====================================================================
        # PASSO 1: Orquestração Gemma 4
        # =====================================================================
        try:
            decisao = execute_with_retry(
                func=custom_logger.cronometrado("roteamento", orquestrar_requisicao),
                args=(solicitacao_original,),
                kwargs={"contexto_atual": self.sessao.contexto_ativo},
                max_tentativas=MAX_TENTATIVAS,
                tempo_espera=TEMPO_RETRY,
                excecoes_recuperaveis=(InvalidOrchestratorOutputException, Exception),
                excecoes_fatais=(OllamaIndisponivelException,),
                voice_service=self.voice_service if self.voice_mode_active else None,
                mensagem_espera_voz="Aguarde um instante, estou reprocessando sua solicitação.",
                nome_servico="Gemma4-Orquestrador"
            )
        except OllamaIndisponivelException:
            # Repetir não adianta e, sem classificação, nada vai à nuvem
            return self._avisar_ollama_fora(solicitacao_original)
        except MaxRetriesExceededException:
            # Sem classificação, o texto pode ser privado (ex.: uma compra): nada vai à nuvem
            logger.warning("⚠️ Gemma 4 excedeu retries. Solicitação não encaminhada à nuvem.")
            custom_logger.log_geral("Orquestrador indisponível: solicitação não encaminhada à nuvem.")
            return self._entregar_resposta(MSG_IA_LOCAL_INDISPONIVEL)

        logger.info(f"🧠 [Decisão do Orquestrador]: {decisao}")
        custom_logger.evento(
            "main", "decisao",
            skill=decisao.get("skill"), contexto=decisao.get("contexto"), acao=decisao.get("acao"),
            resposta_direta="resposta_direta" in decisao,
        )

        contexto = decisao.get("contexto", "outro")
        mudanca_contexto = decisao.get("mudanca_de_contexto", False)

        # =====================================================================
        # INTERCEPTAÇÃO: Resposta direta
        # =====================================================================
        if "resposta_direta" in decisao:
            resposta_texto = decisao["resposta_direta"]
            self.sessao.atualizar_sessao(contexto, solicitacao_original, resposta_texto, mudanca_de_contexto=mudanca_contexto)

            logger.info(f"🗣️ [Resposta Final]: {resposta_texto}")
            self._falar_se_permitido(resposta_texto)

            emitir_electron("assistant_message", {"text": resposta_texto})
            self._set_estado("WAITING_INPUT")
            return resposta_texto

        resposta_texto = ""
        fala_texto = None
        # M16: a nuvem só entra quando a pessoa pede (ou na falha local, mais abaixo), nunca pela "dificuldade"
        usar_nuvem = pede_nuvem(solicitacao_original) and self._pode_usar_nuvem(contexto)

        # =====================================================================
        # PASSO 2: Roteamento de Execução
        # =====================================================================
        if not usar_nuvem:
            logger.info("⚡ Processando LOCALMENTE...")

            try:
                skill = obter_catalogo().por_contexto(contexto)
                resposta = None
                if skill is not None and skill.execucao == "roteiro":
                    # SK3: compras, estoque e agenda executam o roteiro da própria skill
                    resposta = motor_skills.executar(skill, self._contexto_skill(skill), solicitacao_original, decisao)
                    destino = obter_catalogo().skill(resposta.encaminhar) if resposta.encaminhar else None
                    if destino is not None and destino.execucao == "nucleo":
                        # A skill devolveu o pedido (ex.: "me dê ideias de..." não é uma ideia salva, P23)
                        custom_logger.evento("main", "encaminhada", de=skill.nome, para=destino.nome)
                        contexto = destino.contexto
                        resposta = None
                    else:
                        resposta_texto, fala_texto = resposta.texto, resposta.fala
                        if resposta.pendencia is not None:
                            self.pendencia = (skill.nome, resposta.pendencia)

                if resposta is not None:
                    pass  # o roteiro da skill já respondeu
                elif pede_nuvem(solicitacao_original) and self._pode_usar_nuvem(contexto):
                    usar_nuvem = True  # encaminhada para a conversa geral, e a pessoa pediu a nuvem
                else:
                    resposta_texto = execute_with_retry(
                        func=custom_logger.cronometrado("assistente_local", executar_assistente_local),
                        args=(contexto, self.sessao.historico, self._enriquecer_com_memoria(solicitacao_original, contexto)),
                        max_tentativas=MAX_TENTATIVAS,
                        tempo_espera=TEMPO_RETRY,
                        voice_service=self.voice_service if self.voice_mode_active else None,
                        mensagem_espera_voz="Processando sua solicitação localmente.",
                        excecoes_fatais=(OllamaIndisponivelException,),
                        nome_servico="AssistenteLocal"
                    )

            except (MaxRetriesExceededException, OllamaIndisponivelException) as e:
                ollama_fora = isinstance(e, OllamaIndisponivelException)
                if self._pode_usar_nuvem(contexto):
                    logger.error("❌ Falha crítica local. Redirecionando para Nuvem...")
                    usar_nuvem = True
                elif ollama_fora:
                    return self._avisar_ollama_fora(solicitacao_original)
                else:
                    logger.error("❌ Falha crítica local em contexto restrito. Nada enviado à nuvem.")
                    return self._entregar_resposta(MSG_IA_LOCAL_INDISPONIVEL)

        if usar_nuvem:
            logger.info("☁️ Processando na NUVEM via Gemini...")
            # O histórico só acompanha o pedido se a conversa em curso também pode ir à nuvem
            historico_nuvem = self.sessao.historico if self.sessao.contexto_ativo in self.CONTEXTOS_NUVEM else []

            try:
                resposta_texto = execute_with_retry(
                    func=custom_logger.cronometrado("nuvem", self.ai_service.processar_requisicao_complexa),
                    args=(self._enriquecer_com_memoria(solicitacao_original, contexto, para_nuvem=True), historico_nuvem),
                    max_tentativas=MAX_TENTATIVAS,
                    tempo_espera=TEMPO_RETRY,
                    excecoes_recuperaveis=(ServiceUnavailableException, Exception),
                    excecoes_fatais=(TokenExhaustedException,),
                    voice_service=self.voice_service if self.voice_mode_active else None,
                    mensagem_espera_voz="Tráfego congestionado na nuvem. Aguardando reenvio.",
                    nome_servico="Gemini-Nuvem"
                )
            except TokenExhaustedException as e:
                logger.warning(f"AVISO DE TOKENS: {e}")
                return self._entregar_resposta("O limite de uso do Gemini foi atingido. Tente novamente mais tarde.")
            except MaxRetriesExceededException:
                return self._entregar_resposta("Desculpe, o serviço de inteligência na nuvem está indisponível no momento. Tente novamente mais tarde.")

        self.sessao.atualizar_sessao(contexto, solicitacao_original, resposta_texto, mudanca_de_contexto=mudanca_contexto)

        # =====================================================================
        # PASSO 3: Resposta
        # =====================================================================
        if resposta_texto:
            self._entregar_resposta(resposta_texto, fala_texto)
        else:
            self._set_estado("WAITING_INPUT")

        # Depois da resposta: gravar a memória pode aguardar a carga do modelo de embeddings
        self._registrar_memoria(solicitacao_original, contexto)
        return resposta_texto

    # -------------------------------------------------------------------------
    # Threads de Leitura
    # -------------------------------------------------------------------------

    def _leitor_stdin(self):
        """Thread daemon para ler comandos do Electron (pipe isolado em ENTRADA_IPC)."""
        while not self.deve_encerrar:
            try:
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
            emitir_electron("debug_log", {"message": "Cópia de segurança automática desativada (BACKUP_ATIVO=0)."})
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
            ao_gravar=lambda pasta: emitir_electron("debug_log", {"message": f"✓ Cópia de segurança do dia gravada em '{pasta}'."}),
            ao_falhar=lambda erro: emitir_electron("debug_log", {"message": f"⚠️ Cópia de segurança falhou: {erro}"}),
        )

    def rodar(self):
        """Entrypoint principal do runtime."""
        logger.info("Iniciando Assistente Doméstico (Modelo Text-First)")

        # =====================================================================
        # FASE 1: Serviços Essenciais (Chat disponível imediatamente depois)
        # =====================================================================
        self._inicializar_servicos_essenciais()

        # Inicia thread de leitura do stdin
        t_stdin = threading.Thread(target=self._leitor_stdin, daemon=True)
        t_stdin.start()

        # Inicia thread do microfone (ficará em espera até voice_mode_active=True)
        t_mic = threading.Thread(target=self._loop_microfone, daemon=True)
        t_mic.start()

        # Varredura inicial do estoque (em background para não bloquear)
        def _varredura_background():
            try:
                emitir_electron("debug_log", {"message": "Executando varredura preditiva de estoque inicial..."})
                self.inventory_assistant.verificar_itens_expirados_inicializacao()
                emitir_electron("debug_log", {"message": "✓ Varredura inicial de estoque concluída."})
            except Exception as e:
                logger.error(f"Erro na varredura inicial de estoque: {e}")
                emitir_electron("debug_log", {"message": f"⚠️ Erro na varredura de estoque: {e}"})

        t_varredura = threading.Thread(target=_varredura_background, daemon=True)
        t_varredura.start()

        # Avisa logo no início se o Ollama estiver fechado (M17), sem atrasar o chat
        def _verificar_ollama_inicio():
            erro = llm_provider_estado.verificar_ollama()
            if erro:
                emitir_electron("debug_log", {"message": "⚠️ Ollama não respondeu. Abra o Ollama antes de conversar com a IA local."})
            else:
                emitir_electron("debug_log", {"message": "✓ Ollama em execução."})

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
        emitir_electron("system_ready")
        self._set_estado("WAITING_INPUT")

        logger.info("🟢 Assistente pronto no MODO TEXTO. Chat desbloqueado para o usuário.")
        emitir_electron("debug_log", {"message": "Sistema pronto! Modo texto ativo. Digite suas mensagens."})

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

                # Echo para a UI
                emitir_electron("user_message", {"text": text})

                try:
                    self._processar_solicitacao(text)
                except TokenExhaustedException as e:
                    logger.warning(f"AVISO DE TOKENS: {e}")
                    self._falar_se_permitido("Limite de cota atingido para processamento na nuvem.")
                    emitir_electron("error", {"message": f"Limite de cota atingido: {e}"})
                except Exception as e:
                    logger.error(f"Falha ao processar solicitação: {e}")
                    emitir_electron("error", {"message": f"Falha ao processar solicitação: {e}"})
                finally:
                    self._set_estado("WAITING_INPUT")

            # -----------------------------------------------------------------
            # INPUT DE VOZ (vindo da thread do microfone)
            # -----------------------------------------------------------------
            elif tipo == "documento":
                self._importar_documento(payload.get("caminho", ""), payload.get("canal", "pasta"))

            elif tipo == "voice_input":
                text = payload.get("text", "").strip()
                if not text:
                    continue

                # Echo para a UI (transcrição de voz)
                emitir_electron("user_message", {"text": text})

                if self.audio_service:
                    self.audio_service.abortar_captura()

                try:
                    self._processar_solicitacao(text, canal="voz")
                except TokenExhaustedException as e:
                    logger.warning(f"AVISO DE TOKENS: {e}")
                    self._falar_se_permitido("Limite de cota atingido para processamento na nuvem.")
                except Exception as e:
                    logger.error(f"Falha ao processar solicitação por voz: {e}")
                    emitir_electron("error", {"message": f"Falha ao processar: {e}"})
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

                emitir_electron("voice_mode_status", status)

            # -----------------------------------------------------------------
            # TOGGLE MUTE (apenas controla TTS, não afeta microfone)
            # -----------------------------------------------------------------
            elif tipo == "toggle_mute":
                self.is_muted = payload.get("muted", not self.is_muted)
                logger.info(f"🔊 Estado do Áudio alterado: Mudo = {self.is_muted}")
                emitir_electron("debug_log", {
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


if __name__ == "__main__":
    runtime = AssistenteRuntime()
    runtime.rodar()