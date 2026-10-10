@echo off
rem NeoTV - gunluk baslatma: cift tikla, kapatmak icin bu pencerede Ctrl+C.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [HATA] .venv bulunamadi. Once Kurulum.bat dosyasini calistir.
  pause & exit /b 1
)
rem Sunucular ayaga kalkinca tarayiciyi ac (8 sn sonra).
start "" cmd /c "timeout /t 8 >nul & start http://127.0.0.1:5173"
".venv\Scripts\python.exe" start.py
pause
