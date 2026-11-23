"""
Descobre o número do seu chat com o bot do Telegram, para preencher TELEGRAM_CHAT_IDS no .env.

Uso: mande qualquer mensagem ao seu bot no Telegram e rode `python scripts/configurar_telegram.py`.
Rode com o assistente fechado: os dois buscariam as mesmas mensagens.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core import config  # noqa: E402
from services.telegram_service import TelegramErro, TelegramService  # noqa: E402

SAIDA = Path(__file__).resolve().parent.parent.parent / "Planejamento" / "medicoes" / "telegram-ultima.txt"


def registrar(texto: str) -> None:
    """Grava o resultado (sem o token) para o Claude conferir depois."""
    SAIDA.parent.mkdir(parents=True, exist_ok=True)
    with SAIDA.open("a", encoding="utf-8") as arquivo:
        arquivo.write(texto + "\n")


def main() -> int:
    if not config.TELEGRAM_BOT_TOKEN:
        print("Falta TELEGRAM_BOT_TOKEN no .env. Crie o bot com o @BotFather no Telegram e cole o token lá.")
        return 1
    servico = TelegramService(config.TELEGRAM_BOT_TOKEN, set(), config.TELEGRAM_OFFSET_ARQUIVO)
    try:
        bot = servico._chamar("getMe", servico._get)
        atualizacoes = servico._chamar("getUpdates", servico._get, params={"timeout": 0})
    except TelegramErro as erro:
        print(f"Não consegui falar com o Telegram: {erro}. Confira o token e a internet.")
        registrar(f"Falha: {erro}")
        return 1
    SAIDA.unlink(missing_ok=True)
    print(f"Bot: @{bot.get('username')}")
    registrar(f"Bot: @{bot.get('username')}")
    chats = {}
    for item in atualizacoes or []:
        chat = (item.get("message") or {}).get("chat") or {}
        if chat.get("id") is not None:
            chats[chat["id"]] = chat.get("first_name") or chat.get("title") or ""
    if not chats:
        print("Nenhuma mensagem encontrada. Mande um 'oi' ao bot no Telegram e rode de novo.")
        registrar("Nenhuma mensagem encontrada")
        return 1
    for chat_id, nome in chats.items():
        print(f"Chat encontrado: {chat_id} ({nome})")
        registrar(f"Chat encontrado: {chat_id} ({nome})")
    print(f"\nColoque no .env:  TELEGRAM_CHAT_IDS={','.join(str(c) for c in chats)}")
    print("Confira se o nome é o seu: só os chats dessa lista serão atendidos.")
    if config.TELEGRAM_CHAT_IDS:
        print(f"Já configurado hoje: {sorted(config.TELEGRAM_CHAT_IDS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
