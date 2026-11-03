"""
Testes da Skill ProjectAnalyzer (unittest, sem dependências externas).

Executar na raiz do assistente:
    python -m unittest discover -s tests -v
"""
import ast
import hashlib
import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT_DIR))

from services.project_analyzer import ProjectAnalyzer, ProjetoInvalidoError, detectar_comando_projeto  # noqa: E402
from services.project_analyzer.doc_writer import EscritaNaoPermitidaError, EscritorSeguro  # noqa: E402
from services.project_analyzer.extractors import extrair_javascript, extrair_python  # noqa: E402
from services.project_analyzer.redactor import MARCADOR, ocultar_segredos  # noqa: E402
from services.project_analyzer.scanner import varrer_projeto  # noqa: E402

TOKEN_FALSO = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"


class RegistradorNulo:
    def log_assistente(self, *_):
        pass


class LLMFalso:
    """Simula o LocalLLMProvider: registra prompts e devolve JSON válido."""

    def __init__(self, falhar=False):
        self.prompts = []
        self.falhar = falhar

    def gerar_json(self, prompt_sistema, mensagem_usuario, historico=None):
        self.prompts.append(mensagem_usuario)
        if self.falhar:
            raise TimeoutError("ollama indisponível")
        if "grupo de arquivos" in prompt_sistema:
            return {"resumo": "Grupo de serviços."}
        if "descreva a arquitetura" in prompt_sistema:
            return {"visao_geral": "Aplicação de exemplo.", "padroes": ["Camada de serviços"],
                    "fluxo_principal": "app/main.py chama os serviços.", "decisoes": []}
        return {"responsabilidade": "Responsabilidade simulada.", "observacoes": []}


def escrever(raiz, rel, conteudo):
    caminho = Path(raiz) / rel
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_text(conteudo, encoding="utf-8")


def criar_projeto_pequeno(raiz):
    escrever(raiz, "app/main.py", '''"""Ponto de entrada."""
from services.db import Banco
from services import util
import requests

def main():
    Banco().salvar()

if __name__ == "__main__":
    main()
''')
    escrever(raiz, "services/__init__.py", "")
    escrever(raiz, "services/db.py", '''import sqlite3
from asyncio.windows_events import NULL

class Banco:
    """Acesso ao SQLite."""
    def salvar(self):
        conn = sqlite3.connect("x.db")
        conn.execute("CREATE TABLE IF NOT EXISTS itens (id INTEGER)")
        conn.commit()
        conn.close()
        return True
''')
    escrever(raiz, "services/util.py", f'''API_KEY = "{TOKEN_FALSO}"

def limpar(texto):
    texto = texto.strip()
    texto = texto.lower()
    texto = texto.replace("a", "b")
    return texto

def limpar_copia(texto):
    texto = texto.strip()
    texto = texto.lower()
    texto = texto.replace("a", "b")
    return texto
''')
    escrever(raiz, "services/quebrado.py", "def x(:\n    pass\n")
    escrever(raiz, "requirements.txt", "ollama>=0.1\npyaudio\n")
    escrever(raiz, "main.js", '''const { app, ipcMain } = require('electron');
const { spawn } = require('child_process');
const helper = require('./helper');
ipcMain.on('send-text', (e, t) => {});
function iniciar() { spawn('python', ['app/main.py']); }
''')
    escrever(raiz, "helper.js", "module.exports = {};\n")
    escrever(raiz, "package.json", json.dumps({"name": "x", "main": "main.js", "devDependencies": {"electron": "^31"}}))
    escrever(raiz, ".gitignore.txt", "*.db\n")
    escrever(raiz, "README.md", "Ver `app/main.py` e `services/inexistente.py`.\n")
    (Path(raiz) / "node_modules" / "lib").mkdir(parents=True)
    escrever(raiz, "node_modules/lib/index.js", "ignorado")
    (Path(raiz) / "dados.db").write_bytes(b"SQLite format 3\x00\x00")


def hashes_do_projeto(raiz):
    resultado = {}
    for pasta, _, arquivos in os.walk(raiz):
        for nome in arquivos:
            caminho = os.path.join(pasta, nome)
            with open(caminho, "rb") as f:
                resultado[os.path.relpath(caminho, raiz)] = hashlib.sha256(f.read()).hexdigest()
    return resultado


class BaseTeste(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="pa_teste_")
        self.projeto = os.path.join(self.tmp, "projeto_exemplo")
        self.saida = os.path.join(self.tmp, "Documentacao_Gerada")
        os.makedirs(self.projeto)
        criar_projeto_pequeno(self.projeto)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def analisador(self, llm=None):
        return ProjectAnalyzer(llm_provider=llm, pasta_saida=self.saida, nome_modelo="modelo-teste",
                               registrador=RegistradorNulo())

    def ler_doc(self, resultado, nome):
        return Path(resultado["pasta_saida"], nome).read_text(encoding="utf-8")


# =============================================================================
# UNIDADES
# =============================================================================

class TestExtracao(BaseTeste):
    def test_scanner_ignora_dependencias_e_binarios(self):
        var = varrer_projeto(self.projeto)
        caminhos = [a.caminho_relativo for a in var.arquivos]
        self.assertNotIn("node_modules/lib/index.js", caminhos)
        self.assertIn("node_modules", var.diretorios_ignorados)
        db = next(a for a in var.arquivos if a.caminho_relativo == "dados.db")
        self.assertFalse(db.texto)

    def test_python_ast(self):
        texto = Path(self.projeto, "services/db.py").read_text(encoding="utf-8")
        f = extrair_python("services/db.py", texto)
        self.assertEqual(f["classes"][0]["nome"], "Banco")
        self.assertIn("salvar", f["classes"][0]["metodos"])
        self.assertEqual(f["tabelas_sql"][0]["nome"], "itens")
        self.assertTrue(any(i["tipo"].startswith("Banco de dados relacional: SQLite") for i in f["integracoes"]))

    def test_python_import_tardio_e_google(self):
        f = extrair_python("x.py", "from google import genai\ndef f():\n    import edge_tts\n")
        tipos = {i["tipo"] for i in f["integracoes"]}
        self.assertIn("LLM em nuvem: Google Gemini (google-genai)", tipos)
        self.assertIn("Síntese de voz: Edge TTS", tipos)

    def test_python_erro_sintaxe(self):
        f = extrair_python("q.py", "def x(:\n")
        self.assertIsNotNone(f["erro_sintaxe"])

    def test_javascript_regex(self):
        texto = Path(self.projeto, "main.js").read_text(encoding="utf-8")
        f = extrair_javascript("main.js", texto)
        self.assertEqual(f["ipc"][0]["canal"], "send-text")
        self.assertIn("iniciar", [fn["nome"] for fn in f["funcoes"]])
        self.assertTrue(f["processos"])

    def test_ocultar_segredos(self):
        texto, n = ocultar_segredos(f'token = "{TOKEN_FALSO}"\nchave = os.getenv("GEMINI_API_KEY")')
        self.assertNotIn(TOKEN_FALSO, texto)
        self.assertIn(MARCADOR, texto)
        self.assertEqual(n, 1)
        self.assertEqual(ocultar_segredos('API_KEY = os.getenv("X")')[1], 0)


class TestComando(unittest.TestCase):
    def test_comandos(self):
        self.assertEqual(detectar_comando_projeto(r"analisar projeto E:\MOBA"), {"caminho": r"E:\MOBA"})
        self.assertEqual(detectar_comando_projeto(r'analise o projeto "E:\Agente IA\assistente-domestico"'),
                         {"caminho": r"E:\Agente IA\assistente-domestico"})
        self.assertEqual(detectar_comando_projeto("documentar o projeto /home/u/app."), {"caminho": "/home/u/app"})
        self.assertEqual(detectar_comando_projeto(r"Gerar documentação do projeto E:\MOBA"), {"caminho": r"E:\MOBA"})
        self.assertEqual(detectar_comando_projeto("analisar projeto"), {"caminho": None})

    def test_nao_e_comando(self):
        self.assertIsNone(detectar_comando_projeto("comprei 2 kg de arroz"))
        self.assertIsNone(detectar_comando_projeto("amanhã vou analisar o projeto com calma"))


class TestEscritaSegura(BaseTeste):
    def test_bloqueia_escrita_fora_da_saida(self):
        e = EscritorSeguro(self.saida)
        with self.assertRaises(EscritaNaoPermitidaError):
            e.escrever("../projeto_exemplo/app/main.py", "x")
        with self.assertRaises(EscritaNaoPermitidaError):
            e.escrever(os.path.join(self.projeto, "invasao.md"), "x")

    def test_preserva_anotacoes_manuais(self):
        e = EscritorSeguro(self.saida)
        e.escrever_documento("doc.md", "Doc", [("a", "versão 1")])
        caminho = Path(self.saida, "doc.md")
        caminho.write_text(caminho.read_text(encoding="utf-8") + "\nMinha anotação manual.\n", encoding="utf-8")
        e.escrever_documento("doc.md", "Doc", [("a", "versão 2")])
        texto = caminho.read_text(encoding="utf-8")
        self.assertIn("versão 2", texto)
        self.assertNotIn("versão 1", texto)
        self.assertIn("Minha anotação manual.", texto)


# =============================================================================
# ANÁLISE COMPLETA
# =============================================================================

class TestAnaliseCompleta(BaseTeste):
    def test_projeto_pequeno(self):
        antes = hashes_do_projeto(self.projeto)
        llm = LLMFalso()
        r = self.analisador(llm).analisar(self.projeto)

        self.assertEqual(hashes_do_projeto(self.projeto), antes, "o projeto analisado não pode ser modificado")
        self.assertTrue(r["llm_utilizado"])
        self.assertTrue(r["pasta_saida"].startswith(os.path.realpath(self.saida)))
        for nome in ("README.md", "01-visao-geral.md", "02-modulos.md", "03-dependencias-e-integracoes.md",
                     "04-problemas-encontrados.md", "05-divergencias-documentacao.md", "06-historico-de-alteracoes.md"):
            self.assertTrue(Path(r["pasta_saida"], nome).exists(), nome)

        problemas = self.ler_doc(r, "04-problemas-encontrados.md")
        self.assertIn("'requests' é importado no código", problemas)
        self.assertIn("Import exclusivo do Windows", problemas)
        self.assertIn("Código duplicado", problemas)
        self.assertIn(".gitignore.txt", problemas)
        self.assertIn("Erro de sintaxe", problemas)
        self.assertIn("Possível segredo exposto", problemas)
        self.assertIn("provável uso indireto", problemas)  # pyaudio

        divergencias = self.ler_doc(r, "05-divergencias-documentacao.md")
        self.assertIn("services/inexistente.py", divergencias)
        self.assertIn("`services/db.py`", divergencias)  # não citado na documentação

        modulos = self.ler_doc(r, "02-modulos.md")
        self.assertIn("Responsabilidade simulada. `INFERIDO`", modulos)
        self.assertIn("`Banco` (linha 4)", modulos)
        self.assertIn("`services/db.py`", modulos)

        deps = self.ler_doc(r, "03-dependencias-e-integracoes.md")
        self.assertIn("```mermaid", deps)
        self.assertIn("send-text", deps)
        self.assertIn("`itens`", deps)

    def test_segredo_nunca_sai_da_maquina_nem_vai_para_a_documentacao(self):
        llm = LLMFalso()
        r = self.analisador(llm).analisar(self.projeto)
        self.assertFalse(any(TOKEN_FALSO in p for p in llm.prompts))
        for pasta, _, arquivos in os.walk(r["pasta_saida"]):
            for nome in arquivos:
                self.assertNotIn(TOKEN_FALSO, Path(pasta, nome).read_text(encoding="utf-8"), nome)

    def test_llm_recebe_fatos_e_nao_codigo_bruto(self):
        llm = LLMFalso()
        self.analisador(llm).analisar(self.projeto)
        self.assertTrue(llm.prompts)
        self.assertTrue(all(len(p) <= 6000 for p in llm.prompts))
        self.assertFalse(any("conn.execute(" in p for p in llm.prompts))

    def test_incremental(self):
        llm = LLMFalso()
        a = self.analisador(llm)
        a.analisar(self.projeto)
        chamadas_iniciais = len(llm.prompts)

        r2 = a.analisar(self.projeto)
        self.assertEqual(len(llm.prompts), chamadas_iniciais, "nada mudou: o LLM não deve ser chamado")
        self.assertEqual(r2["arquivos_reanalisados"], 0)

        escrever(self.projeto, "services/db.py",
                 Path(self.projeto, "services/db.py").read_text(encoding="utf-8") + "\ndef nova_funcao():\n    return 1\n")
        r3 = a.analisar(self.projeto)
        self.assertEqual(r3["alteracoes"]["modificados"], ["services/db.py"])
        self.assertEqual(r3["arquivos_reanalisados"], 1)
        # 1 resumo do arquivo alterado + 1 síntese de arquitetura
        self.assertEqual(len(llm.prompts) - chamadas_iniciais, 2)
        historico = self.ler_doc(r3, "06-historico-de-alteracoes.md")
        self.assertIn("função nova_funcao", historico)

    def test_llm_indisponivel_gera_documentacao_deterministica(self):
        llm = LLMFalso(falhar=True)
        r = self.analisador(llm).analisar(self.projeto)
        self.assertFalse(r["llm_utilizado"])
        self.assertLessEqual(len(llm.prompts), 2, "após 2 falhas seguidas o LLM deve ser abandonado")
        self.assertIn("NÃO IDENTIFICADO", self.ler_doc(r, "01-visao-geral.md"))
        self.assertIn("requests", self.ler_doc(r, "04-problemas-encontrados.md"))

    def test_sem_llm(self):
        r = self.analisador(None).analisar(self.projeto)
        self.assertEqual(r["chamadas_llm"], 0)
        self.assertTrue(Path(r["pasta_saida"], "02-modulos.md").exists())

    def test_ganchos_de_vram(self):
        eventos = []
        a = ProjectAnalyzer(llm_provider=LLMFalso(), pasta_saida=self.saida, registrador=RegistradorNulo(),
                            preparar_modelo=lambda: eventos.append("preparar"),
                            liberar_modelo=lambda: eventos.append("liberar"))
        a.analisar(self.projeto)
        self.assertEqual(eventos, ["preparar", "liberar"])

    def test_caminho_invalido(self):
        with self.assertRaises(ProjetoInvalidoError):
            self.analisador().analisar(os.path.join(self.tmp, "nao_existe"))

    def test_saida_dentro_do_projeto_e_ignorada_na_varredura(self):
        saida_interna = os.path.join(self.projeto, "Documentacao_Gerada")
        a = ProjectAnalyzer(llm_provider=None, pasta_saida=saida_interna, registrador=RegistradorNulo())
        a.analisar(self.projeto)
        r = a.analisar(self.projeto)
        self.assertEqual(r["alteracoes"]["adicionados"], [], "a documentação gerada não pode ser analisada como projeto")

    def test_projeto_grande(self):
        grande = os.path.join(self.tmp, "grande")
        for i in range(500):
            escrever(grande, f"pacote{i % 20}/modulo_{i}.py",
                     f"from pacote{(i + 1) % 20} import modulo_{(i + 1) % 500}\n\n"
                     f"class Classe{i}:\n    def metodo(self):\n        return {i}\n\n"
                     f"def funcao_{i}(x):\n    return x * {i}\n")
        llm = LLMFalso()
        inicio = time.time()
        r = ProjectAnalyzer(llm_provider=llm, pasta_saida=self.saida, registrador=RegistradorNulo(),
                            max_caracteres_llm=6000).analisar(grande)
        duracao = time.time() - inicio
        self.assertEqual(r["arquivos_analisados"], 500)
        self.assertLess(duracao, 60)
        self.assertTrue(all(len(p) <= 6000 for p in llm.prompts))
        self.assertTrue(any("grupo" in p for p in llm.prompts), "projetos grandes usam resumos intermediários")


class TestProjetoReal(unittest.TestCase):
    """Analisa o próprio assistente doméstico (somente leitura)."""

    def test_assistente_domestico(self):
        tmp = tempfile.mkdtemp(prefix="pa_real_")
        try:
            antes = {p: h for p, h in hashes_do_projeto(ROOT_DIR).items()
                     if "__pycache__" not in p and not p.startswith(("Logs", ".git"))}
            r = ProjectAnalyzer(llm_provider=LLMFalso(), pasta_saida=tmp, registrador=RegistradorNulo()).analisar(str(ROOT_DIR))
            depois = {p: h for p, h in hashes_do_projeto(ROOT_DIR).items()
                      if "__pycache__" not in p and not p.startswith(("Logs", ".git"))}
            self.assertEqual(antes, depois)
            visao = Path(r["pasta_saida"], "01-visao-geral.md").read_text(encoding="utf-8")
            self.assertIn("LLM local: Ollama", visao)
            self.assertIn("app/main.py", visao)
            modulos = Path(r["pasta_saida"], "02-modulos.md").read_text(encoding="utf-8")
            self.assertIn("ShoppingAssistant", modulos)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestSemDependenciaExterna(unittest.TestCase):
    """A Skill não pode importar bibliotecas de rede nem SDKs de nuvem."""

    PROIBIDOS = {"requests", "httpx", "aiohttp", "urllib", "http", "socket", "ollama", "google", "openai",
                 "anthropic", "subprocess", "shutil"}

    def test_imports_do_pacote(self):
        pacote = ROOT_DIR / "services" / "project_analyzer"
        for arquivo in pacote.glob("*.py"):
            arvore = ast.parse(arquivo.read_text(encoding="utf-8"))
            for no in ast.walk(arvore):
                modulos = []
                if isinstance(no, ast.Import):
                    modulos = [a.name for a in no.names]
                elif isinstance(no, ast.ImportFrom) and no.level == 0:
                    modulos = [no.module or ""]
                for m in modulos:
                    self.assertNotIn(m.split(".")[0], self.PROIBIDOS, f"{arquivo.name} importa {m}")


if __name__ == "__main__":
    unittest.main()
