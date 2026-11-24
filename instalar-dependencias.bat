@echo off
title Instalar dependencias do assistente
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
echo == Instalando/atualizando as dependencias do Python (requirements.txt) ==
python -m pip install -r requirements.txt
echo.
echo == Atualizando requirements-lock.txt com as versoes instaladas ==
python scripts\fixar_versoes.py
pause
