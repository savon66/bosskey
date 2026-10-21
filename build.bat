@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

echo [1/2] 正在打包...
python -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name BossKey --icon bosskey.ico --add-data "bosskey.ico;." bosskey.py
if errorlevel 1 (
  echo 打包失败：请确认已安装 pyinstaller 和 pillow、pystray
  exit /b 1
)

echo [2/2] 输出 exe...
if exist "dist\BossKey.exe" (
  copy /y "dist\BossKey.exe" "老板键.exe" >nul
  echo 完成：老板键.exe
) else (
  echo 未找到 dist\BossKey.exe
  exit /b 1
)
endlocal
