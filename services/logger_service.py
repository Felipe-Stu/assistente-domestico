import os
from datetime import datetime

LOGS_BASE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Logs")

class CustomLogger:
    def __init__(self, base_dir: str = LOGS_BASE_DIR):
        self.base_dir = base_dir
        self._dias_inicializados = set()  # Controla em memória os arquivos que já receberam o cabeçalho do dia

    def _obter_caminho_e_garantir_diretorio(self, subpasta: str, nome_arquivo: str) -> str:
        pasta = os.path.join(self.base_dir, subpasta)
        os.makedirs(pasta, exist_ok=True)
        return os.path.join(pasta, nome_arquivo)

    def _garantir_cabecalho_diario(self, caminho_arquivo: str, prefixo_cabecalho: str):
        hoje_str = datetime.now().strftime("%d/%m/%Y")
        chave_controle = f"{caminho_arquivo}_{hoje_str}"

        # Se já foi inicializado nesta execução do sistema hoje, não precisa verificar arquivo
        if chave_controle in self._dias_inicializados:
            return

        # Verifica se a última linha do arquivo já contém o divisor de hoje
        cabecalho_hoje = f"**************************** {prefixo_cabecalho}_{hoje_str} ****************************"
        precisa_escrever = True

        if os.path.exists(caminho_arquivo):
            with open(caminho_arquivo, "r", encoding="utf-8") as f:
                conteudo = f.read()
                if cabecalho_hoje in conteudo:
                    precisa_escrever = False

        if precisa_escrever:
            with open(caminho_arquivo, "a", encoding="utf-8") as f:
                f.write(f"\n{cabecalho_hoje}\n")

        self._dias_inicializados.add(chave_controle)

    def log_geral(self, mensagem: str):
        """Registra entradas no arquivo main_log.txt dentro da pasta Logs/main/"""
        caminho = self._obter_caminho_e_garantir_diretorio("main", "main_log.txt")
        self._garantir_cabecalho_diario(caminho, "main")

        timestamp = datetime.now().strftime("[%d/%m/%Y - %H:%M:%S]")
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} {mensagem}\n")

    def log_assistente(self, nome_assistente: str, mensagem: str):
        """Registra entradas no arquivo log.txt dentro da pasta Logs/nome_do_assistente/"""
        # Normaliza o nome da pasta (ex: "Controle de Consumo" -> "controle_consumo")
        pasta_assistente = nome_assistente.lower().replace(" ", "_")
        caminho = self._obter_caminho_e_garantir_diretorio(pasta_assistente, "log.txt")
        self._garantir_cabecalho_diario(caminho, "log")

        timestamp = datetime.now().strftime("[%d/%m/%Y - %H:%M:%S]")
        with open(caminho, "a", encoding="utf-8") as f:
            f.write(f"{timestamp} {mensagem}\n")

# Instância global pronta para importação
logger = CustomLogger()