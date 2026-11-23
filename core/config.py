import os
from pathlib import Path
from dotenv import load_dotenv

# Carregar variáveis de ambiente do arquivo .env
load_dotenv()

# Caminhos do projeto
BASE_DIR = Path(__file__).resolve().parent.parent
DB_DIR = BASE_DIR / "core" / "database"
DB_PATH = DB_DIR / "assistente_casa.db"
CHROMA_DIR = DB_DIR / "chroma_db"

# Garantir que os diretórios do banco de dados existam
DB_DIR.mkdir(parents=True, exist_ok=True)
CHROMA_DIR.mkdir(parents=True, exist_ok=True)

# Configurações do Banco Vetorial e Embeddings Locais (CPU)
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL_NAME", "paraphrase-multilingual-MiniLM-L12-v2")
# CPU por padrão: a VRAM fica livre para o modelo generativo do Ollama
EMBEDDING_DEVICE = os.getenv("EMBEDDING_DEVICE", "cpu")

# Saída estruturada dos modelos locais: envia um JSON Schema no parâmetro `format` do Ollama.
# Defina OLLAMA_SAIDA_ESTRUTURADA=0 para voltar ao modo JSON simples.
OLLAMA_SAIDA_ESTRUTURADA = os.getenv("OLLAMA_SAIDA_ESTRUTURADA", "1").strip() != "0"
# Raciocínio ("think") dos modelos que o suportam: vazio = padrão do Ollama, 0 = desliga, 1 = liga.
_raciocinio = os.getenv("OLLAMA_RACIOCINIO", "").strip()
OLLAMA_RACIOCINIO = None if _raciocinio == "" else _raciocinio != "0"

# Registro de eventos (M26): uma linha JSON por evento em Logs/eventos-AAAA-MM-DD.jsonl
LOGS_DIR = Path(os.getenv("LOGS_DIR", str(BASE_DIR / "Logs")))
# 0 = não grava o texto das mensagens do usuário (fica só o tamanho)
LOG_CONTEUDO = os.getenv("LOG_CONTEUDO", "1").strip() != "0"
LOG_RETENCAO_DIAS = int(os.getenv("LOG_RETENCAO_DIAS", "30"))

# Cópia de segurança automática (M11): SQLite + ChromaDB, uma vez por dia
BACKUP_ATIVO = os.getenv("BACKUP_ATIVO", "1").strip() != "0"
BACKUP_DIR = Path(os.getenv("BACKUP_DIR", str(DB_DIR / "backups")))
BACKUP_DIARIOS = int(os.getenv("BACKUP_DIARIOS", "7"))
BACKUP_SEMANAIS = int(os.getenv("BACKUP_SEMANAIS", "4"))

# Orquestrador (SK2): "catalogo" escolhe a skill pelo catálogo de skills/; "contextos" volta ao prompt antigo
ORQUESTRADOR_MODO = os.getenv("ORQUESTRADOR_MODO", "catalogo").strip().lower()
if ORQUESTRADOR_MODO not in ("catalogo", "contextos"):
    ORQUESTRADOR_MODO = "catalogo"

# Credenciais e chaves
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Parâmetros de Áudio
SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
CHANNELS = int(os.getenv("AUDIO_CHANNELS", "1"))
CHUNK_SIZE = int(os.getenv("AUDIO_CHUNK_SIZE", "1024"))
# Alterado o padrão de 7 para 20 segundos de tolerância para você começar a falar
RECORD_SECONDS = int(os.getenv("AUDIO_RECORD_SECONDS", "20"))

# Skill ProjectAnalyzer — análise de projetos 100% local
# Única pasta onde a Skill pode escrever (uma subpasta por projeto analisado)
PROJECT_ANALYZER_OUTPUT_DIR = Path(os.getenv("PROJECT_ANALYZER_OUTPUT_DIR", str(BASE_DIR.parent / "Documentacao_Gerada")))
# Modelo local usado para interpretar e redigir a análise
PROJECT_ANALYZER_MODEL = os.getenv("PROJECT_ANALYZER_MODEL", "qwen2.5-coder:7b")
