@echo off
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
if "%~1"=="" (
  echo Arraste uma imagem de nota fiscal sobre este arquivo.
  pause
  exit /b 1
)
echo Testando o modelo de imagem com %~nx1 ... pode levar 1 a 2 minutos.
python scripts\testar_visao.py "%~1"
echo.
echo Resultado salvo em Planejamento\medicoes\visao-ultima.txt
pause
