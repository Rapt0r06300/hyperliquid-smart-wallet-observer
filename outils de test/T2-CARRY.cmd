@echo off
setlocal
cd /d "%~dp0.."
set "PYTHONPATH=%CD%\src;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   T2 - LE CARRY DELTA-NEUTRE : la jambe SPOT existe-t-elle seulement ?
REM   ASCII PUR, pas de "chcp" (cf. tools/garde_cmd_ascii.py).
REM
REM   LONG spot + SHORT perp, meme taille -> le prix s'annule, il ne reste que le funding.
REM   Encore faut-il qu'un marche SPOT existe, et qu'il soit assez epais pour monter la jambe.
REM
REM   Lecture seule. Endpoints /info PUBLICS. Aucune cle, aucune signature, aucun ordre.
REM ==================================================================================
python tools\mesurer_carry_neutre.py > "%~dp0rapports\t2_carry.txt" 2>&1
type t2_carry.txt
pause
