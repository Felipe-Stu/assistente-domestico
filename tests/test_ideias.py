"""
Testes das ideias de projetos: Claude pela assinatura, IdeiasService, bot do Telegram e skill ideias.
Nada sai da máquina: o Claude Code, o Telegram e o modelo local são simulados.
"""
import json
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR / "tests"))

import test_fase1 as fase1  # noqa: E402
from app import main as app_main  # noqa: E402
from core.skills import Contexto, motor, obter_catalogo  # noqa: E402
from services.claude_assinatura_service import ClaudeAssinaturaService, montar_conversa  # noqa: E402
from services.claude_service import ClaudeIndisponivelError  # noqa: E402
from services.ideias_service import IdeiasService, separar_titulo  # noqa: E402
from services.telegram_service import TelegramService, dividir_mensagem  # noqa: E402

AGORA = datetime(2026, 11, 23, 13, 0)
ANALISE = "# Receitas da Geladeira\n\n## Resumo\nApp que sugere receitas.\n\n## Próximos passos\n1. Listar receitas."


class Pasta(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.pasta = Path(self._tmp.name)


# ---------------------------------------------------------------------------
# Claude pela assinatura
# ---------------------------------------------------------------------------

class TestClaudeAssinatura(Pasta):
    def servico(self, saida="", codigo=0, stderr="", erro=None, caminho="/usr/bin/claude"):
        self.chamadas = []

        def executar(args, **kwargs):
            self.chamadas.append((args, kwargs, Path(args[args.index("--system-prompt-file") + 1]).read_text(encoding="utf-8")))
            if erro:
                raise erro
            return SimpleNamespace(returncode=codigo, stdout=saida, stderr=stderr)

        return ClaudeAssinaturaService("claude", "sonnet", self.pasta / "estado.json", hora_reteste=8, reteste_minutos=60,
                                       agora=lambda: AGORA, executar=executar, localizar=lambda _c: caminho)

    def test_resposta_sem_ferramentas_e_sem_chave_de_api(self):
        saida = json.dumps({"type": "result", "subtype": "success", "is_error": False, "result": " Olá ", "total_cost_usd": 0.01})
        servico = self.servico(saida)
        with mock.patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-teste", "ANTHROPIC_AUTH_TOKEN": "x", "PATH": "/bin"}):
            self.assertEqual(servico.gerar_texto("Sistema", "Oi", [{"role": "user", "content": "antes"}]), "Olá")
        args, kwargs, prompt = self.chamadas[0]
        self.assertEqual(args[args.index("--tools") + 1], "")
        self.assertIn("mcp__*", args)
        self.assertIn("--no-session-persistence", args)
        self.assertEqual(prompt, "Sistema")
        self.assertNotIn("ANTHROPIC_API_KEY", kwargs["env"])
        self.assertNotIn("ANTHROPIC_AUTH_TOKEN", kwargs["env"])
        self.assertIn("Usuário: antes", kwargs["input"])
        self.assertTrue(kwargs["input"].endswith("Oi"))

    def test_sem_claude_code_fica_desligado(self):
        servico = self.servico(caminho=None)
        self.assertFalse(servico.configurado())
        with self.assertRaisesRegex(ClaudeIndisponivelError, "Claude Code não encontrado"):
            servico.gerar_texto("s", "m")

    def test_limite_do_plano_espera_os_minutos_configurados(self):
        saida = json.dumps({"subtype": "success", "is_error": True, "result": "Claude AI usage limit reached|1764000000"})
        servico = self.servico(saida, codigo=1)
        with self.assertRaises(ClaudeIndisponivelError) as erro:
            servico.gerar_texto("s", "m")
        self.assertEqual(erro.exception.ate, datetime(2026, 11, 23, 14, 0))
        with self.assertRaisesRegex(ClaudeIndisponivelError, "limite de uso da assinatura"):
            servico.verificar_disponibilidade()

    def test_sem_login_espera_a_manha(self):
        servico = self.servico("", codigo=1, stderr="Invalid API key · Please run /login")
        with self.assertRaises(ClaudeIndisponivelError) as erro:
            servico.gerar_texto("s", "m")
        self.assertEqual(erro.exception.ate, datetime(2026, 11, 24, 8, 0))

    def test_falha_passageira_nao_bloqueia(self):
        servico = self.servico(erro=subprocess.TimeoutExpired("claude", 300))
        with self.assertRaisesRegex(ClaudeIndisponivelError, "a tempo"):
            servico.gerar_texto("s", "m")
        servico.verificar_disponibilidade()  # não marcou indisponível

    def test_acha_o_instalador_nativo_fora_do_path(self):
        from services import claude_assinatura_service as modulo
        (self.pasta / ".local" / "bin").mkdir(parents=True)
        (self.pasta / ".local" / "bin" / "claude.exe").write_text("", encoding="utf-8")
        with mock.patch.object(modulo.shutil, "which", return_value=None), mock.patch.object(modulo.Path, "home", return_value=self.pasta):
            self.assertEqual(modulo.localizar_claude("claude"), str(self.pasta / ".local" / "bin" / "claude.exe"))

    def test_conversa_sem_historico_e_o_proprio_texto(self):
        self.assertEqual(montar_conversa(None, "oi"), "oi")


# ---------------------------------------------------------------------------
# Serviço de ideias
# ---------------------------------------------------------------------------

class ClaudeFalso:
    def __init__(self, respostas=None, pronto=True):
        self.respostas = list(respostas or [])
        self.pronto = pronto
        self.pedidos = []

    def configurado(self):
        return self.pronto

    def _motivo_nao_configurado(self):
        return "Claude Code não encontrado no PC"

    def gerar_texto(self, prompt, texto, historico=None):
        self.pedidos.append((prompt, texto))
        resposta = self.respostas.pop(0)
        if isinstance(resposta, Exception):
            raise resposta
        return resposta


class BaseIdeias(fase1.BaseBanco):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(self._tmp.cleanup)
        self.pasta = Path(self._tmp.name) / "Ideias"
        self.biblioteca = mock.Mock()

    def servico(self, claude):
        return IdeiasService(self.db, claude, self.pasta, prompt_analise=lambda: "PROMPT DE ANÁLISE",
                             biblioteca=self.biblioteca, agora=lambda: AGORA)


class TestIdeiasService(BaseIdeias):
    def test_salva_analisa_grava_arquivo_e_indexa(self):
        claude = ClaudeFalso([ANALISE])
        ideias = self.servico(claude)
        ideia = ideias.salvar("App que olha a geladeira e sugere receitas", "telegram:42")
        self.assertEqual((ideia["id"], ideia["situacao"]), (1, "pendente"))
        avisos = []
        self.assertEqual(ideias.processar_pendentes(avisos.append), 1)
        self.assertEqual(claude.pedidos, [("PROMPT DE ANÁLISE", "App que olha a geladeira e sugere receitas")])
        salva = ideias.obter(1)
        self.assertEqual((salva["titulo"], salva["situacao"]), ("Receitas da Geladeira", "analisada"))
        arquivo = self.pasta / "ideia-0001-receitas-da-geladeira.md"
        conteudo = arquivo.read_text(encoding="utf-8")
        self.assertIn("## Ideia original\n\nApp que olha a geladeira", conteudo)
        self.assertIn("## Próximos passos", conteudo)
        self.assertEqual(conteudo.count("# Receitas da Geladeira"), 1)
        self.biblioteca.indexar.assert_called_once()
        self.assertEqual(avisos[0]["origem"], "telegram:42")

    def test_claude_indisponivel_mantem_na_fila(self):
        claude = ClaudeFalso([ClaudeIndisponivelError("limite de uso da assinatura do Claude atingido"), ANALISE, ANALISE])
        ideias = self.servico(claude)
        ideias.salvar("Primeira ideia de sistema")
        ideias.salvar("Segunda ideia de sistema")
        self.assertEqual(ideias.processar_pendentes(), 0)
        self.assertEqual(len(claude.pedidos), 1)  # não insiste nas outras com o mesmo motivo
        self.assertEqual(ideias.obter(1)["motivo"], "limite de uso da assinatura do Claude atingido")
        self.assertEqual(ideias.processar_pendentes(), 2)
        self.assertEqual([i["situacao"] for i in ideias.listar()], ["analisada", "analisada"])

    def test_sem_claude_avisa_que_fica_na_fila(self):
        ideias = self.servico(ClaudeFalso(pronto=False))
        resposta = ideias.confirmacao(ideias.salvar("Ideia de um bot de passagens"))
        self.assertIn("fica na fila", resposta)
        self.assertEqual(ideias.processar_pendentes(), 0)

    def test_busca_por_numero_e_por_palavras(self):
        ideias = self.servico(ClaudeFalso())
        ideias.salvar("Controle de manutenção da moto")
        ideias.salvar("App de receitas pela geladeira")
        self.assertEqual(ideias.buscar("ver ideia 1")["id"], 1)
        self.assertEqual(ideias.buscar("#2")["id"], 2)
        self.assertEqual(ideias.buscar("como sigo a ideia da moto?")["id"], 1)

    def test_comandos_do_telegram(self):
        ideias = self.servico(ClaudeFalso())
        self.assertIn("/ideias", ideias.responder_mensagem("/start", "telegram:1"))
        self.assertIn("Ideia #1 salva", ideias.responder_mensagem("Um app para a família dividir tarefas", "telegram:1"))
        self.assertEqual(ideias.obter(1)["origem"], "telegram:1")
        self.assertIn("#1 Um app para a família", ideias.responder_mensagem("/ideias", "telegram:1"))
        self.assertIn("aguardando análise", ideias.responder_mensagem("/ver 1", "telegram:1"))
        self.assertIn("voltou para a fila", ideias.responder_mensagem("/reanalisar 1", "telegram:1"))
        self.assertIn("Não encontrei", ideias.responder_mensagem("/ver 9", "telegram:1"))
        self.assertIn("desconhecido", ideias.responder_mensagem("/apagar", "telegram:1"))
        for curta in ("oi", "'oi'", "Bom dia!", "tudo bem?"):
            self.assertIn("Estou ligado", ideias.responder_mensagem(curta, "telegram:1"))
        self.assertEqual(len(ideias.listar()), 1)

    def test_titulo_da_analise(self):
        self.assertEqual(separar_titulo("# Título\n\ncorpo"), ("Título", "corpo"))
        self.assertEqual(separar_titulo("sem título"), (None, "sem título"))


# ---------------------------------------------------------------------------
# Telegram
# ---------------------------------------------------------------------------

class Resposta:
    def __init__(self, dados):
        self.dados = dados

    def json(self):
        return self.dados


class TestTelegram(Pasta):
    def servico(self, atualizacoes, ao_receber):
        self.enviadas = []
        get = lambda url, **k: Resposta({"ok": True, "result": atualizacoes})  # noqa: E731

        def post(url, json=None, **k):
            self.enviadas.append((json["chat_id"], json["text"]))
            return Resposta({"ok": True, "result": {}})

        return TelegramService("123:TOKEN", {42}, self.pasta / "offset.json", ao_receber=ao_receber, get=get, post=post)

    def test_so_atende_o_chat_permitido(self):
        recebidas = []
        atualizacoes = [
            {"update_id": 10, "message": {"chat": {"id": 99}, "text": "invasor"}},
            {"update_id": 11, "message": {"chat": {"id": 42}, "text": "minha ideia"}},
            {"update_id": 12, "message": {"chat": {"id": 42}, "voice": {}}},
        ]
        servico = self.servico(atualizacoes, lambda chat, texto: recebidas.append(texto) or "salva")
        self.assertEqual(servico.processar_uma_vez(), 1)
        self.assertEqual(recebidas, ["minha ideia"])
        self.assertEqual(self.enviadas[0], (42, "salva"))
        self.assertIn("só entendo texto", self.enviadas[1][1])
        self.assertNotIn(99, [chat for chat, _ in self.enviadas])
        self.assertEqual(json.loads((self.pasta / "offset.json").read_text())["offset"], 13)

    def test_erro_de_rede_nao_expoe_o_token(self):
        import requests
        servico = TelegramService("123:SEGREDO", {42}, self.pasta / "o.json",
                                  get=mock.Mock(side_effect=requests.ConnectionError("https://api.telegram.org/bot123:SEGREDO/getUpdates")))
        with self.assertRaises(Exception) as erro:
            servico.processar_uma_vez()
        self.assertNotIn("SEGREDO", str(erro.exception))
        self.assertIsNone(erro.exception.__cause__)

    def test_sem_chat_configurado_fica_desligado(self):
        self.assertFalse(TelegramService("123:T", set(), self.pasta / "o.json").configurado())

    def test_divide_mensagens_longas(self):
        partes = dividir_mensagem("linha\n" * 2000, limite=4000)
        self.assertTrue(all(len(p) <= 4000 for p in partes))
        self.assertEqual("".join(partes), "linha\n" * 2000)


# ---------------------------------------------------------------------------
# Skill e app
# ---------------------------------------------------------------------------

class ModeloLocal:
    def __init__(self):
        self.pedidos = []

    def gerar_texto(self, prompt, texto, *a, **k):
        self.pedidos.append((prompt, texto))
        return "Comece listando as receitas."


class TestSkillIdeias(BaseIdeias):
    def setUp(self):
        super().setUp()
        self.skill = obter_catalogo().skill("ideias")
        self.ideias = self.servico(ClaudeFalso([ANALISE]))
        self.modelo = ModeloLocal()

    def executar(self, texto, acao):
        ctx = Contexto(servicos={"ideias": self.ideias, "llm_local": self.modelo})
        return motor.executar(self.skill, ctx, texto, {"acao": acao})

    def test_salva_sem_o_prefixo(self):
        resposta = self.executar("Tive uma ideia: um app que sugere receitas pela geladeira", "criar")
        self.assertIn("Ideia #1 salva", resposta.texto)
        self.assertEqual(self.ideias.obter(1)["texto"], "um app que sugere receitas pela geladeira")

    def test_sem_conteudo_pergunta_e_salva_a_resposta(self):
        resposta = self.executar("Anota uma ideia", "criar")
        self.assertIn("Qual é a ideia", resposta.texto)
        ctx = Contexto(servicos={"ideias": self.ideias})
        final = motor.responder_pendencia(self.skill, ctx, "Um sistema de rega automática", resposta.pendencia)
        self.assertIn("Ideia #1 salva", final.texto)

    def test_consulta_usa_o_modelo_local_com_a_analise(self):
        self.ideias.salvar("App de receitas pela geladeira")
        self.ideias.processar_pendentes()
        self.assertIn("#1 Receitas da Geladeira (analisada)", self.executar("Quais são minhas ideias?", "consultar").texto)
        self.assertEqual(self.executar("Como sigo a ideia das receitas?", "consultar").texto, "Comece listando as receitas.")
        prompt, pergunta = self.modelo.pedidos[0]
        self.assertIn("## Próximos passos", prompt)
        self.assertEqual(pergunta, "Como sigo a ideia das receitas?")
        self.assertIn("## Resumo", self.executar("mostra a ideia 1", "consultar").texto)


class TestAvisoNoApp(unittest.TestCase):
    def test_analise_volta_para_o_telegram_de_origem(self):
        runtime = app_main.AssistenteRuntime.__new__(app_main.AssistenteRuntime)
        runtime.telegram = mock.Mock()
        with mock.patch.object(app_main, "emitir_electron"):
            runtime._avisar_ideia_analisada({"id": 3, "titulo": "T", "analise": "A", "origem": "telegram:42"})
            runtime._avisar_ideia_analisada({"id": 4, "titulo": "T", "analise": "A", "origem": "chat"})
        runtime.telegram.enviar.assert_called_once_with(42, "💡 Análise da ideia #3\n\nA")


if __name__ == "__main__":
    unittest.main()
