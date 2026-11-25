"""
Compras fictícias no banco real, para testar consultas e o painel com volume (lojas reais, valores inventados).

    python scripts/compras_ficticias.py inserir [--meses 9] [--semente 11]
    python scripts/compras_ficticias.py remover
    python scripts/compras_ficticias.py contar

Todas ficam ligadas a uma entrada com canal "ficticia", então saem de uma vez com "remover"
(o estoque perde o que elas somaram). Faça uma cópia do banco antes (backups/ ou fazer_backup.py).
"""
import random
import sys
from datetime import date, timedelta
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

CANAL = "ficticia"

# (produto, categoria, preço, vendido por kg)
LOJAS = {
    "Irmãos Muffato": [
        ("arroz tipo 1 5kg", "mercearia", 26.9, False), ("feijão carioca 1kg", "mercearia", 8.79, False),
        ("macarrão espaguete 500g", "mercearia", 4.49, False), ("molho de tomate 340g", "mercearia", 3.29, False),
        ("café torrado 500g", "mercearia", 18.9, False), ("leite integral 1L", "laticinios", 4.89, False),
        ("queijo muçarela fatiado 200g", "laticinios", 11.9, False), ("iogurte natural 170g", "laticinios", 3.49, False),
        ("manteiga 200g", "laticinios", 12.9, False), ("presunto fatiado 200g", "laticinios", 8.9, False),
        ("pão de forma", "padaria", 9.49, False), ("banana prata", "hortifruti", 6.99, True), ("tomate", "hortifruti", 8.99, True),
        ("batata", "hortifruti", 5.99, True), ("alface crespa", "hortifruti", 3.49, False), ("maçã gala", "hortifruti", 11.9, True),
        ("refrigerante coca-cola 2L", "bebidas", 10.99, False), ("suco de uva integral 1L", "bebidas", 14.9, False),
        ("detergente 500ml", "limpeza", 2.79, False), ("amaciante 2L", "limpeza", 17.9, False),
        ("sabonete 85g", "higiene", 2.49, False), ("creme dental 90g", "higiene", 5.99, False),
        ("ração para gatos 1kg", "pet", 32.9, False), ("chocolate ao leite 90g", "doces_lanches", 6.49, False),
    ],
    "Moreschi": [
        ("peito de frango", "carnes", 19.9, True), ("coxa e sobrecoxa de frango", "carnes", 12.9, True),
        ("patinho moído", "carnes", 44.9, True), ("contra-filé bovino", "carnes", 54.9, True), ("picanha bovina", "carnes", 79.9, True),
        ("costelinha suína", "carnes", 27.9, True), ("lombo suíno", "carnes", 24.9, True), ("linguiça toscana", "carnes", 21.9, True),
        ("filé de tilápia", "carnes", 49.9, True), ("cebola", "hortifruti", 5.49, True), ("alho", "hortifruti", 29.9, True),
        ("limão taiti", "hortifruti", 6.99, True), ("detergente 500ml", "limpeza", 2.69, False), ("chiclete", "doces_lanches", 3.49, False),
        ("cerveja lata 350ml", "bebidas", 4.29, False),
    ],
    "Max Atacadista": [
        ("arroz tipo 1 5kg", "mercearia", 23.9, False), ("óleo de soja 900ml", "mercearia", 6.99, False),
        ("açúcar refinado 5kg", "mercearia", 21.9, False), ("papel higiênico 12 rolos", "higiene", 19.9, False),
        ("sabão em pó 1,6kg", "limpeza", 24.9, False), ("água sanitária 2L", "limpeza", 6.49, False),
        ("refrigerante guaraná 2L", "bebidas", 7.49, False), ("cerveja lata 350ml", "bebidas", 3.69, False),
        ("água mineral 1,5L", "bebidas", 2.29, False), ("chips elma", "doces_lanches", 5.99, False),
        ("petiscos para gatos whiskas", "pet", 3.79, False), ("areia para gatos 4kg", "pet", 22.9, False),
    ],
    "Engenho Santo Mário": [("pastel", "alimentacao_fora", 11.0, False), ("caldo de cana 500ml", "alimentacao_fora", 9.0, False),
                            ("coca-cola lata", "bebidas", 6.0, False)],
    "Costela de Chão": [("almoço (costela de chão)", "alimentacao_fora", 75.0, False), ("refrigerante lata", "bebidas", 7.0, False)],
}
# loja: (dias entre visitas, itens por visita)
ROTINA = {"Irmãos Muffato": (7, (4, 9)), "Moreschi": (10, (2, 5)), "Max Atacadista": (30, (5, 9)),
          "Engenho Santo Mário": (21, (1, 3)), "Costela de Chão": (45, (1, 2))}


def gerar(meses: int = 9, semente: int = 11, hoje=None):
    aleatorio = random.Random(semente)
    hoje = hoje or date.today()
    ano, mes = hoje.year, hoje.month - (meses - 1)
    while mes <= 0:
        ano, mes = ano - 1, mes + 12
    inicio = date(ano, mes, 1)
    compras = []
    for loja, (cada, (minimo, maximo)) in ROTINA.items():
        dia = inicio + timedelta(days=aleatorio.randint(0, cada - 1))
        while dia <= hoje:
            catalogo = LOJAS[loja]
            itens = []
            for nome, categoria, preco, por_kg in aleatorio.sample(catalogo, k=min(len(catalogo), aleatorio.randint(minimo, maximo))):
                qtd = round(aleatorio.uniform(0.4, 2.2), 3) if por_kg else aleatorio.choice([1, 1, 1, 2, 2, 3, 4])
                if loja == "Max Atacadista" and "cerveja" in nome:
                    qtd = 12
                unitario = round(preco * aleatorio.uniform(0.93, 1.07), 2)
                itens.append({"produto": nome, "quantidade": qtd, "unidade": "kg" if por_kg else "un",
                              "valor_unitario": unitario, "valor_total": round(qtd * unitario, 2), "categoria": categoria})
            compras.append({"estabelecimento": loja, "data_compra": dia.isoformat(), "itens": itens,
                            "valor_total_compra": round(sum(i["valor_total"] for i in itens), 2)})
            dia += timedelta(days=max(2, cada + aleatorio.randint(-3, 3)))
    return sorted(compras, key=lambda c: c["data_compra"])


def _ids(db):
    return [linha[0] for linha in db.executar_consulta(
        "SELECT c.id FROM compras c JOIN entradas e ON e.id = c.entrada_id WHERE e.canal = ?", (CANAL,))]


def main(argv) -> int:
    from services.db_service import DatabaseService
    from services.dinheiro import formatar_reais
    if not argv or argv[0] not in ("inserir", "remover", "contar"):
        print(__doc__)
        return 1
    db = DatabaseService()
    existentes = _ids(db)
    if argv[0] == "contar":
        print(f"{len(existentes)} compras fictícias no banco.")
        return 0
    if argv[0] == "remover":
        db.remover_compras(existentes)
        print(f"{len(existentes)} compras fictícias removidas.")
        return 0
    if existentes:
        print(f"Já há {len(existentes)} compras fictícias. Rode 'remover' antes de inserir de novo.")
        return 1
    meses = int(argv[argv.index("--meses") + 1]) if "--meses" in argv else 9
    semente = int(argv[argv.index("--semente") + 1]) if "--semente" in argv else 11
    compras = gerar(meses, semente)
    db.salvar_compras_da_ia(compras, entrada={"tipo": "compra", "canal": CANAL, "versao_prompt": "ficticia-v1",
                                              "texto": f"Compras fictícias para testar consultas e painel ({meses} meses, semente {semente})"})
    print(f"{len(compras)} compras fictícias inseridas, total {formatar_reais(sum(c['valor_total_compra'] for c in compras))}.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
