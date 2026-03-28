@echo off
setlocal
cd /d %~dp0
cd frontend

npm run dev -- --host 0.0.0.0 --port 5173 --strictPort
endlocal
