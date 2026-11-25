@echo off
title Assistente Domestico - servidor (sem janela)
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
echo == Servidor do assistente (para o celular e o painel, sem abrir a janela do PC) ==
curl -s -o nul http://localhost:11434/api/tags
if errorlevel 1 start "Ollama" /min ollama serve
echo Deixe esta janela aberta. Ctrl+C encerra.
python -u app\servidor.py
pause
