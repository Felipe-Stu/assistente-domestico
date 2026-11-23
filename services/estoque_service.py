"""
Estoque alimentado pelas compras (M06, resolve o P1).

Cada item gravado soma ao estoque do produto do catálogo (M07), na mesma transação da compra:
- a quantidade vai para uma unidade base (kg, litro ou un): "2 pacotes de 5 kg" → 10 kg; "500 g" → 0,5 kg;
- o ritmo de consumo (dias por unidade) é aprendido na segunda compra do mesmo produto, pelo intervalo
  entre as compras; até lá o estoque não diminui sozinho;
- desfazer a compra tira do estoque o que ela tinha somado.

Tudo em `controle_consumo` (uma linha por produto, `produto_id` e `unidade`, migração v6). Não faz
perguntas por voz: a confirmação de sobras fica para quando o estoque for refeito na skill (P8).
"""
import re
import sqlite3
from datetime import date
from typing import Optional, Tuple

_UNIDADES = {
    "kg": ("kg", 1.0), "quilo": ("kg", 1.0), "quilos": ("kg", 1.0), "kilo": ("kg", 1.0),
    "g": ("kg", 0.001), "gr": ("kg", 0.001), "grama": ("kg", 0.001), "gramas": ("kg", 0.001),
    "litro": ("litro", 1.0), "litros": ("litro", 1.0), "l": ("litro", 1.0), "lt": ("litro", 1.0),
    "ml": ("litro", 0.001), "mililitro": ("litro", 0.001), "mililitros": ("litro", 0.001),
}
_RE_TAMANHO = re.compile(r"\s*\b\d+(?:[.,]\d+)?\s*(?:ml|l|lt|lts|litros?|g|gr|gramas?|kg|quilos?)\b", re.IGNORECASE)


def unidade_base(unidade: Optional[str]) -> Tuple[str, float]:
    """('kg', fator) | ('litro', fator) | ('un', 1.0)."""
    return _UNIDADES.get(str(unidade or "").strip().lower().rstrip("."), ("un", 1.0))


def quantidade_base(quantidade, unidade, embalagem_quantidade=None, embalagem_unidade=None) -> Tuple[float, str]:
    """Quantidade comprada na unidade base. Com embalagem informada, conta o conteúdo das embalagens."""
    qtd = float(quantidade or 0)
    if embalagem_quantidade and embalagem_unidade:
        base, fator = unidade_base(embalagem_unidade)
        if base != "un":
            return round(qtd * float(embalagem_quantidade) * fator, 3), base
    base, fator = unidade_base(unidade)
    return round(qtd * fator, 3), base


def nome_exibicao(nome: str) -> str:
    """'Leite 1L' → 'leite' (mantém os acentos)."""
    return " ".join(_RE_TAMANHO.sub(" ", str(nome or "")).lower().split()) or str(nome or "").lower()


def _dias(entre: str, e: str) -> int:
    try:
        return max(0, (date.fromisoformat(str(e)[:10]) - date.fromisoformat(str(entre)[:10])).days)
    except ValueError:
        return 0


def registrar_entrada(cursor: sqlite3.Cursor, produto_id: int, nome: str, categoria: str,
                      quantidade: float, unidade: str, data_compra: str) -> None:
    """Soma uma compra ao estoque do produto. Roda na transação da compra."""
    if not produto_id or quantidade <= 0:
        return
    cursor.execute(
        """SELECT id, tempo_medio_calculado, data_ultima_compra, quantidade_comprada, quantidade_residual_confirmada,
                  status_estoque, unidade FROM controle_consumo WHERE produto_id = ?""", (produto_id,))
    linha = cursor.fetchone()
    if linha is None:
        cursor.execute(
            """INSERT INTO controle_consumo (produto_nome, categoria, tempo_medio_calculado, data_ultima_compra,
                   quantidade_comprada, quantidade_residual_confirmada, status_estoque, ultima_qtd_comprada, produto_id, unidade)
               VALUES (?, ?, 0, ?, ?, 0, 1, ?, ?, ?)""",
            (_nome_livre(cursor, nome_exibicao(nome), produto_id), categoria, data_compra, quantidade, quantidade, produto_id, unidade))
        return
    ident, ritmo, data_ultima, comprada, residual, ativo, unidade_antiga = linha
    ritmo = ritmo or 0.0
    total_antigo = (comprada or 0.0) + (residual or 0.0) if ativo else 0.0
    dias = _dias(data_ultima, data_compra)
    if unidade_antiga and unidade_antiga != unidade:
        total_antigo, ritmo = 0.0, 0.0  # unidade mudou (ex.: kg → un): recomeça a contagem
    if dias == 0:
        restante = total_antigo  # mesma data: nada foi consumido
    elif ritmo > 0:
        restante = max(0.0, total_antigo - dias / ritmo)
    else:
        # Primeira recompra: supõe que o estoque anterior acabou e aprende o ritmo (dias por unidade)
        restante = 0.0
        if total_antigo > 0:
            ritmo = dias / total_antigo
    cursor.execute(
        """UPDATE controle_consumo SET tempo_medio_calculado = ?, data_ultima_compra = ?, quantidade_comprada = ?,
               quantidade_residual_confirmada = ?, status_estoque = 1, ultima_qtd_comprada = ?, unidade = ?,
               validacao_pendente = 0
           WHERE id = ?""",
        (round(ritmo, 4), data_compra, quantidade, round(restante, 3), quantidade, unidade, ident))


def reverter_entrada(cursor: sqlite3.Cursor, produto_id: int, quantidade: float) -> None:
    """Desfazer compra: tira do estoque o que ela somou (aproximação: o ritmo aprendido fica)."""
    if not produto_id or quantidade <= 0:
        return
    cursor.execute("SELECT id, quantidade_comprada, quantidade_residual_confirmada FROM controle_consumo WHERE produto_id = ?",
                   (produto_id,))
    linha = cursor.fetchone()
    if linha is None:
        return
    ident, comprada, residual = linha
    comprada, residual = comprada or 0.0, residual or 0.0
    excedente = max(0.0, quantidade - comprada)  # o que não cabe na última compra sai das sobras
    comprada = max(0.0, comprada - quantidade)
    residual = max(0.0, residual - excedente)
    ativo = 1 if comprada + residual > 0 else 0
    cursor.execute("UPDATE controle_consumo SET quantidade_comprada = ?, quantidade_residual_confirmada = ?, status_estoque = ? "
                   "WHERE id = ?", (round(comprada, 3), round(residual, 3), ativo, ident))


def _nome_livre(cursor: sqlite3.Cursor, nome: str, produto_id: int) -> str:
    """produto_nome é UNIQUE: se já existir (linha antiga sem produto_id), acrescenta o id."""
    cursor.execute("SELECT 1 FROM controle_consumo WHERE produto_nome = ?", (nome,))
    return nome if cursor.fetchone() is None else f"{nome} #{produto_id}"
