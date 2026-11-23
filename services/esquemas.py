"""
Esquemas JSON (JSON Schema) das respostas estruturadas pedidas aos modelos locais.

São enviados no parâmetro `format` do Ollama, que restringe a geração ao esquema:
valores fora das listas permitidas e campos obrigatórios ausentes deixam de ocorrer.
A validação em Python continua existindo como segunda barreira.
"""
from typing import Any, Dict

# O esquema da decisão do orquestrador é montado do catálogo: core/skills/seletor.esquema_decisao()

_ITEM_COMPRA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "produto": {"type": "string"},
        "marca": {"type": ["string", "null"]},
        "quantidade": {"type": "number"},
        "unidade": {"type": "string"},
        "valor_unitario": {"type": "number"},
        "valor_total": {"type": "number"},
        "categoria": {"type": "string"},
        "embalagem_quantidade": {"type": ["number", "null"]},
        "embalagem_unidade": {"type": ["string", "null"]},
    },
    "required": ["produto", "quantidade", "unidade", "valor_unitario", "valor_total"],
}

ESQUEMA_COMPRAS: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "compras": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "estabelecimento": {"type": "string"},
                    "data_compra": {"type": "string"},
                    "itens": {"type": "array", "items": _ITEM_COMPRA},
                    "valor_total_compra": {"type": "number"},
                },
                "required": ["estabelecimento", "itens"],
            },
        }
    },
    "required": ["compras"],
}
