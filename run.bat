@echo off
TITLE Pro Algo Bot Baslatici
COLOR 0A

echo ===================================================
echo 🚀 PRO ALGO BOT SISTEMI BASLATILIYOR...
echo ===================================================
echo.

:: 1. ADIM: Backend API (Python Motoru) Başlatılıyor
echo [1/3] Backend API (api.py) aciliyor...
start "Backend Motoru (Python)" cmd /k "python api.py"

:: Biraz bekle ki Backend kendine gelsin
timeout /t 3 /nobreak >nul

:: 2. ADIM: Frontend (React Ekranı) Başlatılıyor
echo [2/3] React Frontend (npm start) aciliyor...
start "React Ekrani" cmd /k "cd frontend && npm start"

:: React'in derlenmesi için biraz bekle
timeout /t 5 /nobreak >nul

:: 3. ADIM: Streamlit (Ana Kumanda) Başlatılıyor
echo [3/3] Streamlit Paneli aciliyor...
start "Streamlit Kumanda" cmd /k "streamlit run main.py"

echo.
echo ===================================================
echo ✅ TUM SISTEMLER AKTIF!
echo ⚠️  Kapatmak icin acilan pencereleri kapatabilirsin.
echo ===================================================
pause