@echo off
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
python scripts\conferir_chaves.py > "%~dp0..\Planejamento\medicoes\verificacao-ultima.txt" 2>&1
type "%~dp0..\Planejamento\medicoes\verificacao-ultima.txt"
timeout /t 15
