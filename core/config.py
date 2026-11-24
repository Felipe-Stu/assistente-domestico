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

# Modelos e tempos do Ollama (M27). O endereço do servidor vem de OLLAMA_HOST (lido pela biblioteca ollama).
OLLAMA_MODELO_PADRAO = os.getenv("OLLAMA_MODELO_PADRAO", "gemma4:e4b")      # residente: orquestrador, compras, conversa
OLLAMA_MODELO_AVANCADO = os.getenv("OLLAMA_MODELO_AVANCADO", "qwen2.5-coder:7b")  # modo Qwen e reserva da programação
OLLAMA_TIMEOUT = float(os.getenv("OLLAMA_TIMEOUT", "120"))          # segundos por chamada ao modelo
OLLAMA_KEEP_ALIVE = os.getenv("OLLAMA_KEEP_ALIVE", "30m")           # quanto tempo o modelo fica na VRAM depois do uso
OLLAMA_MODELO_VISAO = os.getenv("OLLAMA_MODELO_VISAO", "gemma3:4b")   # lê fotos de cupom; o gemma4 não enxerga imagens no Ollama para Windows (issue 16597)

# Entrada de documentos (notas fiscais em HTML, PDF ou foto)
ENTRADAS_DIR = Path(os.getenv("ENTRADAS_DIR", str(BASE_DIR.parent / "Entradas")))   # pasta vigiada
ANEXOS_DIR = Path(os.getenv("ANEXOS_DIR", str(BASE_DIR.parent / "Anexos")))         # originais guardados
ENTRADAS_INTERVALO_S = float(os.getenv("ENTRADAS_INTERVALO_S", "5"))

# M20: histórico da conversa (gravado no SQLite local)
HISTORICO_JANELA_TROCAS = int(os.getenv("HISTORICO_JANELA_TROCAS", "6"))      # trocas inteiras que vão ao modelo
HISTORICO_RETOMAR_HORAS = float(os.getenv("HISTORICO_RETOMAR_HORAS", "12"))   # reabrir o app continua a conversa
HISTORICO_RESUMO = os.getenv("HISTORICO_RESUMO", "1") != "0"                   # resumo das trocas que saem da janela
ENTRADAS_TAMANHO_MAX_MB = float(os.getenv("ENTRADAS_TAMANHO_MAX_MB", "20"))

# Repetição das chamadas ao modelo local quando a resposta vem malformada
RETRY_TENTATIVAS = int(os.getenv("RETRY_TENTATIVAS", "3"))
RETRY_ESPERA_S = float(os.getenv("RETRY_ESPERA_S", "3"))

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

# Claude (SKP): agente principal de programação quando houver cota; sem cota, o Qwen local responde
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODELO = os.getenv("CLAUDE_MODELO", "claude-sonnet-5-5")
CLAUDE_API_VERSAO = os.getenv("CLAUDE_API_VERSAO", "2026-10-21")
CLAUDE_MAX_TOKENS = int(os.getenv("CLAUDE_MAX_TOKENS", "4096"))
# Teto de gasto do assistente no mês (US$); defina também um limite no Console da Anthropic
CLAUDE_LIMITE_MENSAL_USD = float(os.getenv("CLAUDE_LIMITE_MENSAL_USD", "5"))
# Preço por milhão de tokens (entrada/saída) do modelo acima, para estimar o gasto
CLAUDE_PRECO_ENTRADA = float(os.getenv("CLAUDE_PRECO_ENTRADA", "2"))
CLAUDE_PRECO_SAIDA = float(os.getenv("CLAUDE_PRECO_SAIDA", "10"))
# Sem cota, o Claude volta a ser testado na primeira solicitação depois desta hora
CLAUDE_HORA_RETESTE = int(os.getenv("CLAUDE_HORA_RETESTE", "8"))
# Única skill autorizada a enviar dados ao Claude (decisão de 23/11/2026)
CLAUDE_SKILLS = {s.strip() for s in os.getenv("CLAUDE_SKILLS", "programacao,ideias").split(",") if s.strip()}
# Como o assistente fala com o Claude: "assinatura" (Claude Code logado no seu plano, comando `claude -p`)
# ou "api" (ANTHROPIC_API_KEY, cobrada à parte)
CLAUDE_MODO = os.getenv("CLAUDE_MODO", "assinatura").strip().lower()
CLAUDE_COMANDO = os.getenv("CLAUDE_COMANDO", "claude")
CLAUDE_MODELO_ASSINATURA = os.getenv("CLAUDE_MODELO_ASSINATURA", "sonnet")
# Limite da assinatura atingido: tenta de novo depois destes minutos (a sessão do plano renova a cada 5 h)
CLAUDE_ASSINATURA_RETESTE_MIN = int(os.getenv("CLAUDE_ASSINATURA_RETESTE_MIN", "60"))
CLAUDE_ASSINATURA_TIMEOUT = int(os.getenv("CLAUDE_ASSINATURA_TIMEOUT", "300"))
CLAUDE_ESTADO_ASSINATURA_ARQUIVO = DB_DIR / "estado_claude_assinatura.json"

# Ideias de projetos (skill ideias): banco SQLite + um .md por ideia, fora do Git
IDEIAS_DIR = Path(os.getenv("IDEIAS_DIR", str(BASE_DIR / "Ideias")))
IDEIAS_RETESTE_MIN = int(os.getenv("IDEIAS_RETESTE_MIN", "30"))

# Bot do Telegram para mandar ideias do celular (opcional). Só os chats listados são atendidos.
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_IDS = {int(c) for c in os.getenv("TELEGRAM_CHAT_IDS", "").replace(";", ",").split(",") if c.strip().lstrip("-").isdigit()}
TELEGRAM_OFFSET_ARQUIVO = DB_DIR / "telegram_offset.json"
CLAUDE_ESTADO_ARQUIVO = DB_DIR / "estado_claude.json"

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
