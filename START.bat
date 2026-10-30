@echo off
chcp 65001 >nul
title Smart Money Aggressive Bot
echo.
echo  ╔═══════════════════════════════════════╗
echo  ║   SMART MONEY AGGRESSIVE TRADING BOT  ║
echo  ╚═══════════════════════════════════════╝
echo.
cd /d "%~dp0"
node src/index.js
pause
