@echo off
rem 启动心月狐桌宠（无控制台窗口）
setlocal
set "HERE=%~dp0"
set "PY=%DSH_HOME%\dsh-runtimes\dsh-primary-runtime\dependencies\python\pythonw.exe"
if not exist "%PY%" set "PY=%LOCALAPPDATA%\Programs\Python\Python312\pythonw.exe"
if not exist "%PY%" (
  echo [!] 找不到 pythonw.exe，请编辑本文件里的 PY 变量。
  pause
  exit /b 1
)
set "PYTHONUTF8=1"
start "" "%PY%" "%HERE%src\run_pet.py" %*
endlocal
