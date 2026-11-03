"""
ProjectAnalyzer — Analista de Projetos e Documentação Técnica (fachada da Skill).

Fluxo:
 1. Varredura somente-leitura (scanner)               -> Python
 2. Extração de fatos por arquivo (extractors)        -> Python (incremental por hash)
 3. Grafo de dependências e integrações (mapper)      -> Python
 4. Verificações de consistência (checker)            -> Python
 5. Resumos por módulo e arquitetura (LLM local)      -> somente arquivos alterados
 6. Documentação Markdown (doc_writer)                -> apenas na pasta de saída
 7. Índice + histórico (index_cache)                  -> apenas na pasta de saída

Regras: nenhum arquivo do projeto é modificado; nenhum dado sai da máquina
(o único provedor de LLM usado é o local, injetado pelo runtime).
"""
import logging
import os
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, Optional

from services.project_analyzer import consistency_checker, extractors
from services.project_analyzer.dependency_mapper import MapaDependencias
from services.project_analyzer.doc_writer import EscritorSeguro, GeradorDocumentacao
from services.project_analyzer.index_cache import IndiceIncremental
from services.project_analyzer.llm_summarizer import ResumidorLLM
from services.project_analyzer.redactor import contem_segredo
from services.project_analyzer.scanner import ler_texto, varrer_projeto

logging_logger = logging.getLogger(__name__)

NOME_ASSISTENTE = "project_analyzer"
LINGUAGENS_RESUMIDAS = {"Python", "JavaScript", "TypeScript"}
VERSAO_SKILL = "1.0.0"


class ProjetoInvalidoError(Exception):
    """Diretório inexistente ou inválido para análise."""


def _slug(nome: str) -> str:
    s = re.sub(r"[^\w\-]+", "-", nome.strip(), flags=re.UNICODE).strip("-")
    return s or "projeto"


class ProjectAnalyzer:
    def __init__(
        self,
        llm_provider: Any = None,
        pasta_saida: Optional[str] = None,
        nome_modelo: str = "qwen2.5-coder:7b",
        preparar_modelo: Optional[Callable[[], None]] = None,
        liberar_modelo: Optional[Callable[[], None]] = None,
        progresso: Optional[Callable[[str], None]] = None,
        registrador: Any = None,
        max_caracteres_llm: int = 6000,
    ):
        """
        llm_provider: provedor LOCAL com gerar_json() (LocalLLMProvider). None = somente análise determinística.
        pasta_saida: única pasta onde a Skill escreve (uma subpasta por projeto).
        preparar_modelo / liberar_modelo: ganchos de VRAM (ex.: descarregar o Gemma antes do Qwen).
        progresso: callback para mensagens de andamento (ex.: debug_log do Electron).
        registrador: logger com log_assistente(nome, msg); padrão = custom_logger do projeto.
        """
        if pasta_saida is None:
            raise ValueError("pasta_saida é obrigatória (diretório de saída previamente definido).")
        self.llm_provider = llm_provider
        self.pasta_saida = str(Path(pasta_saida).resolve())
        self.nome_modelo = nome_modelo
        self.preparar_modelo = preparar_modelo
        self.liberar_modelo = liberar_modelo
        self._progresso = progresso
        self.max_caracteres_llm = max_caracteres_llm
        if registrador is None:
            from services.logger_service import logger as registrador
        self.registrador = registrador

    # ------------------------------------------------------------------
    def _log(self, msg: str) -> None:
        logging_logger.info(msg)
        try:
            self.registrador.log_assistente(NOME_ASSISTENTE, msg)
        except Exception:
            pass
        if self._progresso:
            try:
                self._progresso(msg)
            except Exception:
                pass

    def _pasta_projeto(self, raiz: Path) -> str:
        """Subpasta de saída do projeto; se o nome já pertence a outra raiz, acrescenta sufixo."""
        base = _slug(raiz.name)
        escritor = EscritorSeguro(self.pasta_saida)
        indice = escritor.resolver(f"{base}/.indice/indice.json")
        if indice.exists():
            anterior = IndiceIncremental._carregar(str(indice), {})
            if anterior.get("raiz") and os.path.normcase(anterior["raiz"]) != os.path.normcase(str(raiz)):
                import hashlib
                base = f"{base}-{hashlib.sha1(str(raiz).encode('utf-8')).hexdigest()[:6]}"
        return base

    # ------------------------------------------------------------------
    def analisar(self, caminho_projeto: str) -> Dict[str, Any]:
        inicio = time.time()
        raiz = Path(os.path.expanduser(caminho_projeto.strip().strip('"'))).resolve()
        if not raiz.exists() or not raiz.is_dir():
            raise ProjetoInvalidoError(f"Diretório não encontrado: {caminho_projeto}")
        saida_raiz = Path(self.pasta_saida)
        if saida_raiz == raiz or saida_raiz in raiz.parents:
            raise ProjetoInvalidoError("O projeto não pode estar dentro da pasta de saída da documentação.")

        nome_pasta = self._pasta_projeto(raiz)
        escritor = EscritorSeguro(os.path.join(self.pasta_saida, nome_pasta))
        self._log(f"Iniciando análise de '{raiz}'. Saída: {escritor.raiz}")

        # 1. Varredura (a pasta de saída é excluída caso esteja dentro do projeto)
        varredura = varrer_projeto(str(raiz), excluir=[self.pasta_saida])
        self._log(f"Varredura concluída: {len(varredura.arquivos)} arquivo(s).")

        # 2. Extração incremental
        indice = IndiceIncremental(str(escritor.resolver(".indice/indice.json")),
                                   str(escritor.resolver(".indice/historico.json")))
        fatos: Dict[str, Dict[str, Any]] = {}
        resumos: Dict[str, Dict[str, Any]] = {}
        segredos: Dict[str, int] = {}
        requirements, package_json = None, None
        alterados, reutilizados = [], 0

        for arq in varredura.arquivos_texto:
            anterior = indice.entrada_anterior(arq.caminho_relativo, arq.sha256)
            if anterior and anterior.get("fatos") is not None:
                f = anterior["fatos"]
                resumo = anterior.get("resumo")
                if resumo and resumo.get("modelo") == self.nome_modelo:
                    resumos[arq.caminho_relativo] = resumo
                else:
                    resumo = None
                reutilizados += 1
            else:
                texto = ler_texto(arq)
                f = extractors.extrair_fatos(arq.caminho_relativo, arq.linguagem, texto)
                f["segredos"] = contem_segredo(texto)
                base = os.path.basename(arq.caminho_relativo)
                if base == "requirements.txt":
                    f["requirements"] = extractors.extrair_requirements(texto)
                elif base == "package.json":
                    f["package_json"] = extractors.extrair_package_json(texto)
                resumo = None
                alterados.append(arq.caminho_relativo)
            fatos[arq.caminho_relativo] = f
            segredos[arq.caminho_relativo] = f.get("segredos", 0)
            if "requirements" in f and "/" not in arq.caminho_relativo:
                requirements = f["requirements"]
            if "package_json" in f and "/" not in arq.caminho_relativo:
                package_json = f["package_json"]
            indice.registrar(arq.caminho_relativo, arq.sha256, f, resumo)

        self._log(f"Extração: {len(alterados)} arquivo(s) analisado(s), {reutilizados} reaproveitado(s) do índice.")

        # 3-4. Dependências e consistência
        mapa = MapaDependencias(fatos, requirements=requirements, package_json=package_json)
        todos = [a.caminho_relativo for a in varredura.arquivos]
        achados = consistency_checker.verificar_projeto(fatos, mapa, todos, segredos)
        divergencias = consistency_checker.comparar_documentacao(fatos, todos)
        alteracoes = indice.calcular_alteracoes()

        # 5. LLM local (somente o que mudou)
        arquitetura = indice.arquitetura_anterior()
        if arquitetura and arquitetura.get("modelo") != self.nome_modelo:
            arquitetura = None
        houve_mudanca = bool(alterados) or bool(alteracoes["removidos"])
        resumidor = ResumidorLLM(self.llm_provider, max_caracteres=self.max_caracteres_llm, log=self._log) if self.llm_provider else None
        pendentes = [p for p, f in sorted(fatos.items()) if f.get("linguagem") in LINGUAGENS_RESUMIDAS
                     and p not in resumos and not f.get("erro_sintaxe")]
        precisa_llm = resumidor is not None and (pendentes or houve_mudanca or arquitetura is None)

        if precisa_llm:
            if self.preparar_modelo:
                try:
                    self.preparar_modelo()
                except Exception as e:
                    self._log(f"Aviso ao preparar o modelo local: {e}")
            try:
                for i, caminho in enumerate(pendentes, start=1):
                    if not resumidor.disponivel:
                        break
                    self._log(f"[LLM] Resumindo {i}/{len(pendentes)}: {caminho}")
                    descricao = resumidor.descrever_fatos(fatos[caminho], sorted(mapa.usado_por.get(caminho, [])),
                                                           sorted(mapa.arestas.get(caminho, [])))
                    r = resumidor.resumir_modulo(descricao)
                    if r:
                        r["modelo"] = self.nome_modelo
                        resumos[caminho] = r
                        indice.definir_resumo(caminho, r)
                if resumidor.disponivel and (houve_mudanca or arquitetura is None):
                    self._log("[LLM] Elaborando visão de arquitetura...")
                    linhas_mod = [f"- {p}: {resumos[p]['responsabilidade']}" if p in resumos else f"- {p}"
                                  for p in sorted(fatos) if fatos[p].get("linguagem") in LINGUAGENS_RESUMIDAS]
                    integ = sorted({i["tipo"] for f in fatos.values() for i in f.get("integracoes", [])})
                    contexto = (f"Projeto: {raiz.name}\nPontos de entrada: {', '.join(mapa.pontos_de_entrada()) or 'nenhum'}\n"
                                f"Integrações: {'; '.join(integ) or 'nenhuma'}\n"
                                f"Componentes centrais: {', '.join(c['arquivo'] for c in mapa.centrais())}")
                    nova = resumidor.resumir_arquitetura(linhas_mod, contexto)
                    if nova:
                        nova["modelo"] = self.nome_modelo
                        arquitetura = nova
            finally:
                if self.liberar_modelo:
                    try:
                        self.liberar_modelo()
                    except Exception as e:
                        self._log(f"Aviso ao liberar o modelo local: {e}")

        # A documentação contém interpretação do LLM (gerada agora ou reaproveitada do índice)?
        llm_ok = bool(resumos) or arquitetura is not None

        # 6-7. Índice, histórico e documentação
        estatisticas = {
            "arquivos_analisados": len(fatos),
            "linhas": sum(f.get("linhas", 0) for f in fatos.values()),
            "achados": len(achados),
        }
        historico = indice.salvar(str(raiz), arquitetura, alteracoes, estatisticas)
        contexto_docs = {
            "nome": raiz.name, "raiz": str(raiz), "data": datetime.now().strftime("%d/%m/%Y %H:%M"),
            "modelo": self.nome_modelo, "llm_disponivel": llm_ok, "varredura": varredura, "fatos": fatos,
            "mapa": mapa, "achados": achados, "divergencias": divergencias, "resumos": resumos,
            "arquitetura": arquitetura, "historico": historico, "alteracoes": alteracoes,
        }
        documentos = GeradorDocumentacao(escritor, contexto_docs).gerar_todos()

        duracao = round(time.time() - inicio, 1)
        self._log(f"Análise concluída em {duracao}s. {len(documentos)} documento(s) em {escritor.raiz}")
        return {
            "projeto": raiz.name,
            "raiz": str(raiz),
            "pasta_saida": str(escritor.raiz),
            "documentos": documentos,
            "arquivos": len(varredura.arquivos),
            "arquivos_analisados": len(fatos),
            "arquivos_reanalisados": len(alterados),
            "arquivos_reaproveitados": reutilizados,
            "alteracoes": alteracoes,
            "achados": len(achados),
            "achados_alta": sum(1 for a in achados if a["gravidade"] == "alta"),
            "llm_utilizado": llm_ok,
            "chamadas_llm": resumidor.chamadas if resumidor else 0,
            "duracao_s": duracao,
        }

    # ------------------------------------------------------------------
    @staticmethod
    def formatar_resposta(r: Dict[str, Any]) -> str:
        """Resposta curta para o chat/voz."""
        alt = r["alteracoes"]
        if alt["primeira_analise"]:
            mudancas = "primeira análise deste projeto"
        else:
            mudancas = (f"{len(alt['adicionados'])} novo(s), {len(alt['modificados'])} modificado(s), "
                        f"{len(alt['removidos'])} removido(s) desde a última análise")
        llm = "com interpretação do modelo local" if r["llm_utilizado"] else "sem o modelo local (apenas análise determinística)"
        return (f"Análise do projeto {r['projeto']} concluída em {r['duracao_s']}s, {llm}.\n"
                f"- Arquivos analisados: {r['arquivos_analisados']} ({mudancas})\n"
                f"- Problemas encontrados: {r['achados']} ({r['achados_alta']} de gravidade alta)\n"
                f"- Documentação: {r['pasta_saida']}")
