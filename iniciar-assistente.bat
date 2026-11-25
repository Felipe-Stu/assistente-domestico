@echo off
title Assistente Domestico
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
echo == Assistente Domestico ==

rem 1. Ollama (IA local): abre se nao estiver rodando
curl -s -o nul http://localhost:11434/api/tags
if not errorlevel 1 goto ollama_ok
echo Abrindo o Ollama...
if exist "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe" goto abrir_app
start "Ollama" /min ollama serve
goto esperar
:abrir_app
start "" "%LOCALAPPDATA%\Programs\Ollama\ollama app.exe"
:esperar
set /a tentativas=0
:esperar_ollama
timeout /t 2 /nobreak >nul
curl -s -o nul http://localhost:11434/api/tags
if not errorlevel 1 goto ollama_ok
set /a tentativas+=1
if %tentativas% lss 15 goto esperar_ollama
echo AVISO: o Ollama nao respondeu. O assistente abre, mas a IA local fica indisponivel.
goto iniciar
:ollama_ok
echo Ollama em execucao.

:iniciar
rem 2. Bibliotecas do servidor (V5.5): instala na primeira vez
python -c "import starlette, uvicorn, sse_starlette, multipart" >nul 2>&1
if errorlevel 1 (
  echo Instalando as bibliotecas novas do servidor (so desta vez^)...
  python -m pip install -r requirements.txt
)

rem 3. Dependencias do Electron (so na primeira vez)
if exist "node_modules\.bin\electron.cmd" goto abrir
echo Instalando dependencias do Electron...
call npm install

:abrir
rem 4. Abre o assistente (o Electron sobe o servidor; o bot do Telegram e a fila de ideias iniciam junto)
echo Abrindo o assistente. Deixe esta janela aberta (pode minimizar); fechar o assistente encerra tudo.
call npm start
