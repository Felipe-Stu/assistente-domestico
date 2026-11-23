"""Roteiro da skill {{nome}}."""
from core.skills.motor import Resposta


def executar(ctx, texto, decisao):
    """
    ctx.servico("llm_local")  -> modelo local residente (gerar_json com esquema / gerar_texto)
    ctx.servico("db_service") -> SQLite do assistente (executar_comando / executar_consulta)
    ctx.repetir(func, args)   -> política de repetição do núcleo (Ollama fora é fatal)
    decisao["acao"]           -> criar | consultar | corrigir | delegar
    """
    return Resposta("A skill {{nome}} ainda não faz nada.")
