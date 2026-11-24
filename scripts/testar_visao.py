"""
Mostra o que o modelo local de imagem (OLLAMA_MODELO_VISAO) enxerga numa foto de nota.
Uso: dois cliques em testar-visao.bat (usa a imagem mais recente de Anexos/) ou arraste uma imagem sobre ele.
Grava a resposta crua em Planejamento/medicoes/visao-ultima.txt.
"""
import json
import sys
import time
from datetime import date, datetime
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from core import config  # noqa: E402

SAIDA = RAIZ.parent / "Planejamento" / "medicoes" / "visao-ultima.txt"


def _imagem_controle():
    try:
        import io
        from PIL import Image, ImageDraw, ImageFont
        try:
            fonte = ImageFont.truetype("arial.ttf", 56)
        except OSError:
            try:
                fonte = ImageFont.load_default(size=56)
            except TypeError:
                fonte = ImageFont.load_default()
        im = Image.new("RGB", (896, 448), "white")
        desenho = ImageDraw.Draw(im)
        desenho.text((40, 80), "NOTA TESTE 123", fill="black", font=fonte)
        desenho.text((40, 220), "ARROZ  R$ 25,90", fill="black", font=fonte)
        saida = io.BytesIO()
        im.save(saida, "PNG")
        return saida.getvalue()
    except Exception:
        return None


def _imagem_quadrada(caminho: Path):
    try:
        import io
        from PIL import Image, ImageChops
        with Image.open(caminho) as im:
            im = im.convert("RGB")
            caixa = ImageChops.difference(im, Image.new("RGB", im.size, "white")).getbbox()
            if caixa:
                im = im.crop(caixa)
            lado = max(im.size)
            quadrado = Image.new("RGB", (lado, lado), "white")
            quadrado.paste(im, ((lado - im.width) // 2, (lado - im.height) // 2))
            saida = io.BytesIO()
            quadrado.save(saida, "PNG")
            return saida.getvalue()
    except Exception:
        return None


def main() -> int:
    if len(sys.argv) >= 2 and Path(sys.argv[1]).is_file():
        imagem = Path(sys.argv[1])
    else:
        # Sem arquivo arrastado: usa a imagem de nota mais recente guardada em Anexos/
        imagens = [f for f in Path(config.ANEXOS_DIR).rglob("*") if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
        if not imagens:
            print("Nenhuma imagem em Anexos/. Arraste uma imagem (JPG/PNG) sobre testar-visao.bat.")
            return 1
        imagem = max(imagens, key=lambda f: f.stat().st_mtime)
        print(f"Usando a imagem mais recente de Anexos: {imagem.name}")
    linhas = [f"Teste do modelo de imagem — {datetime.now():%d/%m/%Y %H:%M}",
              f"Modelo: {config.OLLAMA_MODELO_VISAO}", f"Arquivo: {imagem.name} ({imagem.stat().st_size // 1024} KB)"]
    try:
        from PIL import Image
        with Image.open(imagem) as im:
            linhas.append(f"Tamanho: {im.width} x {im.height} px")
    except Exception as erro:
        linhas.append(f"Tamanho: não lido ({type(erro).__name__})")
    import ollama
    try:
        info = ollama.Client().show(config.OLLAMA_MODELO_VISAO)
        capacidades = getattr(info, "capabilities", None) or (info.get("capabilities") if isinstance(info, dict) else None)
        linhas.append(f"Capacidades do modelo: {capacidades or 'não informadas por esta versão do Ollama'}")
    except Exception as erro:
        linhas.append(f"Capacidades do modelo: não consultadas ({type(erro).__name__}: {erro})")

    from core.skills.catalogo import obter_catalogo
    from services.esquemas import ESQUEMA_COMPRAS
    prompt = obter_catalogo().skill("compras").prompt("foto_cupom", data_atual=date.today().isoformat())
    cliente = ollama.Client(timeout=config.OLLAMA_TIMEOUT * 2)

    def perguntar(titulo, dados_imagem, pergunta, esquema=None):
        inicio = time.monotonic()
        try:
            resposta = cliente.chat(
                model=config.OLLAMA_MODELO_VISAO,
                messages=[{"role": "system", "content": prompt if esquema else "Você lê imagens com atenção."},
                          {"role": "user", "content": pergunta, "images": [dados_imagem]}],
                options={"temperature": 0.1}, keep_alive=config.OLLAMA_KEEP_ALIVE,
                **({"format": esquema} if esquema else {}))
            texto = resposta["message"]["content"]
        except Exception as erro:
            texto = f"ERRO {type(erro).__name__}: {erro}"
        linhas.extend(["", f"== {titulo} ({time.monotonic() - inicio:.1f} s) ==", texto[:3000]])

    descrever = "Transcreva o texto que aparece nesta imagem, linha por linha."
    # 1. Controle: imagem simples gerada aqui. Se nem esta for lida, o recurso de imagem do modelo não está funcionando.
    controle = _imagem_controle()
    if controle:
        perguntar("1. Imagem de controle (texto grande gerado pelo teste)", controle, descrever)
    # 2. A nota, enviada como bytes (não como caminho)
    perguntar("2. Nota original (bytes)", imagem.read_bytes(), descrever)
    # 3. A nota recortada e centralizada num quadrado branco (o modelo reduz a imagem para um quadrado)
    ajustada = _imagem_quadrada(imagem)
    if ajustada:
        perguntar("3. Nota recortada em quadrado", ajustada, descrever)
        perguntar("4. Nota recortada em quadrado: leitura em JSON", ajustada, "Leia este cupom de compra.", ESQUEMA_COMPRAS)
    else:
        perguntar("4. Nota original: leitura em JSON", imagem.read_bytes(), "Leia este cupom de compra.", ESQUEMA_COMPRAS)
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text("\n".join(linhas), encoding="utf-8")
    print("\n".join(linhas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
