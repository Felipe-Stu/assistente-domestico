"""
Mostra o que o modelo local de imagem (OLLAMA_MODELO_VISAO) enxerga numa foto de nota.
Uso: dois cliques em testar-visao.bat (usa a imagem mais recente de Anexos/) ou arraste uma imagem sobre ele.
Comparar modelos: python scripts/testar_visao.py --modelos gemma3:4b,qwen2.5vl:7b
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


def main() -> int:
    argumentos = [a for a in sys.argv[1:] if a]
    modelos = [config.OLLAMA_MODELO_VISAO]
    if "--modelos" in argumentos:
        i = argumentos.index("--modelos")
        modelos = [m.strip() for m in argumentos[i + 1].split(",") if m.strip()]
        del argumentos[i:i + 2]
    if argumentos and Path(argumentos[0]).is_file():
        imagem = Path(argumentos[0])
    else:
        # Sem arquivo arrastado: usa a imagem de nota mais recente guardada em Anexos/
        imagens = [f for f in Path(config.ANEXOS_DIR).rglob("*") if f.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp")]
        if not imagens:
            print("Nenhuma imagem em Anexos/. Arraste uma imagem (JPG/PNG) sobre testar-visao.bat.")
            return 1
        imagem = max(imagens, key=lambda f: f.stat().st_mtime)
        print(f"Usando a imagem mais recente de Anexos: {imagem.name}")
    linhas = [f"Teste do modelo de imagem — {datetime.now():%d/%m/%Y %H:%M}", f"Arquivo: {imagem.name} ({imagem.stat().st_size // 1024} KB)"]
    from services import imagem_service
    from services.documentos_service import limpar_transcricao
    from services.llm_provider import LocalLLMProvider
    partes = imagem_service.preparar(imagem)
    linhas.append(f"Partes enviadas (recorte e faixas, como no app): {len(partes)}")
    import ollama
    descrever = ("Você transcreve cupons e notas fiscais. Copie fielmente todo o texto desta imagem, linha por linha, "
                 "como está escrito, mantendo números, vírgulas e datas. Não resuma, não traduza e não invente: "
                 "o que estiver ilegível vira [ilegível].")
    for modelo in modelos:
        linhas += ["", f"######## {modelo} ########"]
        try:
            info = ollama.Client().show(modelo)
            capacidades = getattr(info, "capabilities", None) or (info.get("capabilities") if isinstance(info, dict) else None)
            linhas.append(f"Capacidades: {capacidades or 'não informadas'}")
        except Exception as erro:
            linhas.append(f"Modelo não disponível ({type(erro).__name__}: {erro}). Instale com: ollama pull {modelo}")
            continue
        provedor = LocalLLMProvider(modelo=modelo, temperatura=0.1)

        def perguntar(titulo, imagens):
            inicio = time.monotonic()
            try:
                texto = limpar_transcricao(provedor.gerar_texto_imagem(descrever, "Transcreva o texto.", imagens))
            except Exception as erro:
                texto = f"ERRO {type(erro).__name__}: {erro}"
            linhas.extend(["", f"== {titulo} ({time.monotonic() - inicio:.1f} s) ==", texto[:4000]])

        controle = _imagem_controle()
        if controle:
            perguntar("1. Imagem de controle (texto grande gerado pelo teste)", [controle])
        for n, parte in enumerate(partes, start=1):
            perguntar(f"2. Nota preparada, parte {n} de {len(partes)}", [parte])
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    SAIDA.write_text("\n".join(linhas), encoding="utf-8")
    print("\n".join(linhas))
    return 0


if __name__ == "__main__":
    sys.exit(main())
