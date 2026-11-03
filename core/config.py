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

# Credenciais e chaves
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Parâmetros de Áudio
SAMPLE_RATE = int(os.getenv("AUDIO_SAMPLE_RATE", "16000"))
CHANNELS = int(os.getenv("AUDIO_CHANNELS", "1"))
CHUNK_SIZE = int(os.getenv("AUDIO_CHUNK_SIZE", "1024"))
# Alterado o padrão de 7 para 20 segundos de tolerância para você começar a falar
RECORD_SECONDS = int(os.getenv("AUDIO_RECORD_SECONDS", "20"))