"""
Roteiro da skill programacao (SKP): Claude como principal, Qwen local como reserva.

1. Busca na biblioteca os trechos da documentação mais próximos da pergunta.
2. Tenta o Claude, se o núcleo o entregou (só acontece para skills autorizadas em CLAUDE_SKILLS).
3. Sem Claude (sem chave, sem cota, fora do ar), responde com o Qwen local e diz o motivo.
"""
from core.skills import obter_catalogo
from core.skills.motor import Resposta
from services.biblioteca_service import bloco_de_contexto
from services.claude_service import ClaudeIndisponivelError


def executar(ctx, texto, decisao):
    servicos = ctx.servicos
    biblioteca = servicos.get("biblioteca")
    trechos = biblioteca.buscar(texto) if biblioteca is not None else []
    prompt = obter_catalogo().skill("programacao").prompt("sistema") + bloco_de_contexto(trechos)
    historico = servicos.get("historico") or []

    motivo = None
    claude = servicos.get("claude")
    if claude is not None and claude.configurado():
        try:
            return Resposta(claude.gerar_texto(prompt, texto, historico))
        except ClaudeIndisponivelError as erro:
            motivo = erro.motivo

    local = ctx.servico("llm_programacao")
    resposta = ctx.repetir(local.gerar_texto, (prompt, texto, historico),
                           mensagem_espera_voz="Processando sua solicitação localmente.",
                           nome_servico="Qwen-Programacao")
    if motivo:
        resposta += f"\n\n_(Respondido pelo Qwen local: {motivo}.)_"
    return Resposta(resposta, fala=resposta.split("\n", 1)[0])
