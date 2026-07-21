@echo off
setlocal
cd /d "%~dp0"
set "PYTHONPATH=%~dp0src;%~dp0;%PYTHONPATH%"
set "PYTHONIOENCODING=utf-8"
set "PYTHONUTF8=1"
REM ==================================================================================
REM   MEGA-AUDIT DU MOISSONNEUR — tiendra-t-il VRAIMENT 12 h sans deriver ?
REM
REM   Flo : « est-ce que tu es sur qu'il va continuer a trouver pendant 12 h ? »
REM
REM   *** « Je suis sur » n'est pas une reponse. C'est une opinion deguisee en garantie. ***
REM
REM   Cet audit CALCULE :
REM     1. LE BUDGET      combien de requetes tiennent dans 12 h, vu les rythmes respectes
REM     2. L'OFFRE        combien de requetes on a AU DEPART
REM     3. LE BRANCHEMENT combien de NOUVELLES pistes une piste engendre, mesure sur du
REM                       VRAI texte. Si b > 1 la frontiere DIVERGE : elle ne peut pas se
REM                       vider. Si b < 1 elle S'ETEINT -- et il faut le savoir MAINTENANT.
REM     4. LA LAISSE      le taux de faux positifs sur du hors-sujet (les recettes de cuisine)
REM     5. LA COUVERTURE  cherche-t-il TOUT ce qui peut nous servir ?
REM     6. LES IDEES      chaque fiche dit-elle QUOI - POURQUOI - COMMENT - REFUTATION ?
REM
REM   Aucun reseau. Aucune moisson. ASCII PUR -> audit_moissonneur.txt
REM ==================================================================================
python tools\audit_moissonneur.py > audit_moissonneur.txt 2>&1
exit /b 0
