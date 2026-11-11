@echo off
rem Duplo clique: abre o instalador do BRASIL+ como administrador (o Windows vai pedir permissao).
powershell -NoProfile -Command "Start-Process powershell -Verb RunAs -ArgumentList '-NoProfile -ExecutionPolicy Bypass -NoExit -File ""%~dp0instalar-windows.ps1""'"
