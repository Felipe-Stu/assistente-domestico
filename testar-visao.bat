@echo off
cd /d "%~dp0"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
echo Testando o modelo de imagem... pode levar 1 a 2 minutos.
echo (sem arquivo arrastado, usa a imagem mais recente de Anexos)
python scripts\testar_visao.py "%~1"
echo.
echo Resultado salvo em Planejamento\medicoes\visao-ultima.txt
pause
