@echo off
title Assistente Domestico - DEMONSTRACAO
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
rem I07: dados ficticios, banco separado e outra porta (o servidor real pode continuar ligado)
set ASSISTENTE_DEMO=1
set API_PORTA=8766
python scripts\criar_demo.py
if exist "node_modules\.bin\electron.cmd" goto abrir
call npm install
:abrir
call npm start
