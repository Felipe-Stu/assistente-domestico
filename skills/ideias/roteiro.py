"""
Roteiro da skill ideias: salvar, listar e consultar ideias de projetos.

A análise pelo Claude acontece em segundo plano no IdeiasService (serviço `ideias`); este roteiro só
salva, lista e responde. Consultas sobre uma ideia são respondidas pelo modelo local com a análise salva.
"""
import re

from core.skills import obter_catalogo
from core.skills.motor import Resposta
from services.ideias_service import limpar_prefixo, parece_pergunta, pede_para_salvar

_RE_NUMERO = re.compile(r"#\s*\d+|\bideia\s+\d+\b", re.IGNORECASE)
_RE_LISTA = re.compile(r"\bminhas ideias\b|\bquais (?:sao |são )?(?:as )?(?:minhas )?ideias\b", re.IGNORECASE)
# Consulta só quando o pedido se refere a uma ideia SALVA; pedir sugestões ou ideias ao assistente é conversa (P23)
_RE_REFERENCIA = re.compile(
    r"\bminhas? ideias?\b|#\s*\d+|\bideia\s+\d+\b|\b(?:que|qual|quais) (?:eu )?(?:salvei|guardei|anotei|mandei)\b"
    r"|\bideias? (?:salvas?|guardadas?|anotadas?)\b|\b(?:a|essa|esta|daquela|da|na) ideia d[oae]s?\b|\bessa ideia\b",
    re.IGNORECASE,
)
CONVERSA = "conversa-geral"


def limpar(texto: str) -> str:
    return limpar_prefixo(texto)


def _criar(ctx, texto):
    if not pede_para_salvar(texto) and parece_pergunta(texto):
        return Resposta("", encaminhar=CONVERSA)  # P23: pedido ao assistente, não ideia para guardar
    ideias = ctx.servico("ideias")
    conteudo = limpar(texto)
    if len(conteudo) < 12:
        return Resposta("Qual é a ideia? Pode contar com o máximo de detalhes que lembrar.", pendencia={"etapa": "texto"})
    return Resposta(ideias.confirmacao(ideias.salvar(conteudo, "chat")))


def _consultar(ctx, texto):
    if not _RE_REFERENCIA.search(texto):
        return Resposta("", encaminhar=CONVERSA)  # P23: "me dê ideias de..." não fala de uma ideia salva
    ideias = ctx.servico("ideias")
    if _RE_LISTA.search(texto) and not _RE_NUMERO.search(texto):
        return Resposta(ideias.resumo_lista(), fala="Listei suas ideias no chat.")
    ideia = ideias.buscar(texto)
    if ideia is None:
        return Resposta("Não encontrei essa ideia. " + ideias.resumo_lista())
    if ideia["situacao"] != "analisada" or _RE_NUMERO.search(texto) and len(texto.split()) <= 4:
        return Resposta(ideias.detalhe(ideia), fala=f"Mostrei a ideia {ideia['id']} no chat.")
    prompt = obter_catalogo().skill("ideias").prompt("consulta", id=str(ideia["id"]), titulo=ideia["titulo"],
                                                     conteudo=ideia["analise"])
    return Resposta(ctx.servico("llm_local").gerar_texto(prompt, texto))


def executar(ctx, texto, decisao):
    if decisao.get("acao") == "criar":
        return _criar(ctx, texto)
    return _consultar(ctx, texto)


def responder_pendencia(ctx, texto, dados):
    ideias = ctx.servico("ideias")
    if len(texto.strip()) < 3:
        return Resposta("Tudo bem, não salvei nada.")
    return Resposta(ideias.confirmacao(ideias.salvar(texto.strip(), "chat")))
