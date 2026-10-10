@echo off
rem NeoTV - ilk kurulum: yalnizca BIR KEZ (veya guncelleme sonrasi) calistir.
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo [1/6] Sanal ortam olusturuluyor...
  python -m venv .venv || (echo [HATA] Python bulunamadi. python.org'dan kurun. & pause & exit /b 1)
)
set PY=.venv\Scripts\python.exe
echo [2/6] Python paketleri kuruluyor...
"%PY%" -m pip install -q --upgrade pip
rem Kilitli kurulum: CI ile birebir ayni surumler; --only-binary: kaynaktan derleme denenmez.
"%PY%" -m pip install -q --only-binary=:all: --require-hashes -r requirements-dev.lock || goto :hata
echo [3/6] .env hazirlaniyor (Redis gerektirmeyen yerel mod)...
"%PY%" -m tools.devctl init-env --local-dev || goto :hata
echo [4/6] Veritabani yedeklenip guncelleniyor...
"%PY%" -m tools.devctl migrate || goto :hata
echo [5/6] Yonetici hesabi (kullanici adi: admin)...
"%PY%" -m tools.devctl create-admin --username admin --skip-existing || goto :hata
echo [6/6] Arayuz paketleri kuruluyor...
pushd frontend && call npm ci && popd || goto :hata
"%PY%" -m tools.devctl doctor
echo.
echo KURULUM TAMAM. Artik her gun sadece Baslat.bat dosyasina cift tikla.
pause & exit /b 0
:hata
echo [HATA] Yukaridaki kirmizi mesaji kopyalayip Claude'a gonder.
pause & exit /b 1
