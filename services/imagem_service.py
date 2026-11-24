"""
M34: prepara a foto de uma nota para o modelo de imagem.

- converte para RGB e recorta as margens brancas;
- cupom comprido (altura > 1,6 × largura) vira faixas com sobreposição, lidas uma a uma:
  o modelo reduz cada imagem a um quadrado, e a letra miúda some se o cupom inteiro for de uma vez;
- imagem pequena é ampliada.
Sem Pillow, devolve o arquivo como está.
"""
import io
from pathlib import Path
from typing import List

PROPORCAO_FAIXA = 1.3      # altura de cada faixa em relação à largura
SOBREPOSICAO = 0.08        # parte de cada faixa repetida na seguinte (linha cortada aparece inteira em uma delas)
LADO_MINIMO = 1000         # px: imagem menor é ampliada
MAXIMO_FAIXAS = 6


def preparar(caminho: Path) -> List[bytes]:
    dados = Path(caminho).read_bytes()
    try:
        from PIL import Image, ImageChops
    except ImportError:
        return [dados]
    try:
        with Image.open(io.BytesIO(dados)) as original:
            im = original.convert("RGB")
    except Exception:
        return [dados]
    fundo = Image.new("RGB", im.size, "white")
    caixa = ImageChops.difference(im, fundo).point(lambda v: 255 if v > 24 else 0).getbbox()
    if caixa:
        margem = 12
        im = im.crop((max(0, caixa[0] - margem), max(0, caixa[1] - margem),
                      min(im.width, caixa[2] + margem), min(im.height, caixa[3] + margem)))
    if max(im.size) < LADO_MINIMO:
        fator = LADO_MINIMO / max(im.size)
        im = im.resize((round(im.width * fator), round(im.height * fator)), Image.LANCZOS)
    faixas = [im]
    if im.height > 1.6 * im.width:
        altura = round(im.width * PROPORCAO_FAIXA)
        passo = round(altura * (1 - SOBREPOSICAO))
        faixas = [im.crop((0, topo, im.width, min(im.height, topo + altura)))
                  for topo in range(0, max(1, im.height - round(altura * SOBREPOSICAO)), passo)][:MAXIMO_FAIXAS]
    saida = []
    for faixa in faixas:
        buffer = io.BytesIO()
        faixa.save(buffer, "PNG")
        saida.append(buffer.getvalue())
    return saida
