import logging
import json
from datetime import datetime
from google import genai
from google.genai import types
from services.voice_service import VoiceService
from services.audio_service import AudioService

logger = logging.getLogger(__name__)

class InventoryAssistant:
    def __init__(self, db_service):
        self.db = db_service
        self.voice = VoiceService()
        self.audio = AudioService()
        self.client = genai.Client()

    def _calcular_dias_decorridos(self, data_anterior_str: str) -> int:
        """Calcula a diferença em dias entre a data atual e a data da última compra."""
        data_atual = datetime.now().date()
        data_anterior = datetime.strptime(data_anterior_str, "%Y-%m-%d").date()
        return max(0, (data_atual - data_anterior).days)

    def _classificar_resposta_usuario(self, resposta_texto: str) -> dict:
        """Usa o Gemini para extrair de forma estruturada a intenção e valores numéricos."""
        # Duplicamos as chaves do JSON estruturado ({{ e }}) para que a f-string as ignore e envie ao Gemini de forma textual pura.
        prompt = f"""
            # PAPEL
            Você é um classificador de intenções especializado em interpretar transcrições de áudio relacionadas ao controle de estoque residencial.
            Sua única responsabilidade é analisar a fala do usuário e classificá-la em uma das intenções definidas abaixo, extraindo a quantidade real apenas quando aplicável.
            Não responda perguntas, não converse com o usuário, não explique seu raciocínio e não faça inferências além das regras descritas neste prompt.
            ---
            # CONTEXTO
            O texto recebido é proveniente de um sistema de reconhecimento de fala (Speech-to-Text).
            Como toda transcrição automática, ela pode conter:
            * palavras incompletas;
            * palavras substituídas por outras semelhantes;
            * erros de conjugação;
            * omissão de palavras;
            * repetições;
            * ruídos;
            * sotaques;
            * regionalismos;
            * baixa qualidade do áudio;
            * cortes na gravação.

            Portanto, NÃO considere cada palavra isoladamente.
            Analise sempre o significado global da frase.
            Priorize a intenção comunicada pelo usuário, mesmo quando algumas palavras estiverem incorretas.

            Exemplos:
            Usuário falou:
            > Eu não possuo mais.

            Transcrição:
            > Eu não possua mais.

            Interpretação correta:
            A palavra "possua" é claramente um erro de transcrição para "possuo". O sentido da frase permanece negativo.
            ---
            Usuário falou:
            > Não tem mais nenhum.

            Transcrição:
            > Naum tem mais nem um.

            Interpretação correta:
            O usuário informou que o produto acabou.
            ---
            Usuário falou:
            > Está fechado.

            Transcrição:
            > Tá fechadu.

            Interpretação correta:
            O usuário informou que o produto não foi consumido.
            ---
            Usuário falou:
            > Tenho um litro.

            Transcrição:
            > Tenhu rum litru.

            Interpretação correta:
            Quantidade real = 1.
            ---
            Sempre priorize o contexto completo da frase.
            Não descarte uma intenção apenas porque uma palavra foi transcrita incorretamente.
            Caso uma palavra isolada contradiga o restante da frase, considere que ela pode ser resultado de erro de reconhecimento de voz e privilegie o significado predominante da sentença.
            ---
            # OBJETIVO
            Classifique a intenção da resposta do usuário.
            Você deve retornar exclusivamente um objeto JSON válido.
            ---
            # INTENÇÕES PERMITIDAS
            ## CONFIRMACAO
            Utilize quando o usuário concorda que a quantidade estimada está correta.

            Exemplos:
            * sim
            * correto
            * confirmo
            * está certo
            * procede
            * exatamente
            * isso mesmo
            * pode manter
            * confere
            * certo
            * ok
            * beleza
            ---
            ## NEGATIVA_ZERADO
            Utilize quando o usuário informa que o produto acabou completamente.

            Exemplos:
            * acabou
            * acabou tudo
            * não tem mais
            * zerou
            * ficou sem
            * terminou
            * não sobrou nenhum
            * acabou por completo
            * acabou totalmente

            Considere também variações causadas pela transcrição:
            * naum tem mais
            * num tem mais
            * não tem mas
            * na um tem
            * acabou tudu
            ---
            ## NEGATIVA_SEM_CONSUMO
            Utilize quando o usuário informa que não utilizou o produto e que a quantidade continua integral.

            Exemplos:
            * não usei
            * não consumi
            * continua fechado
            * está fechado
            * está lacrado
            * nem abri
            * continua inteiro
            * continua cheio
            * não mexi
            * está intacto

            Também aceite pequenas distorções da transcrição.
            ---
            ## DIVERGENCIA_QUANTIDADE
            Utilize quando o usuário informa explicitamente uma quantidade física diferente da estimada.

            Exemplos:
            * tenho um
            * tenho duas unidades
            * restam três
            * sobrou meio litro
            * só tenho um litro
            * tenho quatro pacotes
            * restam cinco
            * sobraram duas caixas

            Sempre extraia a quantidade mencionada.

            Aceite:
            * números inteiros;
            * números decimais;
            * frações comuns ("meio litro" = 0.5);
            * quantidades escritas por extenso ("dois" = 2, "uma" = 1).

            Caso existam unidades de medida (litros, kg, pacotes, caixas etc.), ignore a unidade e extraia apenas o valor numérico.
            ---
            # REGRAS DE PRIORIDADE
            Quando houver ambiguidades, siga a seguinte ordem:
            1. Se houver uma quantidade explícita → DIVERGENCIA_QUANTIDADE.
            2. Caso contrário, se houver indicação clara de que acabou completamente → NEGATIVA_ZERADO.
            3. Caso contrário, se houver indicação de que nada foi consumido → NEGATIVA_SEM_CONSUMO.
            4. Caso contrário, se houver confirmação da estimativa → CONFIRMACAO.
            ---
            # EXTRAÇÃO DA QUANTIDADE
            Quando a intenção for DIVERGENCIA_QUANTIDADE:
            Converta para float.

            Exemplos:
            "1" → 1.0
            "2" → 2.0
            "2,5" → 2.5
            "2.5" → 2.5
            "meio" → 0.5
            "uma unidade" → 1.0
            "dois litros" → 2.0
            "três pacotes" → 3.0

            Caso nenhuma quantidade possa ser identificada com segurança, utilize:
            null
            ---
            # FORMATO DA RESPOSTA
            Retorne exclusivamente um JSON válido contendo exatamente as seguintes chaves:

            {{
            "intencao": "CONFIRMACAO | NEGATIVA_ZERADO | NEGATIVA_SEM_CONSUMO | DIVERGENCIA_QUANTIDADE",
            "quantidade_real": null ou float
            }}

            Não adicione nenhuma outra chave.
            Não escreva comentários.
            Não explique a decisão.
            Não utilize Markdown.
            Não utilize blocos de código.
            Retorne apenas o JSON puro.
            ---
            # TEXTO DO USUÁRIO
            {resposta_texto}
        """
        response = self.client.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt
        )
        
        try:
            texto_puro = response.text.strip().replace("```json", "").replace("```", "").strip()
            return json.loads(texto_puro)
        except Exception as e:
            logger.error("Falha ao fazer o parse do JSON da IA de intenção: %s", e)
            return {"intencao": "CONFIRMACAO", "quantidade_real": None}

    def verificar_itens_expirados_inicializacao(self):
        """Passo 1: Executado ao ligar o sistema. Varre apenas itens ativos que venceram a autonomia."""
        logger.info("Executando varredura preditiva de estoque...")
        
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
                pergunta = f"Felipe, notei que o tempo estimado para o seu estoque de {nome} acabou. O produto chegou ao fim?"
                self.voice.falar(pergunta)
                
                resposta_bruta = self.audio.capturar_audio_e_transcrever(ativar_trava_inicial=False)
                analise = self._classificar_resposta_usuario(resposta_bruta)
                intencao = str(analise.get("intencao", "")).upper().strip()
                
                data_atual_str = datetime.now().strftime("%Y-%m-%d")
                
                if intencao in ("CONFIRMACAO", "NEGATIVA_ZERADO") or "sim" in resposta_bruta.lower() or "acabou" in resposta_bruta.lower():
                    logger.info("%s confirmado como esgotado na inicialização. Atualizando colunas históricas.", nome)
                    novo_ritmo = max(1.0, dias_decorridos / estoque_antigo_total) if dias_decorridos > 0 else ritmo
                    
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
                    logger.info("%s ainda possui estoque segundo o usuário. Mantendo ativo temporariamente.", nome)
                    
    def processar_estoque_nova_compra(self, nome_produto: str, nova_quantidade: float) -> float:
        """Passo 2: Executado no momento da compra. Gerencia o estoque residual e as 4 vias de decisão."""
        query = """
            SELECT id, produto_nome, tempo_medio_calculado, data_ultima_compra, 
                   quantidade_comprada, quantidade_residual_confirmada, status_estoque 
            FROM controle_consumo 
            WHERE produto_nome = ?
        """
        item = self.db.executar_consulta_uma_linha(query, (nome_produto,))
        
        if not item:
            return 0.0

        id_item, _, ritmo, data_ultima, qtd_comprada, qtd_residual, status_estoque = item
        
        if status_estoque == 0:
            data_atual_str = datetime.now().strftime("%Y-%m-%d")
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
        resíduo_estimado = max(0.0, estoque_antigo_total - consumo_estimado)

        if resíduo_estimado < 0.1:
            data_atual_str = datetime.now().strftime("%Y-%m-%d")
            self.db.executar_comando(
                """UPDATE controle_consumo 
                   SET data_ultima_compra = ?, quantidade_comprada = ?, quantidade_residual_confirmada = 0.0, 
                       status_estoque = 1, ultima_qtd_comprada = ? 
                   WHERE id = ?""",
                (data_atual_str, nova_quantidade, nova_quantidade, id_item)
            )
            return 0.0

        pergunta = (
            f"Pelo que consta, você deve possuir ainda cerca de {resíduo_estimado:.1f} unidades ou litros de {nome_produto} em estoque. "
            f"Confirma que possui essa quantidade?"
        )
        self.voice.falar(pergunta)
        
        resposta_bruta = self.audio.capturar_audio_e_transcrever(ativar_trava_inicial=False)
        
        analise = self._classificar_resposta_usuario(resposta_bruta)
        intencao = analise.get("intencao")
        qtd_real = analise.get("quantidade_real")
        
        data_atual_str = datetime.now().strftime("%Y-%m-%d")

        # Tratamento seguro para strings de intenção
        intencao_tratada = str(intencao).upper().strip() if intencao else ""

        # --- ÁRVORE DE DECISÃO MULTIFLEXÍVEL ATUALIZADA ---
        if intencao_tratada == "DIVERGENCIA_QUANTIDADE" and qtd_real is not None:
            logger.info("Cenário: DIVERGENCIA_QUANTIDADE. Ajustando resíduo para %s unidades reais.", qtd_real)
            
            consumo_real = estoque_antigo_total - qtd_real
            if consumo_real > 0 and dias_decorridos > 0:
                ritmo = max(1.0, dias_decorridos / consumo_real)
            
            self.db.executar_comando(
                """UPDATE controle_consumo 
                   SET tempo_medio_calculado = ?, data_ultima_compra = ?, quantidade_comprada = ?, 
                       quantidade_residual_confirmada = ?, status_estoque = 1, ultima_qtd_comprada = ? 
                   WHERE id = ?""",
                (ritmo, data_atual_str, nova_quantidade, float(qtd_real), nova_quantidade, id_item)
            )
            return float(qtd_real)

        elif intencao_tratada == "CONFIRMACAO":
            logger.info("Cenário: CONFIRMACAO. Somando resíduo estimado à nova compra.")
            self.db.executar_comando(
                """UPDATE controle_consumo 
                   SET data_ultima_compra = ?, quantidade_comprada = ?, quantidade_residual_confirmada = ?, 
                       status_estoque = 1, ultima_qtd_comprada = ? 
                   WHERE id = ?""",
                (data_atual_str, nova_quantidade, resíduo_estimado, nova_quantidade, id_item)
            )
            return resíduo_estimado

        elif intencao_tratada == "NEGATIVA_ZERADO" or "não" in resposta_bruta.lower() or "acabou" in resposta_bruta.lower():
            logger.info("Cenário: NEGATIVA_ZERADO. Estoque antigo estava esgotado no momento desta nova compra. Zerando resíduo e iniciando ciclo com a nova quantidade.")
            
            novo_ritmo = max(1.0, dias_decorridos / estoque_antigo_total) if dias_decorridos > 0 else ritmo
            
            self.db.executar_comando(
                """UPDATE controle_consumo 
                   SET tempo_medio_calculado = ?, 
                       data_ultima_compra = ?, 
                       quantidade_comprada = ?, 
                       quantidade_residual_confirmada = 0.0, 
                       status_estoque = 1, 
                       validacao_pendente = 0,
                       ultima_qtd_comprada = ?, 
                       quantidade_residual_esgotada = ? 
                   WHERE id = ?""",
                (novo_ritmo, data_atual_str, nova_quantidade, qtd_comprada, resíduo_estimado, id_item)
            )
            return 0.0

        elif intencao_tratada == "NEGATIVA_SEM_CONSUMO":
            logger.info("Cenário: NEGATIVA_SEM_CONSUMO. Mantém estoque antigo intacto.")
            resíduo_real = estoque_antigo_total
            self.db.executar_comando(
                """UPDATE controle_consumo 
                   SET data_ultima_compra = ?, quantidade_comprada = ?, quantidade_residual_confirmada = ?, 
                       status_estoque = 1, ultima_qtd_comprada = ? 
                   WHERE id = ?""",
                (data_atual_str, nova_quantidade, resíduo_real, nova_quantidade, id_item)
            )
            return resíduo_real

        # Fallback de segurança definitivo
        else:
            logger.warning("Intenção ignorada ou desconhecida. Aplicando Fallback para CONFIRMACAO.")
            self.db.executar_comando(
                """UPDATE controle_consumo 
                   SET data_ultima_compra = ?, quantidade_comprada = ?, quantidade_residual_confirmada = ?, 
                       status_estoque = 1, ultima_qtd_comprada = ? 
                   WHERE id = ?""",
                (data_atual_str, nova_quantidade, resíduo_estimado, nova_quantidade, id_item)
            )
            return resíduo_estimado

    def registrar_fim_estoque_direto(self, nome_produto: str) -> bool:
        """
        Zera o estoque de um produto voluntariamente pelo usuário sem abrir questionamentos.
        Muda o status do estoque para 0, preparando-o para a lista de compras.
        """
        query = "SELECT id, quantidade_comprada, quantidade_residual_confirmada, tempo_medio_calculado, data_ultima_compra FROM controle_consumo WHERE produto_nome = ?"
        item = self.db.executar_consulta_uma_linha(query, (nome_produto,))
        
        if not item:
            logger.warning("Produto '%s' não localizado no banco para baixa direta.", nome_produto)
            return False
            
        id_item, qtd_comprada, qtd_residual, ritmo, data_ultima = item
        data_atual_str = datetime.now().strftime("%Y-%m-%d")
        
        dias_decorridos = self._calcular_dias_decorridos(data_ultima)
        estoque_antigo_total = qtd_comprada + qtd_residual
        if dias_decorridos > 0 and estoque_antigo_total > 0:
            ritmo = max(1.0, dias_decorridos / estoque_antigo_total)

        logger.info("Baixa direta voluntária processada para: '%s'. Modificando tabelas de auditoria.", nome_produto)
        
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
            (ritmo, qtd_comprada, qtd_residual, data_atual_str, id_item)
        )
        
        self.voice.falar(f"Entendido, Felipe. Já registrei que o seu estoque de {nome_produto} acabou por completo.")
        return True