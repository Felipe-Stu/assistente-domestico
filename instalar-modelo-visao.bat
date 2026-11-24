@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul

where ollama >nul 2>&1
if errorlevel 1 (
  echo [ERRO] Ollama nao encontrado. Instale em https://ollama.com/download
  goto fim
)

rem Ollama em execucao? Se nao, inicia e espera ate 60 s
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
echo Baixando o modelo de leitura de imagens qwen2.5vl:7b (cerca de 6 GB)...
ollama pull qwen2.5vl:7b
if errorlevel 1 (
  echo [ERRO] Nao consegui baixar. Confira a internet e rode de novo.
  goto fim
)
echo.
echo [ok] Modelo instalado. Testando a leitura de imagens...
call testar-visao.bat
exit /b 0

:fim
pause
