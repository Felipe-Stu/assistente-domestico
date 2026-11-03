"""
Skill ProjectAnalyzer — Analista de Projetos e Documentação Técnica (100% local).

Python faz a leitura, extração, indexação e documentação; o LLM local (Ollama)
apenas interpreta e redige a partir dos fatos extraídos. A Skill é somente-leitura
sobre o projeto analisado e escreve exclusivamente na pasta de saída configurada.
"""

from services.project_analyzer.command_parser import detectar_comando_projeto
from services.project_analyzer.project_analyzer import ProjectAnalyzer, ProjetoInvalidoError, VERSAO_SKILL

__all__ = ["ProjectAnalyzer", "ProjetoInvalidoError", "detectar_comando_projeto", "VERSAO_SKILL"]
