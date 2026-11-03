"""
Executa a Skill ProjectAnalyzer sem a interface Electron.

Uso:
    python scripts/analyze_project.py "E:\\MOBA"
    python scripts/analyze_project.py "E:\\MOBA" --sem-llm
    python scripts/analyze_project.py "E:\\MOBA" --saida "E:\\Agente IA\\Documentacao_Gerada" --modelo qwen2.5-coder:7b

O LLM usado é sempre o local (Ollama). Nenhum dado é enviado para serviços externos.
"""
import argparse
import logging
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(ROOT_DIR))

from core.config import PROJECT_ANALYZER_MODEL, PROJECT_ANALYZER_OUTPUT_DIR  # noqa: E402
from services.project_analyzer import ProjectAnalyzer, ProjetoInvalidoError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="ProjectAnalyzer — análise e documentação local de projetos.")
    parser.add_argument("caminho", help="Diretório do projeto a analisar")
    parser.add_argument("--saida", default=str(PROJECT_ANALYZER_OUTPUT_DIR), help="Pasta de saída da documentação")
    parser.add_argument("--modelo", default=PROJECT_ANALYZER_MODEL, help="Modelo local do Ollama")
    parser.add_argument("--sem-llm", action="store_true", help="Somente análise determinística (sem Ollama)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.WARNING, format="%(levelname)s - %(message)s")

    provedor = None
    if not args.sem_llm:
        from services.llm_provider import LocalLLMProvider
        provedor = LocalLLMProvider(modelo=args.modelo, temperatura=0.1)

    analisador = ProjectAnalyzer(
        llm_provider=provedor,
        pasta_saida=args.saida,
        nome_modelo=args.modelo,
        progresso=lambda m: print(f"  {m}", flush=True),
    )
    try:
        resultado = analisador.analisar(args.caminho)
    except ProjetoInvalidoError as e:
        print(f"Erro: {e}")
        return 2
    print()
    print(ProjectAnalyzer.formatar_resposta(resultado))
    print(f"- Chamadas ao modelo local: {resultado['chamadas_llm']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
