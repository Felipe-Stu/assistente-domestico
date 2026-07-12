from google import genai
from google.genai import types
from datetime import datetime
import os
import json

def processar_texto_com_gemini(texto_transcrito):
    client = genai.Client()
    data_atual = datetime.now().strftime("%Y-%m-%d")
    
    prompt = f"""
    Você é um assistente especializado em transformar descrições de compras em registros estruturados.

    Sua única função é analisar o texto informado e retornar APENAS um JSON válido, sem explicações, sem markdown e sem qualquer texto adicional.

    REGRAS

    1. Identifique todos os estabelecimentos mencionados. O usuário pode relatar compras em mais de um mercado no mesmo relato (ex: "comprei tal coisa no Moreschi e tal coisa no Proença").
    2. Se houver mais de um estabelecimento, separe os produtos correspondentes a cada um deles em objetos de compras distintos dentro da lista principal "compras".
    3. A data atual de cada compra é obrigatoriamente: {data_atual}.
    4. Extraia todos os produtos comprados e associe-os ao mercado correto com base no contexto do texto.
    5. Sempre que possível identifique para cada item:
    - nome do produto
    - marca
    - quantidade
    - unidade de medida
    - valor total do item
    - valor unitário
    6. Caso o valor unitário não seja informado mas exista quantidade e valor total:
    valor_unitario = valor_total / quantidade
    7. Caso quantidade não seja informada:
    quantidade = 1
    8. Caso a unidade não seja informada:
    unidade = "un"
    9. Caso a marca não seja identificada:
    marca = null
    10. Caso o estabelecimento não seja identificado para um grupo de itens:
        estabelecimento = null
    11. Todos os valores monetários devem ser números (float), sem "R$".
    12. Não invente informações.

    FORMATO DA RESPOSTA

    {{
        "compras": [
            {{
                "estabelecimento": "Nome do Mercado A",
                "data_compra": "{data_atual}",
                "itens": [
                    {{
                        "produto": "",
                        "marca": null,
                        "quantidade": 1,
                        "unidade": "un",
                        "valor_unitario": 0.0,
                        "valor_total": 0.0
                    }}
                ],
                "valor_total_compra": 0.0
            }},
            {{
                "estabelecimento": "Nome do Mercado B",
                "data_compra": "{data_atual}",
                "itens": [
                    {{
                        "produto": "",
                        "marca": null,
                        "quantidade": 1,
                        "unidade": "un",
                        "valor_unitario": 0.0,
                        "valor_total": 0.0
                    }}
                ],
                "valor_total_compra": 0.0
            }}
        ]
    }}

    Texto informado:

    "{texto_transcrito}"
    """
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    
    return json.loads(response.text)
