@echo off
title Instalar Claude Code
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set "CLAUDE_EXE=%USERPROFILE%\.local\bin\claude.exe"

echo == 1/3 Instalando o Claude Code (instalador oficial: claude.ai/install.ps1) ==
if exist "%CLAUDE_EXE%" (
    echo Ja instalado.
) else (
    powershell -NoProfile -ExecutionPolicy Bypass -Command "irm https://claude.ai/install.ps1 | iex"
)
if not exist "%CLAUDE_EXE%" (
    echo ERRO: claude.exe nao encontrado em %USERPROFILE%\.local\bin. Veja a mensagem acima.
    pause
    exit /b 1
)
"%CLAUDE_EXE%" --version

echo.
echo == 2/3 Login com a sua conta do Claude ==
set ANTHROPIC_API_KEY=
"%CLAUDE_EXE%" auth status >nul 2>&1
if errorlevel 1 (
    echo O navegador vai abrir. Entre com a SUA conta do Claude ^(a da assinatura^) e autorize.
    "%CLAUDE_EXE%" auth login
) else (
    echo Ja esta logado.
)

echo.
echo == 3/3 Teste do assistente com o Claude ==
python scripts\testar_claude_assinatura.py
echo.
echo Resultado salvo em Planejamento\medicoes\claude-assinatura-ultima.txt
pause
