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
    perguntas = [
        ("Descrição livre", "Descreva em português o que está escrito nesta imagem, linha por linha.", None),
        ("Leitura da nota (JSON)", "Leia este cupom de compra.", ESQUEMA_COMPRAS),
    ]
    cliente = ollama.Client(timeout=config.OLLAMA_TIMEOUT * 2)
    for titulo, pergunta, esquema in perguntas:
        inicio = time.monotonic()
        try:
            resposta = cliente.chat(
                model=config.OLLAMA_MODELO_VISAO,
                messages=[{"role": "system", "content": prompt if esquema else "Você lê imagens com atenção."},
                          {"role": "user", "content": pergunta, "images": [str(imagem)]}],
                options={"temperature": 0.1}, keep_alive=config.OLLAMA_KEEP_ALIVE,
                **({"format": esquema} if esquema else {}))
            texto = resposta["message"]["content"]
        except Exception as erro:
            texto = f"ERRO {type(erro).__name__}: {erro}"
        linhas += ["", f"== {titulo} ({time.monotonic() - inicio:.1f} s) ==", texto[:6000]]
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text("\n".join(linhas), encoding="utf-8")
    print("\n".join(linhas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
