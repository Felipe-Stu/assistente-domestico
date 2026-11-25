"""
I07: cria o banco do modo demonstração com compras fictícias (lojas e valores inventados).

    criar-demo.bat   (ou: set ASSISTENTE_DEMO=1 && python scripts/criar_demo.py [--recriar])

Tudo fica em core/database/demo/ (fora do Git); o banco real não é tocado.
"""
import os
import random
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

os.environ["ASSISTENTE_DEMO"] = "1"   # antes de importar a configuração
RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from core import config  # noqa: E402

LOJAS = {
    "Mercado Bom Preço": [("arroz 5kg", "mercearia", 24.9), ("feijão carioca 1kg", "mercearia", 8.49), ("leite integral 1L", "laticinios", 4.79),
                          ("café 500g", "mercearia", 17.9), ("detergente 500ml", "limpeza", 2.69), ("papel higiênico 12un", "higiene", 19.9),
                          ("refrigerante 2L", "bebidas", 8.99), ("queijo muçarela 300g", "laticinios", 15.9), ("biscoito recheado", "doces_lanches", 3.49)],
    "Hortifrúti Vila Verde": [("banana prata kg", "hortifruti", 6.99), ("tomate kg", "hortifruti", 8.49), ("alface", "hortifruti", 3.5),
                              ("batata kg", "hortifruti", 5.99), ("maçã gala kg", "hortifruti", 10.9)],
    "Açougue Boi Bom": [("contrafilé kg", "carnes", 49.9), ("frango inteiro kg", "carnes", 13.9), ("linguiça toscana kg", "carnes", 22.9)],
    "Padaria Pão Quente": [("pão francês kg", "padaria", 16.9), ("bolo de fubá", "padaria", 18.0), ("café coado", "alimentacao_fora", 6.0)],
    "Farmácia Saúde Já": [("dipirona 10cp", "farmacia", 9.9), ("protetor solar", "higiene", 49.9), ("escova de dentes", "higiene", 12.9)],
    "Pet Amigo": [("ração gato 3kg", "pet", 79.9), ("areia de gato 4kg", "pet", 24.9)],
}
FREQUENCIA = {"Mercado Bom Preço": 7, "Hortifrúti Vila Verde": 5, "Açougue Boi Bom": 10, "Padaria Pão Quente": 3,
              "Farmácia Saúde Já": 20, "Pet Amigo": 30}


def compras_ficticias(meses: int = 6, semente: int = 7, hoje=None):
    aleatorio = random.Random(semente)
    hoje = hoje or date.today()
    inicio = hoje - timedelta(days=30 * meses)
    compras = []
    for loja, cada in FREQUENCIA.items():
        dia = inicio + timedelta(days=aleatorio.randint(0, cada))
        while dia <= hoje:
            itens = []
            for nome, categoria, preco in aleatorio.sample(LOJAS[loja], k=min(len(LOJAS[loja]), aleatorio.randint(1, 4))):
                qtd = aleatorio.choice([1, 1, 1, 2, 3]) if not nome.endswith(" kg") else round(aleatorio.uniform(0.4, 2.5), 3)
                unitario = round(preco * aleatorio.uniform(0.92, 1.08), 2)
                itens.append({"produto": nome, "quantidade": qtd, "unidade": "kg" if nome.endswith(" kg") else "un",
                              "valor_unitario": unitario, "valor_total": round(qtd * unitario, 2), "categoria": categoria})
            compras.append({"estabelecimento": loja, "data_compra": dia.isoformat(), "itens": itens,
                            "valor_total_compra": round(sum(i["valor_total"] for i in itens), 2)})
            dia += timedelta(days=max(1, cada + aleatorio.randint(-2, 3)))
    return sorted(compras, key=lambda c: c["data_compra"])


def main(argv) -> int:
    if "--recriar" in argv and config.DB_DIR.exists():
        shutil.rmtree(config.DB_DIR)
        config.DB_DIR.mkdir(parents=True, exist_ok=True)
        config.CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    from services.db_service import DatabaseService
    db = DatabaseService()
    existentes = db.executar_consulta_uma_linha("SELECT count(*) FROM compras")[0]
    if existentes:
        print(f"O banco de demonstração já tem {existentes} compras ({config.DB_PATH}). Use --recriar para começar de novo.")
        return 0
    compras = compras_ficticias()
    db.salvar_compras_da_ia(compras, entrada={"tipo": "compra", "canal": "demo", "texto": "Dados fictícios do modo demonstração",
                                              "versao_prompt": "demo-v1"})
    from services.dinheiro import formatar_reais
    total = sum(c["valor_total_compra"] for c in compras)
    print(f"Banco de demonstração criado: {len(compras)} compras fictícias, total {formatar_reais(total)} ({config.DB_PATH}).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
