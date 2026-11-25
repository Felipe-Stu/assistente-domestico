@echo off
title Atualizar o Electron
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set "SAIDA=%~dp0..\Planejamento\medicoes\electron-ultimo.txt"
echo Atualizacao do Electron - %date% %time% > "%SAIDA%"

echo == 1/3 Fechando o assistente (janela e servidor) ==
python scripts\desligar_assistente.py >> "%SAIDA%" 2>&1
timeout /t 3 >nul
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\fechar_assistente.ps1" >> "%SAIDA%" 2>&1
timeout /t 2 >nul

echo == 2/3 Instalando o Electron (pode levar alguns minutos) ==
call npm install >> "%SAIDA%" 2>&1
if errorlevel 1 (echo NPM: FALHOU >> "%SAIDA%") else (echo NPM: OK >> "%SAIDA%")

echo == 3/3 Versao instalada ==
call npx electron --version >> "%SAIDA%" 2>&1
type "%SAIDA%"
echo.
echo Pronto. Abra o assistente de novo pelo iniciar-assistente.bat.
pause
