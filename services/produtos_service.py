"""
Catálogo de produtos e categorias fechadas (M07).

- Categorias: lista fechada (CATEGORIAS). O esquema de saída do modelo só aceita estes valores, e o
  código converte valores antigos ou livres ("carne", "guloseima", "passeios") pelo SINONIMOS; o que
  não se encaixa vira "outros".
- Produtos: tabela `produtos` com um nome por produto (`chave` normalizada: sem acentos, sem tamanho
  de embalagem, singular/plural tratados). Produto novo é cadastrado sozinho, com a categoria que veio
  da compra; cada item de compra aponta para ele (`itens_compra.produto_id`).

É a base das consultas por categoria (M19) e do estoque (M06): "leite", "Leite 1L" e "leites" são o
mesmo produto.
"""
import re
import sqlite3
import unicodedata
from datetime import datetime
from typing import Optional

CATEGORIAS = {
    "hortifruti": "Hortifrúti",
    "carnes": "Carnes e peixes",
    "laticinios": "Laticínios e frios",
    "padaria": "Padaria",
    "mercearia": "Mercearia",
    "bebidas": "Bebidas",
    "doces_lanches": "Doces e lanches",
    "limpeza": "Limpeza",
    "higiene": "Higiene pessoal",
    "pet": "Pet",
    "farmacia": "Farmácia",
    "casa": "Casa e utensílios",
    "alimentacao_fora": "Alimentação fora de casa",
    "lazer": "Lazer",
    "outros": "Outros",
}

# Valores livres que o modelo (ou o banco antigo) costuma usar → categoria fechada
SINONIMOS = {
    "frutas": "hortifruti", "verduras": "hortifruti", "legumes": "hortifruti", "hortalicas": "hortifruti", "feira": "hortifruti",
    "carne": "carnes", "acougue": "carnes", "frango": "carnes", "peixe": "carnes", "peixaria": "carnes", "aves": "carnes",
    "laticinio": "laticinios", "frios": "laticinios", "queijos": "laticinios", "leite": "laticinios",
    "paes": "padaria", "pao": "padaria", "confeitaria": "doces_lanches",
    "alimentacao": "mercearia", "alimentos": "mercearia", "graos": "mercearia", "massas": "mercearia",
    "enlatados": "mercearia", "temperos": "mercearia", "geral": "mercearia", "mercado": "mercearia",
    "bebida": "bebidas", "refrigerante": "bebidas", "sucos": "bebidas", "cerveja": "bebidas",
    "doces": "doces_lanches", "guloseima": "doces_lanches", "guloseimas": "doces_lanches", "lanche": "doces_lanches",
    "lanches": "doces_lanches", "salgadinhos": "doces_lanches", "snacks": "doces_lanches", "biscoitos": "doces_lanches",
    "produtos de limpeza": "limpeza", "lavanderia": "limpeza",
    "higiene pessoal": "higiene", "cuidados pessoais": "higiene", "perfumaria": "higiene", "beleza": "higiene",
    "petshop": "pet", "pet shop": "pet", "animais": "pet", "racao": "pet",
    "remedios": "farmacia", "remedio": "farmacia", "medicamentos": "farmacia", "saude": "farmacia", "drogaria": "farmacia",
    "utensilios": "casa", "utilidades": "casa", "casa e utensilios": "casa", "eletronicos": "casa", "papelaria": "casa",
    "restaurante": "alimentacao_fora", "delivery": "alimentacao_fora", "refeicao": "alimentacao_fora",
    "alimentacao fora de casa": "alimentacao_fora", "lanchonete": "alimentacao_fora",
    "passeios": "lazer", "passeio": "lazer", "cinema": "lazer", "entretenimento": "lazer", "viagem": "lazer",
}

# Palavras do nome do produto que definem a categoria (usadas quando a categoria dada é livre ou "outros")
PALAVRAS_PRODUTO = (
    (r"\b(chocolates?|bombo(m|ns)|balas?|chicletes?|chips|salgadinhos?|biscoitos?|bolachas?|sorvetes?|pirulitos?)\b", "doces_lanches"),
    (r"\b(almoco|jantar|refeicao|marmita|pizza|restaurante|lanchonete|ifood)\b", "alimentacao_fora"),
    (r"\b(racao|areia (de|para) gato|petiscos? (de|para) (gatos?|caes|cachorros?))\b", "pet"),
    (r"\b(remedios?|dipirona|paracetamol|vitaminas?)\b", "farmacia"),
    (r"\b(sabonetes?|shampoo|pasta de dentes?|creme dental|papel higienico|desodorantes?)\b", "higiene"),
    (r"\b(detergentes?|sabao|amaciante|desinfetante|agua sanitaria|esponjas?)\b", "limpeza"),
)


def categoria_pelo_nome(nome: str) -> Optional[str]:
    texto = _sem_acentos(nome)
    for padrao, categoria in PALAVRAS_PRODUTO:
        if re.search(padrao, texto):
            return categoria
    return None


def inferir_categoria(nome: str, categoria, nome_primeiro: bool = False) -> str:
    """Categoria fechada de um item.

    nome_primeiro=False (compras novas): vale a categoria dada; o nome só decide se ela for "outros".
    nome_primeiro=True (migração de dados antigos): o nome decide antes, porque a categoria antiga era livre.
    """
    pelo_nome = categoria_pelo_nome(nome)
    dada = normalizar_categoria(categoria)
    if nome_primeiro and pelo_nome:
        return pelo_nome
    return pelo_nome if dada == "outros" and pelo_nome else dada


TABELA_PRODUTOS = """
CREATE TABLE IF NOT EXISTS produtos (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    nome TEXT NOT NULL,              -- como aparece (primeira vez que foi comprado)
    chave TEXT NOT NULL UNIQUE,      -- nome normalizado, usado para reconhecer o mesmo produto
    categoria TEXT NOT NULL,         -- uma das CATEGORIAS
    unidade_padrao TEXT,             -- unidade da primeira compra (kg, litro, un)
    criado_em TEXT NOT NULL
)
"""

_RE_TAMANHO = re.compile(
    r"\b\d+(?:[.,]\d+)?\s*(?:ml|l|lt|lts|litro|litros|g|gr|grama|gramas|kg|quilo|quilos|un|und|unidade|unidades)\b")


def _sem_acentos(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto or "")
    return "".join(c for c in texto if not unicodedata.combining(c)).lower()


def normalizar_categoria(valor) -> str:
    """Qualquer valor → uma das CATEGORIAS (ou 'outros')."""
    texto = " ".join(re.sub(r"[^a-z0-9]+", " ", _sem_acentos(str(valor or ""))).split())
    if texto.replace(" ", "_") in CATEGORIAS:
        return texto.replace(" ", "_")
    if texto in SINONIMOS:
        return SINONIMOS[texto]
    for rotulo_slug, rotulo in CATEGORIAS.items():
        if texto == " ".join(re.sub(r"[^a-z0-9]+", " ", _sem_acentos(rotulo)).split()):
            return rotulo_slug
    return "outros"


def chave_produto(nome: str) -> str:
    """'Coca-Cola 2L' → 'coca cola'; 'Pães franceses' → 'paes franceses'."""
    texto = _RE_TAMANHO.sub(" ", _sem_acentos(nome))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", texto).split())


def _variantes(chave: str):
    """A própria chave e a forma com ou sem 's' no fim de cada palavra (plural simples)."""
    palavras = chave.split()
    yield chave
    yield " ".join(p[:-1] if len(p) > 3 and p.endswith("s") else p for p in palavras)
    yield " ".join(p + "s" if not p.endswith("s") else p for p in palavras)


def resolver_produto(cursor: sqlite3.Cursor, nome: str, categoria: str, unidade: Optional[str] = None,
                     nome_primeiro: bool = False) -> Optional[int]:
    """Id do produto no catálogo; cadastra se for novo. Roda na transação do cursor recebido."""
    chave = chave_produto(nome)
    if not chave:
        return None
    for variante in dict.fromkeys(_variantes(chave)):
        cursor.execute("SELECT id FROM produtos WHERE chave = ?", (variante,))
        linha = cursor.fetchone()
        if linha:
            return linha[0]
    cursor.execute(
        "INSERT INTO produtos (nome, chave, categoria, unidade_padrao, criado_em) VALUES (?, ?, ?, ?, ?)",
        (" ".join(str(nome).split()).lower(), chave, inferir_categoria(nome, categoria, nome_primeiro), unidade,
         datetime.now().isoformat(timespec="seconds")),
    )
    return cursor.lastrowid
