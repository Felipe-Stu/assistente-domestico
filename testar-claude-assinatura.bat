@echo off
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
echo Conferindo o Claude Code (assinatura)...
python scripts\testar_claude_assinatura.py
echo.
echo Resultado salvo em Planejamento\medicoes\claude-assinatura-ultima.txt
pause
