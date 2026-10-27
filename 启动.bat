@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "APP=%~dp0E学院试题格式互转.py"
set "PYW=%~dp0.venv\Scripts\pythonw.exe"

if exist "%APP%" goto :findpy
echo.
echo 未找到主程序：%APP%
pause
exit /b 1

:findpy
if exist "%PYW%" (
    start "" "%PYW%" "%APP%"
    exit /b 0
)

where pythonw >nul 2>nul
if errorlevel 1 goto :nopython
start "" pythonw "%APP%"
exit /b 0

:nopython
echo.
echo 未检测到可用的 Python 运行环境。
echo 请先安装 Python 3.9 及以上版本，并执行：
echo     pip install PyQt6 python-docx pywin32
echo.
pause
exit /b 1
