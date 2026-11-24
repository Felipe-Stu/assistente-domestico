@echo off
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
echo Medindo as consultas de gastos (M19) com o gemma4:e4b... cerca de 1 minuto.
python scripts\avaliar.py --so-consultas --modelos gemma4:e4b
echo.
echo Relatorio na pasta Planejamento\medicoes
pause
