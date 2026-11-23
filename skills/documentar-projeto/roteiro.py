"""Roteiro da skill documentar-projeto: análise síncrona, 100% local (o chat espera até o fim)."""
import logging

from core.skills.motor import Resposta
from services.logger_service import logger as custom_logger
from services.project_analyzer import ProjectAnalyzer, ProjetoInvalidoError

logger = logging.getLogger(__name__)


def executar(ctx, texto, decisao):
    caminho = (decisao.get("parametros") or {}).get("caminho")
    if not caminho:
        return Resposta("Informe o caminho da pasta do projeto. Exemplo: analisar projeto E:\\MOBA")
    progresso = ctx.servicos.get("progresso")
    if progresso:
        progresso(f"ProjectAnalyzer: analisando '{caminho}'. Isso pode levar alguns minutos...")
    try:
        with custom_logger.etapa("analise_projeto"):
            resultado = ctx.servico("project_analyzer").analisar(caminho)
        resposta = ProjectAnalyzer.formatar_resposta(resultado)
    except ProjetoInvalidoError as e:
        resposta = f"Não foi possível analisar: {e}"
    except Exception as e:
        logger.error(f"Falha na análise de projeto: {e}")
        custom_logger.log_geral(f"[ProjectAnalyzer] Falha na análise de '{caminho}': {e}")
        resposta = f"A análise do projeto falhou: {e}"
    # Por voz, apenas a primeira linha (sem caminhos de pasta)
    return Resposta(resposta, fala=resposta.split("\n", 1)[0])
