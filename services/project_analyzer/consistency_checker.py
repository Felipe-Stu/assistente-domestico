"""
Verificações determinísticas de consistência e possíveis problemas.

Cada achado informa: gravidade, categoria, mensagem, confiabilidade
(CONFIRMADO / INFERIDO) e evidências (arquivo:linha).
"""
import posixpath
from collections import defaultdict
from typing import Any, Dict, List

from services.project_analyzer.dependency_mapper import MapaDependencias

CONFIRMADO = "CONFIRMADO"
INFERIDO = "INFERIDO"
NAO_IDENTIFICADO = "NÃO IDENTIFICADO"

LIMITE_ARQUIVO_GRANDE = 800  # linhas


def _achado(gravidade: str, categoria: str, mensagem: str, confiabilidade: str, evidencias: List[str]) -> Dict[str, Any]:
    return {"gravidade": gravidade, "categoria": categoria, "mensagem": mensagem,
            "confiabilidade": confiabilidade, "evidencias": evidencias}


def verificar_projeto(fatos: Dict[str, Dict[str, Any]], mapa: MapaDependencias,
                      todos_arquivos: List[str], segredos_por_arquivo: Dict[str, int]) -> List[Dict[str, Any]]:
    achados: List[Dict[str, Any]] = []
    nomes_arquivos = set(todos_arquivos)

    # 1. Erros de sintaxe
    for caminho, f in sorted(fatos.items()):
        if f.get("erro_sintaxe"):
            e = f["erro_sintaxe"]
            achados.append(_achado("alta", "Erro de sintaxe", f"Arquivo Python não pôde ser analisado: {e['mensagem']}.",
                                   CONFIRMADO, [f"{caminho}:{e['linha']}"]))

    # 2. Dependências importadas e não declaradas
    for dep in mapa.nao_declaradas():
        evid = [f"{u['arquivo']}:{u['linha']}" for u in dep["usos"][:5]]
        achados.append(_achado("media", "Dependência não declarada",
                               f"'{dep['pacote']}' é importado no código, mas não consta em {dep['manifesto']}.",
                               CONFIRMADO, evid))

    # 3. Dependências declaradas sem import direto
    for dep in mapa.declaradas_sem_uso():
        local = f"{dep['origem']}:{dep['linha']}" if dep.get("linha") else dep["origem"]
        if dep.get("nota"):
            msg = f"'{dep['pacote']}' está declarado e não é importado diretamente; provável uso indireto ({dep['nota']})."
            achados.append(_achado("baixa", "Dependência sem uso direto", msg, INFERIDO, [local]))
        else:
            msg = f"'{dep['pacote']}' está declarado, mas nenhum import correspondente foi encontrado."
            achados.append(_achado("baixa", "Dependência sem uso direto", msg, INFERIDO, [local]))

    # 4. Imports internos que não resolvem para nenhum arquivo
    for item in mapa.internos_nao_resolvidos:
        achados.append(_achado("alta", "Import interno inexistente",
                               f"'{item['modulo']}' parece interno, mas nenhum arquivo correspondente foi encontrado.",
                               INFERIDO, [f"{item['arquivo']}:{item['linha']}"]))

    # 5. Imports exclusivos do Windows
    for item in mapa.imports_windows:
        achados.append(_achado("media", "Portabilidade", f"Import exclusivo do Windows: '{item['modulo']}'.",
                               CONFIRMADO, [f"{item['arquivo']}:{item['linha']}"]))

    # 6. Código duplicado (corpo idêntico em funções/métodos com 4+ instruções)
    por_hash = defaultdict(list)
    for caminho, f in fatos.items():
        for h in f.get("hashes_corpo", []):
            por_hash[h["hash"]].append((caminho, h["nome"], h["linha"]))
    for ocorrencias in por_hash.values():
        if len(ocorrencias) > 1:
            nomes = ", ".join(sorted({n for _, n, _ in ocorrencias}))
            achados.append(_achado("media", "Código duplicado", f"Corpo idêntico em {len(ocorrencias)} locais ({nomes}).",
                                   CONFIRMADO, [f"{c}:{l}" for c, _, l in sorted(ocorrencias)]))

    # 7. Funções de mesmo nome em arquivos diferentes (possível duplicação de responsabilidade)
    por_nome = defaultdict(list)
    for caminho, f in fatos.items():
        if f.get("linguagem") != "Python":
            continue
        # Funções de módulo + métodos utilitários (sanitizar/validar/parse) costumam ser duplicados
        for fn in f.get("funcoes", []):
            if not fn["nome"].startswith("__"):
                por_nome[fn["nome"]].append(f"{caminho}:{fn['linha']}")
        for cls in f.get("classes", []):
            for m in cls.get("metodos", []):
                if m.startswith(("_sanitizar", "_validar", "_parse")):
                    por_nome[m].append(f"{caminho}:{cls['linha']} ({cls['nome']})")
    ignorar = {"main", "run", "setup", "teardown"}
    for nome, locais in sorted(por_nome.items()):
        arquivos_distintos = {l.split(":")[0] for l in locais}
        if len(arquivos_distintos) > 1 and nome not in ignorar:
            achados.append(_achado("baixa", "Possível duplicação",
                                   f"'{nome}' está definido em {len(arquivos_distintos)} arquivos diferentes.",
                                   INFERIDO, locais[:6]))

    # 8. Arquivos de configuração com nome incorreto
    for caminho in sorted(nomes_arquivos):
        base = posixpath.basename(caminho)
        if base in (".gitignore.txt", ".env.txt", ".gitattributes.txt"):
            correto = base[:-4]
            if posixpath.join(posixpath.dirname(caminho), correto) not in nomes_arquivos:
                achados.append(_achado("alta", "Configuração ignorada",
                                       f"'{base}' não é reconhecido pelas ferramentas; o nome esperado é '{correto}'.",
                                       CONFIRMADO, [caminho]))

    # 9. Possíveis segredos em texto (somente a contagem; o valor nunca é exibido)
    for caminho, qtd in sorted(segredos_por_arquivo.items()):
        if qtd:
            achados.append(_achado("alta", "Possível segredo exposto",
                                   f"{qtd} possível(is) credencial(is) em texto. O conteúdo foi ocultado nesta documentação.",
                                   INFERIDO, [caminho]))

    # 10. Arquivos muito grandes
    for caminho, f in sorted(fatos.items()):
        if f.get("linguagem") in ("Python", "JavaScript", "TypeScript") and f.get("linhas", 0) > LIMITE_ARQUIVO_GRANDE:
            achados.append(_achado("baixa", "Complexidade",
                                   f"Arquivo com {f['linhas']} linhas; pode concentrar responsabilidades demais.",
                                   INFERIDO, [caminho]))

    ordem = {"alta": 0, "media": 1, "baixa": 2}
    achados.sort(key=lambda a: (ordem[a["gravidade"]], a["categoria"], a["evidencias"][0] if a["evidencias"] else ""))
    return achados


def comparar_documentacao(fatos: Dict[str, Dict[str, Any]], todos_arquivos: List[str]) -> Dict[str, Any]:
    """
    Compara a documentação Markdown existente no projeto com a implementação:
    - arquivos citados na documentação que não existem;
    - módulos de código que não são citados em nenhum documento.
    """
    docs = {c: f for c, f in fatos.items() if f.get("linguagem") == "Markdown"}
    nomes_base = defaultdict(set)
    for c in todos_arquivos:
        nomes_base[posixpath.basename(c)].add(c)

    referencias_quebradas = []
    citados = set()
    for doc, f in sorted(docs.items()):
        for ref in f.get("referencias_arquivos", []):
            arquivo = ref["arquivo"].lstrip("./")
            base = posixpath.basename(arquivo)
            existe = arquivo in todos_arquivos or base in nomes_base
            if existe:
                citados.update(nomes_base.get(base, set()))
                citados.add(arquivo)
            else:
                referencias_quebradas.append({"documento": doc, "arquivo": ref["arquivo"], "linha": ref["linha"]})

    codigo = [c for c, f in fatos.items() if f.get("linguagem") in ("Python", "JavaScript", "TypeScript")
              and not c.endswith("__init__.py")]
    nao_documentados = sorted(c for c in codigo if c not in citados)

    return {
        "documentos": sorted(docs.keys()),
        "referencias_quebradas": referencias_quebradas,
        "nao_documentados": nao_documentados if docs else [],
    }
