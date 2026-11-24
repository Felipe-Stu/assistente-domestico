"""
Pasta de entrada: arquivos salvos em ENTRADAS_DIR são importados pelo assistente.

Vigia a pasta a cada ENTRADAS_INTERVALO_S segundos. Um arquivo é entregue quando o tamanho para de
mudar (cópia terminada). Depois de tratado, vai para Entradas/processados (ou Entradas/com_erro):
a pasta principal fica só com o que ainda não foi lido. Arquivos com o prefixo "telegram_" vieram do bot.
"""
import threading
import time
from pathlib import Path
from typing import Callable, Dict

from services.documentos_service import tipo_do_arquivo
from services.logger_service import logger as custom_logger

COMPONENTE = "entradas"


class PastaEntradas:
    def __init__(self, pasta: Path, ao_encontrar: Callable[[Path, str], None], intervalo_s: float = 5):
        self.pasta = Path(pasta)
        self.ao_encontrar = ao_encontrar
        self.intervalo_s = intervalo_s
        self._tamanhos: Dict[Path, int] = {}
        self._entregues = set()

    def preparar(self) -> None:
        for sub in ("", "processados", "com_erro"):
            (self.pasta / sub).mkdir(parents=True, exist_ok=True)

    @staticmethod
    def canal(caminho: Path) -> str:
        return "telegram" if caminho.name.startswith("telegram_") else "pasta"

    def verificar(self) -> int:
        """Uma passada: entrega os arquivos novos cuja cópia terminou."""
        entregues = 0
        vistos = set()
        for arquivo in sorted(self.pasta.iterdir()):
            if not arquivo.is_file() or tipo_do_arquivo(arquivo) is None or arquivo in self._entregues:
                continue
            vistos.add(arquivo)
            tamanho = arquivo.stat().st_size
            if self._tamanhos.get(arquivo) == tamanho and tamanho > 0:
                self._entregues.add(arquivo)
                self.ao_encontrar(arquivo, self.canal(arquivo))
                entregues += 1
            else:
                self._tamanhos[arquivo] = tamanho
        for antigo in set(self._tamanhos) - vistos:
            self._tamanhos.pop(antigo, None)
        return entregues

    def mover(self, arquivo: Path, ok: bool) -> Path:
        destino_pasta = self.pasta / ("processados" if ok else "com_erro")
        destino_pasta.mkdir(parents=True, exist_ok=True)
        destino = destino_pasta / arquivo.name
        n = 1
        while destino.exists():
            destino = destino_pasta / f"{arquivo.stem}-{n}{arquivo.suffix}"
            n += 1
        arquivo.replace(destino)
        self._entregues.discard(arquivo)
        return destino

    def iniciar_em_segundo_plano(self, deve_parar: Callable[[], bool]):
        self.preparar()

        def laco():
            while not deve_parar():
                try:
                    self.verificar()
                except Exception as erro:
                    custom_logger.evento(COMPONENTE, "falha", type(erro).__name__, nivel="WARNING")
                time.sleep(self.intervalo_s)

        linha = threading.Thread(target=laco, name="entradas", daemon=True)
        linha.start()
        return linha
