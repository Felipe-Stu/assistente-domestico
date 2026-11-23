@echo off
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
python scripts\fixar_versoes.py > "%~dp0..\Planejamento\medicoes\fixar-versoes-ultima.txt" 2>&1
type "%~dp0..\Planejamento\medicoes\fixar-versoes-ultima.txt"
timeout /t 10
