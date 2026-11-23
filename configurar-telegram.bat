@echo off
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
echo Feche o assistente antes de continuar. Mande um "oi" ao seu bot no Telegram.
pause
python scripts\configurar_telegram.py
pause
