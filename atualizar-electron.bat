@echo off
title Atualizar o Electron
cd /d "%~dp0"
chcp 65001 >nul
set "SAIDA=%~dp0..\Planejamento\medicoes\electron-ultimo.txt"
echo Atualizacao do Electron - %date% %time% > "%SAIDA%"
echo Feche o assistente antes de continuar.
pause
call npm install >> "%SAIDA%" 2>&1
if errorlevel 1 (echo NPM: FALHOU >> "%SAIDA%") else (echo NPM: OK >> "%SAIDA%")
call npx electron --version >> "%SAIDA%" 2>&1
type "%SAIDA%"
pause
