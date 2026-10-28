@echo off
chcp 65001 >nul
cd /d "%~dp0"
title Editor de Video IA

set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
  python --version >nul 2>nul && set "PY=python"
)
if not defined PY (
  echo.
  echo Python nao encontrado.
  echo Instale o Python 3.10 ou mais novo em https://www.python.org/downloads/
  echo e marque a opcao "Add python.exe to PATH" na instalacao.
  echo.
  pause
  exit /b 1
)

rem Modelos do Whisper e arquivos temporarios ficam dentro da pasta do editor (nao enchem o disco C)
set "HF_HOME=%~dp0modelos"
if not exist "%~dp0temp" mkdir "%~dp0temp"
set "TEMP=%~dp0temp"
set "TMP=%~dp0temp"

rem Se a pasta foi movida de lugar, o ambiente antigo pode nao funcionar: recria
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" -c "import flask" >nul 2>nul
  if errorlevel 1 (
    echo O ambiente do editor precisa ser recriado neste local...
    rmdir /s /q ".venv"
  )
)

if not exist ".venv\Scripts\python.exe" (
  echo Criando ambiente virtual...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo Falha ao criar o ambiente virtual.
    pause
    exit /b 1
  )
)

if not exist ".venv\.instalado_v2" (
  echo.
  echo Instalando dependencias. Isso so acontece na primeira vez e pode levar alguns minutos...
  echo.
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r requirements.txt
  if errorlevel 1 (
    echo.
    echo Falha na instalacao. Verifique a internet e rode o iniciar.bat de novo.
    pause
    exit /b 1
  )
  echo ok> ".venv\.instalado_v2"
)

echo.
echo Iniciando o editor. O navegador vai abrir sozinho.
".venv\Scripts\python.exe" app.py
echo.
pause
