@echo off
chcp 65001 >nul
cd /d "%~dp0"

:: ==========================================
:: 文字宽度因子（SHX 字体），可按需修改
:: ==========================================
set STYLE_WIDTH=0.65

python translate_menu.py --style-width %STYLE_WIDTH%
