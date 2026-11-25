@echo off
title Novo dispositivo do assistente
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set /p NOME="Nome do aparelho (ex.: Celular do Felipe): "
if "%NOME%"=="" set NOME=Celular
python scripts\dispositivos.py novo %NOME%
echo.
python scripts\dispositivos.py listar
pause
