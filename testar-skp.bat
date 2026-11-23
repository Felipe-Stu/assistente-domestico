@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
title SKP - Claude, biblioteca e Qwen
echo ==============================================
echo  SKP - teste do Claude (API), biblioteca e Qwen local
echo ==============================================
echo.
findstr /b /c:"ANTHROPIC_API_KEY=" .env >nul 2>&1
if errorlevel 1 (
    echo [AVISO] Nao ha a linha ANTHROPIC_API_KEY= no .env. O teste roda so com o Qwen local.
    echo         Para usar o Claude, crie a chave em https://console.anthropic.com e cole no .env.
    echo.
)
ollama list >nul 2>&1
if errorlevel 1 (
    echo Iniciando o Ollama...
    start "Ollama" /min ollama serve
    timeout /t 8 /nobreak >nul
)
python scripts\testar_skp.py
echo.
pause
