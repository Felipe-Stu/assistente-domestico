from datetime import date, datetime, timedelta
import logging
import re
from typing import Dict, Any, List, Optional, Tuple

from services.esquemas import ESQUEMA_COMPRAS
from services.intent_router import normalizar_texto
from services.llm_provider import BaseLLMProvider
from services.logger_service import logger as custom_logger
from services.vector.vector_store_service import VectorStoreService, VectorDocument

# Logger do console (terminal)
logging_logger = logging.getLogger(__name__)

NOME_ASSISTENTE = "shopping_assistant"

UNIDADES_PESO_VOLUME = {"kg", "g", "grama", "gramas", "quilo", "quilos", "litro", "litros", "l", "ml"}
ESTABELECIMENTOS_INVALIDOS = {"", "nao informado", "nao identificado", "nome do estabelecimento"}
DIAS_SEMANA = {"segunda": 0, "terca": 1, "quarta": 2, "quinta": 3, "sexta": 4, "sabado": 5, "domingo": 6}
MESES = {
    "janeiro": 1, "fevereiro": 2, "marco": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11, "dezembro": 12
}

_RE_PRECO_POR_UNIDADE = re.compile(r"\b(?:o|por|ao|cada|a)\s+(?:kg|quilo|kilo|litro|l)\b|/\s*(?:kg|l)\b|\bcada\b")
_RE_DATA_VAGA = re.compile(r"\b(?:semana passada|semana retrasada|mes passado|outro dia|dias atras)\b")


def _formatar_moeda(valor: float) -> str:
    return f"R$ {valor:.2f}".replace(".", ",")


def _formatar_numero(valor: float) -> str:
    return f"{valor:g}".replace(".", ",")


def _formatar_data(data_iso: str) -> str:
    try:
        return datetime.strptime(data_iso, "%Y-%m-%d").strftime("%d/%m/%Y")
    except (ValueError, TypeError):
        return str(data_iso)


def _para_float(valor: Any) -> Optional[float]:
    try:
        return float(valor) if valor is not None else None
    except (ValueError, TypeError):
        return None


class ShoppingAssistant:
    def __init__(
        self, 
        db_service: Any, 
        ai_service: Any = None, 
        llm_provider: Optional[BaseLLMProvider] = None,
        vector_store: Optional[VectorStoreService] = None
    ):
        """
        Inicializa o assistente de compras com suporte a SQLite e Banco Vetorial (ChromaDB).
        """
        self.db_service = db_service
        self.ai_service = ai_service
        self.llm_provider = llm_provider or ai_service
        self.vector_store = vector_store or VectorStoreService()
        # Último registro desta sessão: limita o "desfazer" ao que acabou de ser gravado
        self._ultimo_registro: List[Tuple[int, int]] = []

        if not self.llm_provider:
            logging_logger.warning(
                "ShoppingAssistant inicializado sem 'llm_provider' ou 'ai_service' válido!"
            )

        custom_logger.log_assistente(
            NOME_ASSISTENTE, 
            "Inicialização do assistente de compras (com vetorização integrada) concluída com sucesso."
        )

    def _validar_e_sanitizar_compra(self, dados_compra: dict) -> dict:
        """
        Valida e higieniza os valores numéricos dos itens da compra para evitar divisões por zero
        e assegurar a consistência dos dados financeiros antes de salvar no banco.
        """
        dados_validados = dados_compra.copy()
        itens = dados_validados.get("itens", [])
        itens_validados = []
        valor_total_calculado_compra = 0.0

        for item in itens:
            if not isinstance(item, dict):
                continue
            item_validado = item.copy()

            produto = str(item_validado.get("produto") or "").strip()
            if not produto:
                continue
            item_validado["produto"] = produto

            quantidade = item_validado.get("quantidade")
            valor_unitario = item_validado.get("valor_unitario")
            valor_total = item_validado.get("valor_total")

            try:
                quantidade = float(quantidade) if quantidade is not None else 0.0
            except (ValueError, TypeError):
                quantidade = 0.0

            try:
                valor_unitario = float(valor_unitario) if valor_unitario is not None else 0.0
            except (ValueError, TypeError):
                valor_unitario = 0.0

            try:
                valor_total = float(valor_total) if valor_total is not None else 0.0
            except (ValueError, TypeError):
                valor_total = 0.0

            if quantidade <= 0:
                if valor_total > 0 and valor_unitario > 0:
                    quantidade = valor_total / valor_unitario
                else:
                    quantidade = 1.0

            if valor_unitario <= 0:
                if valor_total > 0 and quantidade > 0:
                    valor_unitario = valor_total / quantidade
                else:
                    valor_unitario = 0.0

            if valor_total <= 0:
                if quantidade > 0 and valor_unitario > 0:
                    valor_total = quantidade * valor_unitario
                else:
                    valor_total = 0.0

            # Divergência não é corrigida aqui: o usuário confirma os valores em _avaliar_duvidas
            item_validado["total_divergente"] = abs(valor_total - (quantidade * valor_unitario)) > 0.05
            item_validado["quantidade"] = quantidade
            item_validado["valor_unitario"] = round(valor_unitario, 2)
            item_validado["valor_total"] = round(valor_total, 2)

            embalagem_quantidade = _para_float(item_validado.get("embalagem_quantidade"))
            embalagem_unidade = item_validado.get("embalagem_unidade")
            if embalagem_quantidade and embalagem_quantidade > 0 and embalagem_unidade:
                item_validado["embalagem_quantidade"] = embalagem_quantidade
                item_validado["embalagem_unidade"] = str(embalagem_unidade).strip()
            else:
                item_validado["embalagem_quantidade"] = None
                item_validado["embalagem_unidade"] = None

            valor_total_calculado_compra += valor_total
            itens_validados.append(item_validado)

        dados_validados["itens"] = itens_validados
        dados_validados["valor_total_compra"] = round(valor_total_calculado_compra, 2)
        return dados_validados

    def _resolver_data(self, texto: str, hoje: Optional[date] = None) -> Tuple[str, Optional[str]]:
        """
        Calcula a data da compra a partir do texto, sem depender do LLM.
        Retorna (data ISO, motivo de dúvida ou None).
        """
        hoje = hoje or datetime.now().date()
        t = normalizar_texto(texto)
        candidatas = set()

        if re.search(r"\banteontem\b", t):
            candidatas.add(hoje - timedelta(days=2))
        if re.search(r"\bontem\b", t):
            candidatas.add(hoje - timedelta(days=1))
        if re.search(r"\bhoje\b", t):
            candidatas.add(hoje)
        for m in re.finditer(r"\bha (\d{1,2}) dias\b", t):
            candidatas.add(hoje - timedelta(days=int(m.group(1))))

        padrao_semana = r"\b(?:na|no|nesta|neste|nessa|nesse)\s+(?:ultim[ao]\s+)?(" + "|".join(DIAS_SEMANA) + r")\b"
        for m in re.finditer(padrao_semana, t):
            dias = (hoje.weekday() - DIAS_SEMANA[m.group(1)]) % 7 or 7
            candidatas.add(hoje - timedelta(days=dias))

        duvida = "Data não compreendida." if _RE_DATA_VAGA.search(t) else None

        def adicionar(ano: int, mes: int, dia: int) -> None:
            nonlocal duvida
            try:
                data = date(ano, mes, dia)
                # Sem ano explícito, uma data futura pertence ao ano anterior
                candidatas.add(date(ano - 1, mes, dia) if data > hoje else data)
            except ValueError:
                duvida = "Data não compreendida."

        padrao_barra = r"\b(\d{1,2})/(\d{1,2})(?:/(\d{4}))?\b(?!\s*(?:kg|quilo|kilo|g\b|grama|litro|l\b|ml\b))"
        for m in re.finditer(padrao_barra, t):
            dia, mes, ano = int(m.group(1)), int(m.group(2)), m.group(3)
            adicionar(int(ano) if ano else hoje.year, mes, dia)

        padrao_mes = r"\bdia (\d{1,2}) de (" + "|".join(MESES) + r")\b"
        for m in re.finditer(padrao_mes, t):
            adicionar(hoje.year, MESES[m.group(2)], int(m.group(1)))

        if not re.search(padrao_mes, t):
            for m in re.finditer(r"\bdia (\d{1,2})\b", t):
                dia = int(m.group(1))
                # "dia 28" dito no dia 3 refere-se ao mês anterior
                ano, mes = hoje.year, hoje.month
                if dia > hoje.day:
                    ano, mes = (ano - 1, 12) if mes == 1 else (ano, mes - 1)
                adicionar(ano, mes, dia)

        if len(candidatas) > 1:
            duvida = "Mais de uma data foi mencionada."
        data = candidatas.pop() if len(candidatas) == 1 else hoje
        return data.strftime("%Y-%m-%d"), duvida

    @staticmethod
    def _localizar_preco(valor: float, texto: str) -> Optional[re.Match]:
        """Localiza um valor no texto, aceitando vírgula ou ponto e centavos opcionais."""
        centavos = round(valor * 100)
        reais, resto = centavos // 100, centavos % 100
        if resto == 0:
            padrao = rf"{reais}(?:[.,]00?)?"
        elif resto % 10 == 0:
            padrao = rf"{reais}[.,]{resto // 10}0?"
        else:
            padrao = rf"{reais}[.,]{resto:02d}"
        return re.search(rf"(?<![\d.,]){padrao}(?![\d])", texto)

    def _preco_por_unidade_ambiguo(self, item: Dict[str, Any], texto: str) -> bool:
        """Detecta peso ou volume com preço que pode ser da embalagem, não do quilo ou litro."""
        if normalizar_texto(str(item.get("unidade") or "")) not in UNIDADES_PESO_VOLUME:
            return False
        t = normalizar_texto(texto)
        m = self._localizar_preco(item["valor_unitario"], t)
        if m is None or (item["valor_total"] > 0 and self._localizar_preco(item["valor_total"], t)):
            return False
        vizinhanca = t[max(0, m.start() - 15):min(len(t), m.end() + 20)]
        return _RE_PRECO_POR_UNIDADE.search(vizinhanca) is None

    def _avaliar_duvidas(self, compras: List[Dict[str, Any]], texto: str, duvida_data: Optional[str]) -> List[str]:
        """Lista os motivos que exigem a confirmação do usuário antes de gravar."""
        duvidas = [duvida_data] if duvida_data else []

        for compra in compras:
            estabelecimento = normalizar_texto(str(compra.get("estabelecimento") or ""))
            if estabelecimento in ESTABELECIMENTOS_INVALIDOS:
                duvidas.append("Mercado não informado.")
            if compra.get("valor_total_compra", 0) <= 0:
                duvidas.append("Compra com total zero.")

            for item in compra.get("itens", []):
                produto = item.get("produto")
                if item.get("valor_unitario", 0) <= 0 and item.get("valor_total", 0) <= 0:
                    duvidas.append(f"{produto}: preço não informado.")
                elif item.get("total_divergente"):
                    duvidas.append(f"{produto}: total diferente de quantidade × preço.")
                elif self._preco_por_unidade_ambiguo(item, texto):
                    duvidas.append(f"{produto}: não ficou claro se o preço é por {item.get('unidade')} ou da embalagem.")

        return list(dict.fromkeys(duvidas))

    @staticmethod
    def formatar_resumo(compras: List[Dict[str, Any]]) -> str:
        """Resumo legível das compras para confirmação no chat."""
        linhas = []
        for compra in compras:
            linhas.append(
                f"{compra.get('estabelecimento') or 'Não informado'}, {_formatar_data(compra.get('data_compra'))}, "
                f"total {_formatar_moeda(compra.get('valor_total_compra', 0.0))}"
            )
            for item in compra.get("itens", []):
                marca = item.get("marca") or ""
                nome = item["produto"]
                if marca and marca.lower() not in nome.lower():
                    nome = f"{nome} {marca}"
                if item.get("embalagem_quantidade"):
                    nome = f"{nome} ({_formatar_numero(item['embalagem_quantidade'])} {item['embalagem_unidade']})"
                linhas.append(
                    f"- {nome}: {_formatar_numero(item['quantidade'])} {item.get('unidade') or 'un'} × "
                    f"{_formatar_moeda(item['valor_unitario'])} = {_formatar_moeda(item['valor_total'])}"
                )
        return "\n".join(linhas)

    def preparar_compra(self, texto_transcrito: str) -> Dict[str, Any]:
        """
        Gera o prompt especializado em parsing de compras (multi-mercados), solicita a
        estruturação ao llm_provider e valida o resultado. Não grava nada: pode ser
        repetida com segurança pelo retry.
        Retorna {"compras": [...], "duvidas": [...]}.
        """
        custom_logger.log_assistente(NOME_ASSISTENTE, f"Áudio recebido: '{custom_logger.conteudo(texto_transcrito)}'")

        if not self.llm_provider:
            logging_logger.error("Nenhum provedor de LLM configurado para processar a compra.")
            return {"compras": [], "duvidas": []}

        data_atual = datetime.now().strftime("%Y-%m-%d")

        prompt_sistema = f"""
        Você é um extrator de dados de compras em formato JSON rigoroso.
        Sua única tarefa é converter a transcrição de voz fornecida pelo usuário em um JSON válido.

        ### REGRAS CRÍTICAS DE SAÍDA:
        1. Responda APENAS com o JSON. 
        2. NÃO use blocos de código (NÃO use ```json ou ```).
        3. NÃO inclua nenhum texto de apresentação, explicação ou comentário antes ou depois do JSON.

        ---

        ### REGRAS DE CONVERSÃO E CÁLCULO:

        1. QUANTIDADES COMPOSTAS (PESOS E VOLUMES):
        - Some quilos e gramas em um único valor decimal em quilos (kg).
            * Exemplo: "3 kg 124 g" ou "3 kg e 124 g" -> quantidade: 3.124, unidade: "kg"
            * Exemplo: "106 gramas" ou "106 g" -> quantidade: 0.106, unidade: "kg"
            * Exemplo: "484 g" -> quantidade: 0.484, unidade: "kg"
        - Some litros e mililitros em um único valor decimal em litros (litro).
            * Exemplo: "1 litro e 250 ml" -> quantidade: 1.25, unidade: "litro"

        2. PREÇOS E CÁLCULOS:
        - valor_unitario: O preço por unidade (kg, litro, un, pacote).
        - valor_total (item): Arredonde para 2 casas decimais -> quantidade * valor_unitario
        - valor_total_compra: Soma dos valores totais dos itens do estabelecimento.

        3. EMBALAGENS:
        - Só use unidade "kg" ou "litro" quando o preço for por quilo ou por litro ("o quilo", "por kg", "o litro").
        - Se o preço for de um pacote, caixa, garrafa ou fardo, use quantidade = número de embalagens e unidade = "un".
        - Nesse caso, informe o conteúdo em embalagem_quantidade e embalagem_unidade.
            * Exemplo: "um pacote de arroz de 5 kg por 27,90" -> quantidade: 1.0, unidade: "un", valor_unitario: 27.90, valor_total: 27.90, embalagem_quantidade: 5.0, embalagem_unidade: "kg"
        - Sem conteúdo informado, embalagem_quantidade e embalagem_unidade -> null

        4. VALORES PADRÃO (QUANDO NÃO INFORMADO):
        - marca -> null
        - estabelecimento -> "Não informado" (se nenhum for dito)
        - data_compra -> "{data_atual}"

        ---

        ### EXEMPLOS DE CONVERSÃO (Siga este padrão estritamente):

        ENTRADA:
        "eu fui ao mercado Moreschi e comprei peito de frango por r$ 16,99 o quilo comprei 3 kg 124 G comprei também detergente Minuano por r$ 2,69 e alho 27,99 o quilo eu comprei 106 gramas"

        SAÍDA:
        {{
        "compras": [
            {{
            "estabelecimento": "Moreschi",
            "data_compra": "{data_atual}",
            "itens": [
                {{
                "produto": "peito de frango",
                "marca": null,
                "quantidade": 3.124,
                "unidade": "kg",
                "valor_unitario": 16.99,
                "valor_total": 53.08,
                "categoria": "carne"
                }},
                {{
                "produto": "detergente",
                "marca": "Minuano",
                "quantidade": 1.0,
                "unidade": "un",
                "valor_unitario": 2.69,
                "valor_total": 2.69,
                "categoria": "limpeza"
                }},
                {{
                "produto": "alho",
                "marca": null,
                "quantidade": 0.106,
                "unidade": "kg",
                "valor_unitario": 27.99,
                "valor_total": 2.97,
                "categoria": "hortifruti"
                }}
            ],
            "valor_total_compra": 58.74
            }}
        ]
        }}

        ---

        ### FORMATO FINAL OBRIGATÓRIO:

        {{
        "compras": [
            {{
            "estabelecimento": "Nome do Estabelecimento",
            "data_compra": "{data_atual}",
            "itens": [
                {{
                "produto": "nome do produto",
                "marca": null,
                "quantidade": 1.0,
                "unidade": "un",
                "valor_unitario": 0.0,
                "valor_total": 0.0,
                "categoria": "categoria",
                "embalagem_quantidade": null,
                "embalagem_unidade": null
                }}
            ],
            "valor_total_compra": 0.0
            }}
        ]
        }}
        """

        logging_logger.info("Enviando texto de compras para estruturação via LLMProvider...")
        custom_logger.log_assistente(NOME_ASSISTENTE, "Solicitando extração de compras em JSON ao LLMProvider.")

        # Solicita a estrutura JSON através do provedor de LLM configurado (Local ou Nuvem)
        resposta_json = self.llm_provider.gerar_json(
            prompt_sistema=prompt_sistema,
            mensagem_usuario=texto_transcrito,
            esquema=ESQUEMA_COMPRAS
        )
        custom_logger.log_assistente(NOME_ASSISTENTE, "Estrutura JSON retornada pelo LLMProvider com sucesso.")

        listagem_compras = []
        if isinstance(resposta_json, dict):
            listagem_compras = resposta_json.get("compras", [resposta_json])
        elif isinstance(resposta_json, list):
            listagem_compras = resposta_json

        data_compra, duvida_data = self._resolver_data(texto_transcrito)

        compras_validadas = []
        for dados_compra in listagem_compras:
            if not isinstance(dados_compra, dict):
                continue
            dados_validados = self._validar_e_sanitizar_compra(dados_compra)
            if not dados_validados.get("itens"):
                continue
            dados_validados["data_compra"] = data_compra
            compras_validadas.append(dados_validados)

        duvidas = self._avaliar_duvidas(compras_validadas, texto_transcrito, duvida_data)
        custom_logger.log_assistente(
            NOME_ASSISTENTE,
            f"Compras preparadas: {len(compras_validadas)}. Dúvidas: {duvidas or 'nenhuma'}."
        )
        return {"compras": compras_validadas, "duvidas": duvidas}

    def registrar_compras(self, compras: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Grava as compras em uma única transação e vetoriza os itens. Não deve ser repetida."""
        compra_ids = self.db_service.salvar_compras_da_ia(compras)

        for compra_id, dados_validados in zip(compra_ids, compras):
            logging_logger.info("Compra gravada com sucesso pelo ShoppingAssistant! ID: %s", compra_id)
            self._vetorizar_compra(compra_id, dados_validados)

        self._ultimo_registro = [
            (compra_id, len(compra.get("itens", []))) for compra_id, compra in zip(compra_ids, compras)
        ]
        custom_logger.log_assistente(NOME_ASSISTENTE, f"Dados de processamento: {len(compra_ids)} compras salvas com sucesso.")

        linhas = [
            f"{compra.get('estabelecimento') or 'Não informado'}: {len(compra.get('itens', []))} item(ns), "
            f"total {_formatar_moeda(compra.get('valor_total_compra', 0.0))}, em {_formatar_data(compra.get('data_compra'))}"
            for compra in compras
        ]
        return {
            "status": "sucesso",
            "mensagem": "\n".join(["Compra registrada."] + [f"- {linha}" for linha in linhas]),
            "compras_processadas": len(compra_ids)
        }

    def _vetorizar_compra(self, compra_id: int, dados_validados: Dict[str, Any]) -> None:
        """Vetorização automática dos itens gravados no ChromaDB; falhas não afetam o registro."""
        try:
            data_c = dados_validados.get("data_compra") or datetime.now().strftime("%Y-%m-%d")
            comercio_c = dados_validados.get("estabelecimento") or "Não informado"
            docs_vetoriais = []

            for idx, item in enumerate(dados_validados.get("itens", []), 1):
                prod = item.get("produto") or "produto"
                marca = item.get("marca")
                marca_str = f" da marca {marca}" if marca else ""
                qtd = item.get("quantidade", 1.0)
                unid = item.get("unidade") or "un"
                v_tot = item.get("valor_total", 0.0)
                v_unit = item.get("valor_unitario", 0.0)
                cat = item.get("categoria") or "geral"

                texto_item = (
                    f"Compra de {qtd} {unid} de {prod}{marca_str} no estabelecimento {comercio_c} "
                    f"por R$ {v_tot:.2f} (R$ {v_unit:.2f}/{unid}) na data {data_c}. Categoria: {cat}."
                )

                doc_id = f"purchase_item_live_{compra_id}_{idx}"
                meta = {
                    "assistant": "compras",
                    "category": str(cat).lower(),
                    "entity_type": "purchase_item",
                    "compra_id": compra_id,
                    "produto": str(prod).lower(),
                    "estabelecimento": str(comercio_c).lower(),
                    "created_at": data_c,
                    "source": "live_purchase"
                }
                docs_vetoriais.append(VectorDocument(id=doc_id, content=texto_item, metadata=meta))

            if docs_vetoriais:
                self.vector_store.upsert_documents(docs_vetoriais)
                logging_logger.info(f"Vetorização de {len(docs_vetoriais)} itens da compra ID {compra_id} concluída no ChromaDB.")
        except Exception as e_vec:
            logging_logger.error(f"Erro ao vetorizar itens da compra ID {compra_id} no ChromaDB: {e_vec}")
            custom_logger.log_assistente(NOME_ASSISTENTE, f"Alerta ao vetorizar compra no ChromaDB: {e_vec}")

    def desfazer_ultimo_registro(self) -> str:
        """Remove do SQLite e do ChromaDB o último registro feito nesta sessão."""
        if not self._ultimo_registro:
            return "Não há compra registrada nesta sessão para desfazer."

        compra_ids = [compra_id for compra_id, _ in self._ultimo_registro]
        itens_ids = self.db_service.remover_compras(compra_ids)

        ids_vetoriais = [f"purchase_item_{item_id}" for item_id in itens_ids]
        for compra_id, qtd_itens in self._ultimo_registro:
            ids_vetoriais.extend(f"purchase_item_live_{compra_id}_{idx}" for idx in range(1, qtd_itens + 1))
        try:
            self.vector_store.delete_documents(ids_vetoriais)
        except Exception as e_vec:
            logging_logger.error(f"Erro ao remover vetores das compras {compra_ids}: {e_vec}")
            custom_logger.log_assistente(NOME_ASSISTENTE, f"Alerta ao remover vetores das compras: {e_vec}")

        self._ultimo_registro = []
        return f"Última compra desfeita: {len(compra_ids)} registro(s) e {len(itens_ids)} item(ns) removidos."
