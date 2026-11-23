@echo off
rem Chay Arch Client tu source (Windows 10/11). Can Python 3.10+ (python.org, nho tick "Add to PATH").
cd /d "%~dp0"
where py >nul 2>nul && (set PY=py -3) || (where python >nul 2>nul && (set PY=python) || (set PY=))
if "%PY%"=="" (
  echo Khong tim thay Python 3. Cai Python 3.10+ tu https://www.python.org/downloads/ roi chay lai.
  pause
  exit /b 1
)
%PY% -c "import PyQt6.QtWidgets, PyQt6.QtSvg, requests, minecraft_launcher_lib.mod_loader" >nul 2>nul
if errorlevel 1 (
  echo Lan dau chay: dang cai thu vien, doi mot chut...
  %PY% -m pip install --upgrade -r requirements.txt
  if errorlevel 1 (
    echo Cai thu vien that bai. Kiem tra mang roi chay lai.
    pause
    exit /b 1
  )
)
rem pythonw = khong hien cua so console
where pyw >nul 2>nul && (start "" pyw -3 arch_laucher.py) || (start "" pythonw arch_laucher.py)
