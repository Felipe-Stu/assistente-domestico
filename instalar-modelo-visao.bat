@echo off
cd /d "%~dp0"
chcp 65001 >nul
echo Baixando o modelo de leitura de imagens gemma3:4b (cerca de 3,3 GB)...
ollama pull gemma3:4b
if errorlevel 1 (
  echo [ERRO] Nao consegui baixar. Confira se o Ollama esta aberto e a internet.
  pause
  exit /b 1
)
echo.
echo [ok] Modelo instalado. Testando a leitura de imagens...
call testar-visao.bat
