@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8

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
echo [ERRO] O Ollama nao respondeu em 60 s.
goto fim

:ollama_ok
ollama list | findstr /i /c:"qwen2.5vl:7b" >nul
if errorlevel 1 (
  choice /c SN /m "O modelo qwen2.5vl:7b (bom em ler texto de imagem, cerca de 6 GB) nao esta instalado. Baixar agora"
  if not errorlevel 2 ollama pull qwen2.5vl:7b
)
echo.
echo Comparando gemma3:4b e qwen2.5vl:7b na nota mais recente de Anexos (2 a 4 minutos)...
python scripts\testar_visao.py --modelos gemma3:4b,qwen2.5vl:7b
echo.
echo Resultado salvo em Planejamento\medicoes\visao-ultima.txt

:fim
pause
