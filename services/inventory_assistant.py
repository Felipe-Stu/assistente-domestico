import logging
import json
import re
from datetime import datetime
from typing import Optional, Dict, Any
from google import genai
from google.genai import types
from services.voice_service import VoiceService
from services.audio_service import AudioService
from services.logger_service import logger as custom_logger

# Logger de console (terminal)
logger = logging.getLogger(__name__)

# Identificador do serviço para o logger estruturado em arquivo
NOME_ASSISTENTE = "inventory_assistant"

class InventoryAssistant:
    def __init__(self, db_service):
        self.db = db_service
        self.voice = VoiceService()
        self.audio = AudioService()
        self.client = genai.Client()
        
        custom_logger.log_assistente(NOME_ASSISTENTE, "Inicialização do serviço InventoryAssistant concluída.")

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

    def _classificar_resposta_localmente(self, resposta_texto: str) -> Optional[Dict[str, Any]]:
        """
        Classifica a resposta localmente via Regex/Heurísticas para economizar latência/API.
        """
        texto = resposta_texto.lower().strip().replace(".", "").replace(",", "").strip()
        
        confirmacoes = {"sim", "correto", "confirmo", "está certo", "esta certo", "procede", "exatamente", "isso mesmo", "pode manter", "confere", "certo", "ok", "beleza", "isso", "pode"}
        zerados = {"acabou", "acabou tudo", "não tem mais", "nao tem mais", "zerou", "ficou sem", "terminou", "não sobrou nenhum", "nao sobrou nenhum", "acabou por completo", "acabou totalmente", "naum tem mais", "num tem mais", "não tem mas", "na um tem", "acabou tudu"}
        sem_consumo = {"não usei", "nao usei", "não consumi", "nao consumi", "continua fechado", "está fechado", "esta fechado", "tá fechado", "ta fechado", "está lacrado", "esta lacrado", "nem abri", "continua inteiro", "continua cheio", "não mexi", "nao mexi", "está intacto", "esta intacto"}
        
        # 1. Match sem negações
        if any(c in texto for c in confirmacoes):
            if not any(neg in texto for neg in ["não", "nao", "num", "naum", "nem"]):
                return {"intencao": "CONFIRMACAO", "quantidade_real": None}
                
        if any(z in texto for z in zerados):
            if not any(neg + " acabou" in texto for neg in ["não", "nao", "num", "naum"]):
                return {"intencao": "NEGATIVA_ZERADO", "quantidade_real": None}
                
        if any(s in texto for s in sem_consumo):
            return {"intencao": "NEGATIVA_SEM_CONSUMO", "quantidade_real": None}

        # 2. Detectar quantidade via Regex
        mapa_numeros = {
            "meio": 0.5, "um": 1.0, "uma": 1.0, "dois": 2.0, "duas": 2.0,
            "três": 3.0, "tres": 3.0, "quatro": 4.0, "cinco": 5.0,
            "seis": 6.0, "sete": 7.0, "oito": 8.0, "nove": 9.0, "dez": 10.0
        }
        
        padrao_qtd = r"\b(meio|uma?|dois|duas|três|tres|quatro|cinco|seis|sete|oito|nove|dez|\d+(?:[\.,]\d+)?)\b"
        matches = re.findall(padrao_qtd, texto)
        
        if matches:
            verbos_ou_palavras = ["tenho", "resta", "sobrou", "sobraram", "só", "so", "tem", "fica", "ficou", "unidade", "unidades", "litro", "litros", "kg", "quilo", "quilos", "pacote", "pacotes", "caixa", "caixas"]
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

    def _classificar_resposta_usuario(self, resposta_texto: str) -> Dict[str, Any]:
        """Tenta classificação local e, se falhar, usa Gemini com Structured Output."""
        analise_local = self._classificar_resposta_localmente(resposta_texto)
        if analise_local:
            msg_local = f"Intenção '{analise_local['intencao']}' classificada LOCALMENTE para: '{resposta_texto}'"
            logger.info(msg_local)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_local)
            return analise_local
            
        msg_remoto = f"Classificação local falhou para: '{resposta_texto}'. Acionando a API do Gemini..."
        logger.info(msg_remoto)
        custom_logger.log_assistente(NOME_ASSISTENTE, msg_remoto)
        
        prompt = f"""
        Você é um classificador de intenções para controle de estoque por voz.
        Classifique a intenção do usuário no JSON indicado.

        INTENÇÕES:
        - CONFIRMACAO: Concorda com a estimativa.
        - NEGATIVA_ZERADO: O produto acabou totalmente.
        - NEGATIVA_SEM_CONSUMO: O produto não foi aberto/usado.
        - DIVERGENCIA_QUANTIDADE: Mencionou uma quantidade física explícita (retorne em quantidade_real).

        RESTRICÕES:
        Retorne apenas a intenção e quantidade_real.

        TEXTO DO USUÁRIO:
        {resposta_texto}
        """
        
        try:
            response = self.client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    temperature=0.0
                )
            )
            texto_puro = response.text.strip()
            resultado = json.loads(texto_puro)
            custom_logger.log_assistente(
                NOME_ASSISTENTE, 
                f"Classificação remota concluída pelo Gemini: {resultado}"
            )
            return resultado
        except Exception as e:
            msg_erro_llm = f"Falha na chamada/parse da LLM (Gemini): {e}. Aplicando fallback."
            logger.error(msg_erro_llm)
            custom_logger.log_assistente(NOME_ASSISTENTE, msg_erro_llm)
            return {"intencao": "CONFIRMACAO", "quantidade_real": None}

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
        self.voice.falar(pergunta)
        
        resposta_bruta = self.audio.capturar_audio_e_transcrever(ativar_trava_inicial=False)
        custom_logger.log_assistente(NOME_ASSISTENTE, f"Resposta do usuário para o resíduo de '{nome_produto}': '{resposta_bruta}'")
        
        analise = self._classificar_resposta_usuario(resposta_bruta)
        
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