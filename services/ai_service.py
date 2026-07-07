from google import genai
from google.genai import types
from datetime import datetime
import os
import json

def processar_texto_com_gemini(texto_transcrito):
    # O novo SDK busca automaticamente a variável GEMINI_API_KEY do sistema
    client = genai.Client()
    
    # Captura a data exata do momento da execução no formato AAAA-MM-DD
    data_atual = datetime.now().strftime("%Y-%m-%d")
    
    prompt = f"""
Você é um assistente especializado em transformar descrições de compras em registros estruturados.

Sua única função é analisar o texto informado e retornar APENAS um JSON válido, sem explicações, sem markdown e sem qualquer texto adicional.

REGRAS

1. Identifique o estabelecimento onde a compra foi realizada.
2. A data atual desta compra é obrigatoriamente: {data_atual}.
3. Extraia todos os produtos comprados.
4. Sempre que possível identifique:
   - nome do produto
   - marca
   - quantidade
   - unidade de medida
   - valor total do item
   - valor unitário
5. Caso o valor unitário não seja informado mas exista quantidade e valor total:
   valor_unitario = valor_total / quantidade
6. Caso quantidade não seja informada:
   quantidade = 1
7. Caso a unidade não seja informada:
   unidade = "un"
8. Caso a marca não seja identificada:
   marca = null
9. Caso o estabelecimento não seja identificado:
   estabelecimento = null
10. Todos os valores monetários devem ser números (float), sem "R$".
11. Não invente informações.
12. Retorne apenas os produtos explicitamente mencionados.

FORMATO DA RESPOSTA

{{
    "estabelecimento": "",
    "data_compra": "{data_atual}",
    "itens": [
        {{
            "produto": "",
            "marca": null,
            "quantidade": 0,
            "unidade": "",
            "valor_unitario": 0.0,
            "valor_total": 0.0
        }}
    ],
    "valor_total_compra": 0.0
}}

Texto informado:

"{texto_transcrito}"
"""
    
    # Chamada oficial usando o SDK moderno e o modelo estável mais rápido
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json"
        ),
    )
    
    return json.loads(response.text)