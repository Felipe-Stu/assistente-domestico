from datetime import datetime
import json
import logging
import re
from typing import Any, Callable, Dict, Optional

from services.audio_service import AudioService
from services.llm_provider import BaseLLMProvider
from services.logger_service import logger as custom_logger
from services.voice_service import VoiceService

# Logger de console (terminal)
logger = logging.getLogger(__name__)

# Identificador do serviço para o logger estruturado
NOME_ASSISTENTE = "inventory_assistant"


class InventoryAssistant:
    def __init__(
        self,
        db_service: Any,
        ai_service: Any = None,
        llm_provider: Optional[BaseLLMProvider] = None,
        voice_service: Optional[VoiceService] = None,
        audio_service: Optional[AudioService] = None,
        modo_voz_ativo: Optional[Callable[[], bool]] = None
    ):
        """
        Inicializa o assistente de controle de estoque.
        Suporta o Gemma 4 local via llm_provider ou ai_service.

        voice_service / audio_service: instâncias compartilhadas do runtime (V4).
        modo_voz_ativo: função que informa se o usuário ativou o modo voz na interface.
        Sem modo voz, o assistente não fala nem escuta (modelo Text-First).
        """
        self.db = db_service
        self.voice = voice_service or VoiceService()
        self.audio = audio_service or AudioService()
        self._modo_voz_ativo = modo_voz_ativo
        self.ai_service = ai_service
        self.llm_provider = llm_provider or ai_service

        if not self.llm_provider:
            logger.warning("InventoryAssistant inicializado sem 'llm_provider' ou 'ai_service' local configurado.")

        custom_logger.log_assistente(
            NOME_ASSISTENTE, 
            "Inicialização do serviço InventoryAssistant (Gemma 4 Local) concluída com sucesso."
        )

    def _voz_disponivel(self) -> bool:
        """True somente se o modo voz está ativo e TTS + microfone estão prontos."""
        if self._modo_voz_ativo is not None and not self._modo_voz_ativo():
            return False
        return self.voice.esta_disponivel() and self.audio.esta_disponivel()

    # =========================================================================
    # CONSULTA DE ESTOQUE (V4) — somente leitura, sem LLM
    # =========================================================================

    PALAVRAS_IGNORADAS_CONSULTA = {
        "ainda", "tenho", "temos", "tem", "quanto", "quantos", "quantas", "quanta",
        "qual", "quais", "que", "meu", "minha", "meus", "minhas", "nosso", "nossa",
        "estoque", "inventario", "inventário", "casa", "sobrou", "sobra", "resta",
        "restam", "falta", "faltando", "acabando", "acabou", "possuo", "existe",
        "consulta", "consultar", "verifica", "verificar", "mostra", "mostrar",
        "lista", "listar", "itens", "produtos", "produto", "item", "para", "com",
        "por", "dos", "das", "nos", "nas", "uma", "algum", "alguma", "tudo",
        "todos", "todas", "agora", "hoje", "aqui", "ali", "isso", "esse", "essa",
        "pode", "poderia", "favor", "sabe", "saber", "dizer", "fala", "ver",
    }

    @staticmethod
    def _formatar_numero(valor: float) -> str:
        return f"{valor:.1f}".replace(".", ",")

    def _estimar_estoque_restante(self, qtd_comprada, qtd_residual, ritmo, data_ultima) -> float:
        """Mesma fórmula de processar_estoque_nova_compra: total - dias/ritmo."""
        dias = self._calcular_dias_decorridos(data_ultima)
        total = (qtd_comprada or 0.0) + (qtd_residual or 0.0)
        consumo = dias / ritmo if ritmo and ritmo > 0 else 0.0
        return max(0.0, total - consumo)

    def _extrair_termos_produto(self, texto: str) -> list:
        palavras = re.findall(r"[a-zà-ú]+", (texto or "").lower())
        return [p for p in palavras if len(p) >= 3 and p not in self.PALAVRAS_IGNORADAS_CONSULTA]

    def consultar_estoque(self, texto_usuario: str, limite: int = 15) -> str:
        """
        Responde consultas de estoque ("ainda tenho leite?", "o que tenho em estoque?").
        Lê controle_consumo (status_estoque = 1) e estima o restante pelo ritmo de consumo.
        Não altera o banco.
        """
        custom_logger.log_assistente(NOME_ASSISTENTE, f"Consulta de estoque recebida: '{texto_usuario}'")

        itens = self.db.executar_consulta(
            """SELECT produto_nome, quantidade_comprada, quantidade_residual_confirmada,
                      tempo_medio_calculado, data_ultima_compra, validacao_pendente
               FROM controle_consumo
               WHERE status_estoque = 1
               ORDER BY produto_nome"""
        )

        if not itens:
            return "Seu estoque ativo está vazio no momento. Nenhum produto registrado."

        termos = self._extrair_termos_produto(texto_usuario)
        if termos:
            def corresponde(nome: str) -> bool:
                nome_lower = nome.lower()
                return any(t in nome_lower or (t.endswith("s") and t[:-1] in nome_lower) for t in termos)
            selecionados = [it for it in itens if corresponde(it[0])]
            if not selecionados:
                msg = f"Não encontrei estoque ativo para: {', '.join(termos)}."
                custom_logger.log_assistente(NOME_ASSISTENTE, msg)
                return msg
        else:
            selecionados = list(itens)

        linhas = []
        for nome, qtd_comprada, qtd_residual, ritmo, data_ultima, pendente in selecionados[:limite]:
            restante = self._estimar_estoque_restante(qtd_comprada, qtd_residual, ritmo, data_ultima)
            linha = f"{nome}: cerca de {self._formatar_numero(restante)} restante(s) (última compra em {data_ultima})"
            if pendente:
                linha += " — aguardando sua confirmação"
            linhas.append(linha)

        if len(selecionados) > limite:
            linhas.append(f"... e mais {len(selecionados) - limite} item(ns).")

        resposta = "Estimativa do seu estoque:\n" + "\n".join(f"- {l}" for l in linhas)
        custom_logger.log_assistente(NOME_ASSISTENTE, f"Consulta respondida com {len(selecionados)} item(ns).")
        return resposta

    def _calcular_dias_decorridos(self, data_anterior_str: str) -> int:
        """Calcula a diferença em dias entre a data atual e a data da última compra."""
        try:
            data_atual = datetime.now().date()
            data_anterior = datetime.strptime(data_anterior_str, "%Y-%m-%d").date()
            dias = max(0, (data_atual - data_anterior).days)
            custom_logger.log_assistente(
                NOME_ASSISTENTE, 
                f"Cálculo de dias decorridos: {dias} dia(s) desde {data_anterior_str}."
            )
            return dias
        except (ValueError, TypeError) as e:
            msg_erro = f"Erro ao converter data '{data_anterior_str}': {e}"
            logger.error(msg_erro)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_erro)
            return 0

    def _heuristica_rapida(self, resposta_texto: str) -> Optional[Dict[str, Any]]:
        """
        Análise rápida via Regex/Heurística de baixíssima latência para termos diretos.
        """
        texto = resposta_texto.lower().strip().replace(".", "").replace(",", "").strip()

        confirmacoes = {
            "sim", "correto", "confirmo", "está certo", "esta certo", "procede", 
            "exatamente", "isso mesmo", "pode manter", "confere", "certo", "ok", "beleza", "isso", "pode"
        }
        zerados = {
            "acabou", "acabou tudo", "não tem mais", "nao tem mais", "zerou", 
            "ficou sem", "terminou", "não sobrou nenhum", "nao sobrou nenhum", 
            "acabou por completo", "acabou totalmente", "naum tem mais", "num tem mais"
        }
        sem_consumo = {
            "não usei", "nao usei", "não consumi", "nao consumi", "continua fechado", 
            "está fechado", "esta fechado", "tá fechado", "ta fechado", "está lacrado", 
            "esta lacrado", "nem abri", "continua inteiro", "continua cheio", "não mexi", "nao mexi"
        }

        # 1. Checagem de intenções diretas sem negação ambígua
        if any(c in texto for c in confirmacoes):
            if not any(neg in texto for neg in ["não", "nao", "num", "naum", "nem"]):
                return {"intencao": "CONFIRMACAO", "quantidade_real": None}

        if any(z in texto for z in zerados):
            if not any(neg + " acabou" in texto for neg in ["não", "nao", "num", "naum"]):
                return {"intencao": "NEGATIVA_ZERADO", "quantidade_real": None}

        if any(s in texto for s in sem_consumo):
            return {"intencao": "NEGATIVA_SEM_CONSUMO", "quantidade_real": None}

        # 2. Detecção de quantidade rápida via Regex
        mapa_numeros = {
            "meio": 0.5, "um": 1.0, "uma": 1.0, "dois": 2.0, "duas": 2.0,
            "três": 3.0, "tres": 3.0, "quatro": 4.0, "cinco": 5.0,
            "seis": 6.0, "sete": 7.0, "oito": 8.0, "nove": 9.0, "dez": 10.0
        }

        padrao_qtd = r"\b(meio|uma?|dois|duas|três|tres|quatro|cinco|seis|sete|oito|nove|dez|\d+(?:[\.,]\d+)?)\b"
        matches = re.findall(padrao_qtd, texto)

        if matches:
            verbos_ou_palavras = [
                "tenho", "resta", "sobrou", "sobraram", "só", "so", "tem", "fica", "ficou", 
                "unidade", "unidades", "litro", "litros", "kg", "quilo", "quilos", "pacote", "pacotes", "caixa", "caixas"
            ]
            if len(texto.split()) <= 4 or any(palavra in texto for palavra in verbos_ou_palavras):
                val_str = matches[0]
                if val_str in mapa_numeros:
                    qtd_real = mapa_numeros[val_str]
                else:
                    try:
                        qtd_real = float(val_str.replace(",", "."))
                    except ValueError:
                        return None
                return {"intencao": "DIVERGENCIA_QUANTIDADE", "quantidade_real": qtd_real}

        return None

    def _classificar_resposta_localmente(self, resposta_texto: str) -> Dict[str, Any]:
        """
        Classifica a intenção do usuário priorizando a execução 100% local com Gemma 4.
        Combina heurística ultra-rápida (padrões simples) com o poder do modelo Gemma 4 Local.
        """
        # Passagem 1: Heurística ultra-rápida (0 ms)
        resultado_heuristica = self._heuristica_rapida(resposta_texto)
        if resultado_heuristica:
            msg_h = f"Intenção '{resultado_heuristica['intencao']}' identificada via Heurística Rápida Local para: '{resposta_texto}'"
            logger.info(msg_h)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_h)
            return resultado_heuristica

        # Passagem 2: Processamento avançado com Gemma 4 Local
        if not self.llm_provider:
            logger.warning("Gemma 4 Local não disponível. Aplicando fallback de confirmação padrão.")
            return {"intencao": "CONFIRMACAO", "quantidade_real": None}

        msg_gemma = f"Executando classificação inteligente com Gemma 4 Local para: '{resposta_texto}'"
        logger.info(msg_gemma)
        custom_logger.log_assistente(NOME_ASSISTENTE, msg_gemma)

        prompt_sistema = """
        Você é um classificador local especializado em controle de estoque residencial por voz.
        Sua missão é extrair a intenção e quantidade informada pelo usuário a partir da transcrição de áudio.

        INTENÇÕES PERMITIDAS:
        1. "CONFIRMACAO": O usuário concorda com o valor estimado ou diz que está tudo certo.
        2. "NEGATIVA_ZERADO": O usuário afirma que o produto acabou, zerou, acabou tudo ou não tem mais nada.
        3. "NEGATIVA_SEM_CONSUMO": O usuário afirma que não abriu, não usou, continua lacrado ou intacto.
        4. "DIVERGENCIA_QUANTIDADE": O usuário menciona uma quantidade física explícita restante (ex: "tenho 2 pacotes", "sobraram 1.5 litros", "só tem meio quilo").

        REGRAS:
        - Se a intenção for "DIVERGENCIA_QUANTIDADE", extraia o número em "quantidade_real" (float).
        - Se não houver quantidade informada, "quantidade_real" deve ser null.
        - Retorne estritamente um JSON no formato exigido, sem markdown extra.

        FORMATO OBRIGATÓRIO DE SAÍDA:
        {
            "intencao": "CONFIRMACAO" | "NEGATIVA_ZERADO" | "NEGATIVA_SEM_CONSUMO" | "DIVERGENCIA_QUANTIDADE",
            "quantidade_real": float ou null
        }
"""

        try:
            resultado_gemma = self.llm_provider.gerar_json(
                prompt_sistema=prompt_sistema,
                mensagem_usuario=resposta_texto
            )

            if isinstance(resultado_gemma, dict) and "intencao" in resultado_gemma:
                custom_logger.log_assistente(
                    NOME_ASSISTENTE, 
                    f"Classificação concluída pelo Gemma 4 Local com sucesso: {resultado_gemma}"
                )
                return resultado_gemma

        except Exception as e:
            msg_erro_gemma = f"Erro ao processar classificação local com Gemma 4: {e}. Usando fallback."
            logger.error(msg_erro_gemma)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_erro_gemma)

        return {"intencao": "CONFIRMACAO", "quantidade_real": None}

    def _classificar_resposta_usuario(self, resposta_texto: str) -> Dict[str, Any]:
        """Interface unificada de classificação delegando inteiramente para a pipeline Local (Gemma 4)."""
        return self._classificar_resposta_localmente(resposta_texto)

    def verificar_itens_expirados_inicializacao(self):
        """Passo 1: Executado na inicialização. Varre itens com autonomia esgotada."""
        msg_init = "Executando varredura preditiva de estoque..."
        logger.info(msg_init)
        custom_logger.log_assistente(NOME_ASSISTENTE, msg_init)

        query = """
            SELECT id, produto_nome, tempo_medio_calculado, data_ultima_compra, 
                   quantidade_comprada, quantidade_residual_confirmada 
            FROM controle_consumo 
            WHERE status_estoque = 1
        """
        itens_ativos = self.db.executar_consulta(query)

        for item in itens_ativos:
            id_item, nome, ritmo, data_ultima, qtd_comprada, qtd_residual = item

            dias_decorridos = self._calcular_dias_decorridos(data_ultima)
            estoque_antigo_total = qtd_comprada + qtd_residual
            autonomia_total = estoque_antigo_total * ritmo

            if dias_decorridos > autonomia_total:
                msg_expirado = f"Item expirado identificado: '{nome}' (Dias decorridos: {dias_decorridos}, Autonomia estimada: {autonomia_total})."
                custom_logger.log_assistente(NOME_ASSISTENTE, msg_expirado)

                if not self._voz_disponivel():
                    # Modo texto: não pergunta por voz; marca para validação posterior
                    self.db.marcar_validacao_pendente(id_item)
                    custom_logger.log_assistente(
                        NOME_ASSISTENTE,
                        f"Modo voz inativo. '{nome}' marcado com validação pendente."
                    )
                    continue

                pergunta = f"Felipe, notei que o tempo estimado para o seu estoque de {nome} acabou. O produto chegou ao fim?"
                self.voice.falar(pergunta)

                resposta_bruta = self.audio.capturar_audio_e_transcrever(ativar_trava_inicial=False)
                custom_logger.log_assistente(NOME_ASSISTENTE, f"Resposta por voz capturada: '{resposta_bruta}'")

                analise = self._classificar_resposta_usuario(resposta_bruta)
                intencao = str(analise.get("intencao", "")).upper().strip()

                data_atual_str = datetime.now().strftime("%Y-%m-%d")

                if intencao in ("CONFIRMACAO", "NEGATIVA_ZERADO") or any(w in resposta_bruta.lower() for w in ["sim", "acabou"]):
                    msg_esgotado = f"'{nome}' confirmado como esgotado na inicialização."
                    logger.info(msg_esgotado)
                    custom_logger.log_assistente(NOME_ASSISTENTE, msg_esgotado)

                    novo_ritmo = max(1.0, dias_decorridos / estoque_antigo_total) if (dias_decorridos > 0 and estoque_antigo_total > 0) else max(1.0, ritmo)

                    self.db.executar_comando(
                        """UPDATE controle_consumo 
                           SET tempo_medio_calculado = ?, 
                               quantidade_comprada = 0.0, 
                               quantidade_residual_confirmada = 0.0, 
                               status_estoque = 0, 
                               validacao_pendente = 0,
                               ultima_qtd_comprada = ?, 
                               quantidade_residual_esgotada = 0.0,
                               data_ultima_compra = ? 
                           WHERE id = ?""", 
                        (novo_ritmo, qtd_comprada, data_atual_str, id_item)
                    )
                else:
                    msg_ativo = f"'{nome}' ainda possui estoque segundo o usuário. Mantendo registro ativo."
                    logger.info(msg_ativo)
                    custom_logger.log_assistente(NOME_ASSISTENTE, msg_ativo)

    def processar_estoque_nova_compra(self, nome_produto: str, nova_quantidade: float) -> float:
        """Passo 2: Processa a entrada de uma nova compra e ajusta os resíduos do lote anterior."""
        custom_logger.log_assistente(
            NOME_ASSISTENTE, 
            f"Processando entrada de nova compra para '{nome_produto}' (Qtd: {nova_quantidade})."
        )

        query = """
            SELECT id, produto_nome, tempo_medio_calculado, data_ultima_compra, 
                   quantidade_comprada, quantidade_residual_confirmada, status_estoque 
            FROM controle_consumo 
            WHERE produto_nome = ?
        """
        item = self.db.executar_consulta_uma_linha(query, (nome_produto,))
        if not item:
            custom_logger.log_assistente(NOME_ASSISTENTE, f"Produto '{nome_produto}' não localizado no controle de consumo.")
            return 0.0

        id_item, _, ritmo, data_ultima, qtd_comprada, qtd_residual, status_estoque = item
        data_atual_str = datetime.now().strftime("%Y-%m-%d")

        if status_estoque == 0:
            custom_logger.log_assistente(NOME_ASSISTENTE, f"Produto '{nome_produto}' estava inativo. Reativando estoque.")
            self.db.executar_comando(
                """UPDATE controle_consumo 
                   SET data_ultima_compra = ?, quantidade_comprada = ?, quantidade_residual_confirmada = 0.0, 
                       status_estoque = 1, ultima_qtd_comprada = ? 
                   WHERE id = ?""",
                (data_atual_str, nova_quantidade, nova_quantidade, id_item)
            )
            return 0.0

        dias_decorridos = self._calcular_dias_decorridos(data_ultima)
        consumo_estimado = dias_decorridos / ritmo if ritmo > 0 else 0
        estoque_antigo_total = qtd_comprada + qtd_residual
        residuos_estimado = max(0.0, estoque_antigo_total - consumo_estimado)

        if residuos_estimado < 0.1:
            custom_logger.log_assistente(
                NOME_ASSISTENTE, 
                f"Resíduo estimado insignificante ({residuos_estimado:.2f}). Atualizando base diretamente."
            )
            self.db.executar_comando(
                """UPDATE controle_consumo 
                   SET data_ultima_compra = ?, quantidade_comprada = ?, quantidade_residual_confirmada = 0.0, 
                       status_estoque = 1, ultima_qtd_comprada = ? 
                   WHERE id = ?""",
                (data_atual_str, nova_quantidade, nova_quantidade, id_item)
            )
            return 0.0

        pergunta = (
            f"Pelo que consta, você deve possuir ainda cerca de {residuos_estimado:.1f} unidades ou litros de {nome_produto} em estoque. "
            f"Confirma que possui essa quantidade?"
        )
        if self._voz_disponivel():
            self.voice.falar(pergunta)

            resposta_bruta = self.audio.capturar_audio_e_transcrever(ativar_trava_inicial=False)
            custom_logger.log_assistente(NOME_ASSISTENTE, f"Resposta do usuário para o resíduo de '{nome_produto}': '{resposta_bruta}'")

            analise = self._classificar_resposta_usuario(resposta_bruta)
        else:
            # Modo texto: sem pergunta por voz, mantém o resíduo estimado
            resposta_bruta = ""
            analise = {"intencao": "CONFIRMACAO"}
            custom_logger.log_assistente(
                NOME_ASSISTENTE,
                f"Modo voz inativo. Resíduo estimado de '{nome_produto}' mantido sem confirmação."
            )

        intencao = str(analise.get("intencao", "")).upper().strip()
        qtd_real = analise.get("quantidade_real")

        if intencao == "DIVERGENCIA_QUANTIDADE" and qtd_real is not None:
            msg_divergencia = f"Cenário: DIVERGENCIA_QUANTIDADE. Ajustando resíduo para {qtd_real} unidades."
            logger.info(msg_divergencia)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_divergencia)

            consumo_real = estoque_antigo_total - qtd_real
            ritmo_atualizado = max(1.0, dias_decorridos / consumo_real) if (consumo_real > 0 and dias_decorridos > 0) else max(1.0, ritmo)

            self.db.executar_comando(
                """UPDATE controle_consumo 
                   SET tempo_medio_calculado = ?, data_ultima_compra = ?, quantidade_comprada = ?, 
                       quantidade_residual_confirmada = ?, status_estoque = 1, ultima_qtd_comprada = ? 
                   WHERE id = ?""",
                (ritmo_atualizado, data_atual_str, nova_quantidade, float(qtd_real), nova_quantidade, id_item)
            )
            return float(qtd_real)

        elif intencao == "CONFIRMACAO":
            msg_conf = "Cenário: CONFIRMACAO. Mantendo resíduo estimado."
            logger.info(msg_conf)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_conf)

            self.db.executar_comando(
                """UPDATE controle_consumo 
                   SET data_ultima_compra = ?, quantidade_comprada = ?, quantidade_residual_confirmada = ?, 
                       status_estoque = 1, ultima_qtd_comprada = ? 
                   WHERE id = ?""",
                (data_atual_str, nova_quantidade, residuos_estimado, nova_quantidade, id_item)
            )
            return residuos_estimado

        elif intencao == "NEGATIVA_ZERADO" or any(w in resposta_bruta.lower() for w in ["não", "nao", "acabou"]):
            msg_zerado = "Cenário: NEGATIVA_ZERADO. Zerando resíduo e iniciando novo ciclo."
            logger.info(msg_zerado)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_zerado)

            novo_ritmo = max(1.0, dias_decorridos / estoque_antigo_total) if (dias_decorridos > 0 and estoque_antigo_total > 0) else max(1.0, ritmo)

            self.db.executar_comando(
                """UPDATE controle_consumo 
                   SET tempo_medio_calculado = ?, data_ultima_compra = ?, quantidade_comprada = ?, 
                       quantidade_residual_confirmada = 0.0, status_estoque = 1, validacao_pendente = 0,
                       ultima_qtd_comprada = ?, quantidade_residual_esgotada = ? 
                   WHERE id = ?""",
                (novo_ritmo, data_atual_str, nova_quantidade, qtd_comprada, residuos_estimado, id_item)
            )
            return 0.0

        elif intencao == "NEGATIVA_SEM_CONSUMO":
            msg_sem_consumo = "Cenário: NEGATIVA_SEM_CONSUMO. Mantém estoque antigo intacto."
            logger.info(msg_sem_consumo)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_sem_consumo)

            self.db.executar_comando(
                """UPDATE controle_consumo 
                   SET data_ultima_compra = ?, quantidade_comprada = ?, quantidade_residual_confirmada = ?, 
                       status_estoque = 1, ultima_qtd_comprada = ? 
                   WHERE id = ?""",
                (data_atual_str, nova_quantidade, estoque_antigo_total, nova_quantidade, id_item)
            )
            return estoque_antigo_total

        else:
            msg_fallback = "Intenção desconhecida. Aplicando Fallback para CONFIRMACAO."
            logger.warning(msg_fallback)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_fallback)

            self.db.executar_comando(
                """UPDATE controle_consumo 
                   SET data_ultima_compra = ?, quantidade_comprada = ?, quantidade_residual_confirmada = ?, 
                       status_estoque = 1, ultima_qtd_comprada = ? 
                   WHERE id = ?""",
                (data_atual_str, nova_quantidade, residuos_estimado, nova_quantidade, id_item)
            )
            return residuos_estimado

    def _executar_baixa_estoque_id(self, id_item: int, nome_produto: str) -> None:
        """Executa a baixa física do item no banco."""
        query = "SELECT quantidade_comprada, quantidade_residual_confirmada, tempo_medio_calculado, data_ultima_compra FROM controle_consumo WHERE id = ?"
        item = self.db.executar_consulta_uma_linha(query, (id_item,))
        if not item:
            custom_logger.log_assistente(NOME_ASSISTENTE, f"Não foi possível dar baixa: Item ID {id_item} não encontrado.")
            return

        qtd_comprada, qtd_residual, ritmo, data_ultima = item
        data_atual_str = datetime.now().strftime("%Y-%m-%d")

        dias_decorridos = self._calcular_dias_decorridos(data_ultima)
        estoque_antigo_total = qtd_comprada + qtd_residual
        novo_ritmo = max(1.0, dias_decorridos / estoque_antigo_total) if (dias_decorridos > 0 and estoque_antigo_total > 0) else max(1.0, ritmo)

        msg_baixa = f"Baixa voluntária processada para: '{nome_produto}' (ID: {id_item})."
        logger.info(msg_baixa)
        custom_logger.log_assistente(NOME_ASSISTENTE, msg_baixa)

        self.db.executar_comando(
            """UPDATE controle_consumo 
               SET tempo_medio_calculado = ?, 
                   quantidade_residual_confirmada = 0.0, 
                   quantidade_comprada = 0.0, 
                   status_estoque = 0, 
                   validacao_pendente = 0,
                   ultima_qtd_comprada = ?,
                   quantidade_residual_esgotada = ?,
                   data_ultima_compra = ?
               WHERE id = ?""",
            (novo_ritmo, qtd_comprada, qtd_residual, data_atual_str, id_item)
        )

    def registrar_fim_estoque_direto(self, nome_produto: str) -> bool:
        """Zera o estoque voluntariamente com suporte a ambiguidade de áudio."""
        custom_logger.log_assistente(NOME_ASSISTENTE, f"Solicitada baixa direta para produto: '{nome_produto}'")

        query_exata = "SELECT id, produto_nome FROM controle_consumo WHERE produto_nome = ? AND status_estoque = 1"
        item = self.db.executar_consulta_uma_linha(query_exata, (nome_produto,))

        if item:
            id_item, nome_real = item
            self._executar_baixa_estoque_id(id_item, nome_real)
            self.voice.falar(f"Entendido, Felipe. Já registrei que o seu estoque de {nome_real} acabou por completo.")
            return True

        query_busca = """
            SELECT id, produto_nome 
            FROM controle_consumo 
            WHERE (produto_nome LIKE ? OR categoria LIKE ?) AND status_estoque = 1
        """
        termo_like = f"%{nome_produto}%"
        itens_encontrados = self.db.executar_consulta(query_busca, (termo_like, termo_like))

        if not itens_encontrados:
            msg_nao_encontrado = f"Produto '{nome_produto}' não localizado ativo para baixa."
            logger.warning(msg_nao_encontrado)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_nao_encontrado)
            self.voice.falar(f"Não localizei nenhum estoque ativo para {nome_produto}.")
            return False

        if len(itens_encontrados) == 1:
            id_item, nome_real = itens_encontrados[0]
            self._executar_baixa_estoque_id(id_item, nome_real)
            self.voice.falar(f"Entendido, Felipe. Já registrei que o seu estoque de {nome_real} acabou por completo.")
            return True

        # Tratamento de ambiguidade
        custom_logger.log_assistente(
            NOME_ASSISTENTE, 
            f"Ambiguidade detectada para '{nome_produto}'. Opções encontradas: {len(itens_encontrados)}."
        )

        nomes_produtos = [it[1] for it in itens_encontrados]
        opcoes_fala = ", ".join(nomes_produtos[:-1]) + " ou " + nomes_produtos[-1]

        pergunta = f"Você consumiu toda a {opcoes_fala}, ou realmente todas as opções?"
        self.voice.falar(pergunta)

        resposta_bruta = self.audio.capturar_audio_e_transcrever(ativar_trava_inicial=False).lower()
        custom_logger.log_assistente(NOME_ASSISTENTE, f"Resposta sobre a ambiguidade: '{resposta_bruta}'")

        if any(w in resposta_bruta for w in ["todos", "todas", "tudo"]):
            for id_item, nome_real in itens_encontrados:
                self._executar_baixa_estoque_id(id_item, nome_real)
            self.voice.falar("Entendido. Dei baixa em todos esses produtos.")
            return True
        elif any(w in resposta_bruta for w in ["nenhum", "cancelar", "cancela"]):
            custom_logger.log_assistente(NOME_ASSISTENTE, "Operação de baixa cancelada pelo usuário.")
            self.voice.falar("Ok, nenhuma alteração foi realizada no estoque.")
            return False
        else:
            for id_item, nome_real in itens_encontrados:
                palavras_chave = [p for p in nome_real.lower().split() if len(p) > 2]
                if any(p in resposta_bruta for p in palavras_chave):
                    self._executar_baixa_estoque_id(id_item, nome_real)
                    self.voice.falar(f"Entendido, Felipe. Já registrei que o seu estoque de {nome_real} acabou por completo.")
                    return True

            custom_logger.log_assistente(NOME_ASSISTENTE, "Não foi possível desambiguar a resposta do usuário.")
            self.voice.falar("Não consegui compreender a opção. Nenhuma alteração foi realizada.")
            return False