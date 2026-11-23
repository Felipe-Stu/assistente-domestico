"""
Dinheiro em centavos inteiros (M08).

Valores de dinheiro são convertidos para centavos (int) uma vez, na entrada, e formatados só na
exibição. Somas em centavos não acumulam o erro do ponto flutuante (0,1 + 0,2 ≠ 0,3).
Arredondamento comercial: meio centavo para cima (ROUND_HALF_UP).
"""
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def para_centavos(valor) -> int:
    """12.9 → 1290; "27,90" → 2790; None ou inválido → 0."""
    if valor is None or valor == "":
        return 0
    try:
        texto = str(valor).strip().replace("R$", "").replace(" ", "")
        if "," in texto:  # formato brasileiro: 1.234,56
            texto = texto.replace(".", "").replace(",", ".")
        return int((Decimal(texto) * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))
    except (InvalidOperation, ValueError):
        return 0


def para_reais(centavos: int) -> float:
    """Para exibir ou para os campos REAL antigos, que continuam preenchidos."""
    return round(int(centavos) / 100, 2)


def formatar(centavos: int) -> str:
    """1234567 → 'R$ 12.345,67'."""
    sinal = "-" if centavos < 0 else ""
    reais, cent = divmod(abs(int(centavos)), 100)
    return f"{sinal}R$ {reais:,}".replace(",", ".") + f",{cent:02d}"


def formatar_reais(valor) -> str:
    return formatar(para_centavos(valor))
