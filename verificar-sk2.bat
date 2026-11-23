@echo off
setlocal
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
title Verificacao: chaves (M01) e orquestrador pelo catalogo (SK2)
set "SAIDA=%~dp0..\Planejamento\medicoes"
if not exist "%SAIDA%" mkdir "%SAIDA%"
set "LOG=%SAIDA%\verificacao-ultima.txt"

echo ==============================================
echo  1/2 - Conferencia das chaves (nenhuma chave e exibida)
echo ==============================================
python scripts\conferir_chaves.py > "%LOG%" 2>&1
type "%LOG%"
echo.

echo ==============================================
echo  2/2 - Medicao do SK2 (Gemma, escolha da skill)
echo ==============================================
echo Resultado tambem em: %SAIDA%  (sk0-*.md e verificacao-ultima.txt)
echo.
call "%~dp0rodar-medicao-sk0.bat" --so-roteamento --modelos gemma4:e4b --modos atual
