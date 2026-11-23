@echo off
setlocal
cd /d "%~dp0"
title SK0 - medicao do assistente

echo ==============================================
echo  SK0 - medicao (escolha da skill, compras, troca de modelo)
echo ==============================================
echo.

where ollama >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Ollama nao encontrado. Instale em https://ollama.com/download
    goto fim
)

rem 1. Ollama em execucao? Se nao, inicia e espera ate 60 s
ollama list >nul 2>&1
if not errorlevel 1 goto ollama_ok
echo Iniciando o Ollama...
start "Ollama" /min ollama serve
set /a tentativas=0
:espera
timeout /t 2 /nobreak >nul
ollama list >nul 2>&1
if not errorlevel 1 goto ollama_ok
set /a tentativas+=1
if %tentativas% lss 30 goto espera
echo [ERRO] O Ollama nao respondeu em 60 s. Abra o Ollama manualmente e rode de novo.
goto fim

:ollama_ok
echo [ok] Ollama em execucao.

rem 2. Modelos: o teste pula os que faltarem; oferece baixar o qwen2.5:7b (cerca de 4,7 GB)
ollama list | findstr /i /c:"qwen2.5:7b" >nul
if errorlevel 1 (
    choice /c SN /m "O modelo qwen2.5:7b nao esta instalado (cerca de 4,7 GB). Baixar agora"
    if not errorlevel 2 ollama pull qwen2.5:7b
)

rem 3. Dependencia nova das skills
python -c "import yaml" >nul 2>&1
if errorlevel 1 (
    echo Instalando PyYAML...
    python -m pip install "PyYAML>=6.0"
)

rem 4. Medicao (15 a 20 min com tres modelos), com o progresso na tela
echo.
echo Rodando a medicao. Nao feche esta janela.
echo.
set PYTHONUNBUFFERED=1
python scripts\avaliar.py %*
set codigo=%errorlevel%
echo.
if %codigo%==0 (
    echo [ok] Medicao concluida. Relatorio na pasta Planejamento\medicoes ^(caminho acima^).
) else (
    echo [ERRO] A medicao terminou com codigo %codigo%.
)

:fim
echo.
pause
