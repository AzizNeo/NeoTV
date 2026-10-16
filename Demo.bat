@echo off
rem NeoTV - tek komutla Docker demosu (Docker Desktop gerekir). Kurulum, .env veya Python gerekmez.
rem Durdurmak: docker compose -f compose.demo.yml down   (verileri silmek icin sonuna -v ekle)
cd /d "%~dp0"
where docker >nul 2>nul || (
  echo [HATA] Docker bulunamadi. Docker Desktop'i kur ve calistir: https://www.docker.com/products/docker-desktop/
  pause & exit /b 1
)
docker info >nul 2>nul || (
  echo [HATA] Docker calismiyor. Docker Desktop'i acip "Engine running" yazisini bekle, sonra tekrar dene.
  pause & exit /b 1
)
echo Demo hazirlaniyor... (ilk seferde imajlar indirilip derlenir: birkac dakika surebilir)
docker compose -f compose.demo.yml up --build --wait --wait-timeout 900 || (
  echo [HATA] Demo baslatilamadi. Ayrinti icin: docker compose -f compose.demo.yml logs
  pause & exit /b 1
)
docker compose -f compose.demo.yml logs --no-log-prefix setup
start "" http://localhost:8080
pause
