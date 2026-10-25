@echo off
setlocal
cd /d "%~dp0"
title Hydra One
if "%~1"=="" (
  echo Usage: Hydra-Web.bat path-to-engine-config.json
  echo See docs\INSTALL.en.md or docs\INSTALL.it.md
  exit /b 2
)
"%~dp0.venv\Scripts\python.exe" -m serve.server --engine strata --config "%~f1" --host 127.0.0.1 --port 8090 --lazy --open
