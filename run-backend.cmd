@echo off
setlocal EnableExtensions

set "ROOT_DIR=%~dp0"
set "API_DIR=%ROOT_DIR%apps\api"
set "VENV_DIR=%API_DIR%\.venv"
set "VENV_PYTHON=%VENV_DIR%\Scripts\python.exe"

if not exist "%API_DIR%\requirements.txt" (
  echo [run-backend] Missing requirements file: "%API_DIR%\requirements.txt"
  exit /b 1
)

where py >nul 2>nul
if %ERRORLEVEL% EQU 0 (
  set "PYTHON_BOOTSTRAP=py -3"
) else (
  where python >nul 2>nul
  if %ERRORLEVEL% EQU 0 (
    set "PYTHON_BOOTSTRAP=python"
  ) else (
    echo [run-backend] Python was not found in PATH.
    exit /b 1
  )
)

if not exist "%VENV_PYTHON%" (
  echo [run-backend] Creating virtual environment...
  call %PYTHON_BOOTSTRAP% -m venv "%VENV_DIR%"
  if errorlevel 1 exit /b %ERRORLEVEL%
)

echo [run-backend] Syncing Python dependencies...
call "%VENV_PYTHON%" -m pip install --upgrade pip
if errorlevel 1 exit /b %ERRORLEVEL%

if not defined WEATHER_ENABLE_BERT_EXTRACTOR set "WEATHER_ENABLE_BERT_EXTRACTOR=false"
if not defined WEATHER_BERT_MODEL set "WEATHER_BERT_MODEL=dslim/bert-base-NER"
if not defined WEATHER_BERT_MIN_SCORE set "WEATHER_BERT_MIN_SCORE=0.5"

call "%VENV_PYTHON%" -m pip install -r "%API_DIR%\requirements.txt"
if errorlevel 1 exit /b %ERRORLEVEL%

if /I "%WEATHER_ENABLE_BERT_EXTRACTOR%"=="1" goto :install_bert
if /I "%WEATHER_ENABLE_BERT_EXTRACTOR%"=="true" goto :install_bert
if /I "%WEATHER_ENABLE_BERT_EXTRACTOR%"=="yes" goto :install_bert
if /I "%WEATHER_ENABLE_BERT_EXTRACTOR%"=="on" goto :install_bert
goto :after_bert

:install_bert
echo [run-backend] Installing optional BERT extractor dependencies...
call "%VENV_PYTHON%" -m pip install -r "%API_DIR%\requirements-bert.txt"
if errorlevel 1 exit /b %ERRORLEVEL%

:after_bert

if /I "%NO_START%"=="1" (
  echo [run-backend] Dependency sync completed. Skipping server start because NO_START=1.
  exit /b 0
)

echo [run-backend] Starting FastAPI with auto-reload...
pushd "%ROOT_DIR%"
if defined PYTHONPATH (
  set "PYTHONPATH=%ROOT_DIR%src;%PYTHONPATH%"
) else (
  set "PYTHONPATH=%ROOT_DIR%src"
)
call "%VENV_PYTHON%" -m uvicorn glass_box_chat.main:app --host 0.0.0.0 --port 8000 --reload
set "EXIT_CODE=%ERRORLEVEL%"
popd

exit /b %EXIT_CODE%