@echo off
chcp 65001 > nul
title BaroLab Memory Service (Port 8792)

echo ============================================================
echo   [BaroLab] 기억 그래프 (Vault) 로컬 서비스 시작
echo   주소: http://127.0.0.1:8792/memory.html
echo ============================================================

cd /d "%~dp0\.."
python -B -X utf8 -m server.memory_service --port 8792
pause
