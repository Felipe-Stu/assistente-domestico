"""
Interpretação e redação com o LLM local.

O LLM nunca recebe código bruto: recebe apenas os fatos já extraídos pelo Python
(nomes, assinaturas, docstrings curtas, dependências), sempre com segredos ocultados
e limitados a `max_caracteres` por chamada. Grupos grandes são resumidos em etapas
(resumos intermediários) antes da síntese final.

Tudo o que vem do LLM é classificado como INFERIDO pela documentação.
"""
import logging
from typing import Any, Callable, Dict, List, Optional

from services.project_analyzer.redactor import ocultar_segredos

logger = logging.getLogger(__name__)

PROMPT_MODULO = """Você é um analista de software. Descreva a responsabilidade de UM arquivo de código.
Use SOMENTE os dados fornecidos. Não invente funcionalidades. Se os dados não bastarem, use "NÃO IDENTIFICADO".
Responda em português do Brasil. Retorne SOMENTE JSON válido, sem Markdown.

Esquema:
{"responsabilidade": string (1 a 2 frases), "observacoes": [string] (0 a 3 itens curtos)}

Exemplo:
Entrada: arquivo services/db_service.py; classe DatabaseService (métodos: get_connection, salvar_compra); integrações: SQLite
Saída: {"responsabilidade": "Centraliza o acesso ao banco SQLite e a persistência de compras.", "observacoes": ["Concentra SQL e conexão na mesma classe."]}"""

PROMPT_GRUPO = """Você é um arquiteto de software. Resuma o papel conjunto do grupo de arquivos abaixo.
Use SOMENTE os dados fornecidos. Responda em português do Brasil. Retorne SOMENTE JSON válido.

Esquema:
{"resumo": string (até 3 frases)}"""

PROMPT_ARQUITETURA = """Você é um arquiteto de software. A partir dos dados extraídos de um projeto, descreva a arquitetura.
Use SOMENTE os dados fornecidos. Não invente componentes. Se algo não puder ser determinado, escreva "NÃO IDENTIFICADO".
Responda em português do Brasil. Retorne SOMENTE JSON válido, sem Markdown.

Esquema:
{"visao_geral": string (até 4 frases),
 "padroes": [string] (padrões de arquitetura observados, até 5),
 "fluxo_principal": string (sequência do ponto de entrada até a resposta, até 4 frases),
 "decisoes": [string] (decisões arquiteturais evidentes nos dados, até 5)}"""


def _limitar(texto: Any, limite: int) -> str:
    texto = " ".join(str(texto or "").split())
    return texto if len(texto) <= limite else texto[: limite - 3] + "..."


class ResumidorLLM:
    """
    `provedor`: objeto com gerar_json(prompt_sistema, mensagem_usuario) (ex.: LocalLLMProvider).
    Após `max_falhas_seguidas` falhas o LLM é considerado indisponível (evita esperar
    o timeout de cada arquivo) e a documentação segue apenas com dados determinísticos.
    """

    def __init__(self, provedor: Any, max_caracteres: int = 6000, max_falhas_seguidas: int = 2,
                 log: Optional[Callable[[str], None]] = None):
        self.provedor = provedor
        self.max_caracteres = max_caracteres
        self.max_falhas_seguidas = max_falhas_seguidas
        self.falhas_seguidas = 0
        self.chamadas = 0
        self.falhas = 0
        self.log = log or (lambda m: None)

    @property
    def disponivel(self) -> bool:
        return self.provedor is not None and self.falhas_seguidas < self.max_falhas_seguidas

    def _chamar(self, prompt: str, mensagem: str) -> Optional[Dict[str, Any]]:
        if not self.disponivel:
            return None
        mensagem, _ = ocultar_segredos(mensagem[: self.max_caracteres])
        self.chamadas += 1
        try:
            resposta = self.provedor.gerar_json(prompt, mensagem)
            if not isinstance(resposta, dict):
                raise ValueError("resposta não é um objeto JSON")
            self.falhas_seguidas = 0
            return resposta
        except Exception as e:
            self.falhas += 1
            self.falhas_seguidas += 1
            self.log(f"[LLM] Falha na chamada ao modelo local: {e}")
            if not self.disponivel:
                self.log("[LLM] Modelo local considerado indisponível. Seguindo apenas com análise determinística.")
            return None

    # ------------------------------------------------------------------
    @staticmethod
    def descrever_fatos(fatos: Dict[str, Any], usado_por: List[str], depende_de: List[str]) -> str:
        partes = [f"arquivo {fatos['caminho']} ({fatos.get('linguagem')}, {fatos.get('linhas', 0)} linhas)"]
        if fatos.get("doc_modulo"):
            partes.append(f"docstring do módulo: {_limitar(fatos['doc_modulo'], 300)}")
        for c in fatos.get("classes", [])[:12]:
            metodos = ", ".join(c.get("metodos", [])[:25])
            doc = f" — {_limitar(c['doc'], 150)}" if c.get("doc") else ""
            partes.append(f"classe {c['nome']}({', '.join(c.get('bases', []))}) métodos: {metodos}{doc}")
        for fn in fatos.get("funcoes", [])[:25]:
            doc = f" — {_limitar(fn['doc'], 120)}" if fn.get("doc") else ""
            partes.append(f"função {fn['nome']}({', '.join(fn.get('argumentos', []))}){doc}")
        if fatos.get("integracoes"):
            partes.append("integrações: " + "; ".join(i["tipo"] for i in fatos["integracoes"]))
        if fatos.get("tabelas_sql"):
            partes.append("tabelas SQL: " + ", ".join(t["nome"] for t in fatos["tabelas_sql"]))
        if fatos.get("ipc"):
            partes.append("canais IPC: " + ", ".join(sorted({i["canal"] for i in fatos["ipc"]}))[:400])
        if depende_de:
            partes.append("depende de: " + ", ".join(depende_de[:15]))
        if usado_por:
            partes.append("usado por: " + ", ".join(usado_por[:15]))
        if fatos.get("ponto_de_entrada"):
            partes.append("possui bloco if __name__ == '__main__' (ponto de entrada)")
        return "\n".join(partes)

    def resumir_modulo(self, descricao: str) -> Optional[Dict[str, Any]]:
        dados = self._chamar(PROMPT_MODULO, descricao)
        if not dados:
            return None
        resp = _limitar(dados.get("responsabilidade", ""), 400)
        obs = [_limitar(o, 200) for o in (dados.get("observacoes") or []) if isinstance(o, str)][:3]
        if not resp:
            return None
        return {"responsabilidade": resp, "observacoes": obs}

    def resumir_arquitetura(self, linhas_modulos: List[str], contexto_projeto: str) -> Optional[Dict[str, Any]]:
        """Map-reduce: se a lista não cabe no limite, resume em grupos antes da síntese final."""
        if not self.disponivel:
            return None
        orcamento = self.max_caracteres - len(contexto_projeto) - 200
        blocos = self._agrupar(linhas_modulos, max(1000, orcamento))
        if len(blocos) > 1:
            resumos = []
            for i, bloco in enumerate(blocos, start=1):
                self.log(f"[LLM] Resumo intermediário {i}/{len(blocos)}...")
                dados = self._chamar(PROMPT_GRUPO, bloco)
                if dados and dados.get("resumo"):
                    resumos.append(f"- grupo {i}: {_limitar(dados['resumo'], 500)}")
            if not resumos:
                return None
            corpo = "\n".join(resumos)
        else:
            corpo = blocos[0] if blocos else ""

        dados = self._chamar(PROMPT_ARQUITETURA, f"{contexto_projeto}\n\nMÓDULOS:\n{corpo}")
        if not dados:
            return None

        def lista(chave: str, n: int) -> List[str]:
            return [_limitar(x, 300) for x in (dados.get(chave) or []) if isinstance(x, str)][:n]

        return {
            "visao_geral": _limitar(dados.get("visao_geral", ""), 800),
            "padroes": lista("padroes", 5),
            "fluxo_principal": _limitar(dados.get("fluxo_principal", ""), 800),
            "decisoes": lista("decisoes", 5),
        }

    @staticmethod
    def _agrupar(linhas: List[str], limite: int) -> List[str]:
        blocos, atual, tamanho = [], [], 0
        for linha in linhas:
            if atual and tamanho + len(linha) + 1 > limite:
                blocos.append("\n".join(atual))
                atual, tamanho = [], 0
            atual.append(linha[:limite])
            tamanho += len(linha) + 1
        if atual:
            blocos.append("\n".join(atual))
        return blocos

