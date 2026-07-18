@echo off
chcp 65001 > nul
title Portal NF — Servidor
cd /d "%~dp0"
python server.py 8080
