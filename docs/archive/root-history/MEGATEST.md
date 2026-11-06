# MEGATEST — HyperSmart Observer

**2026-07-12 21:17:16 Paris, Madrid (heure d’été)** · mode `rapide` · 8/8 sections executees

> **100 % LECTURE SEULE.** 0 ordre reel · 0 argent reel · 0 cle privee · 0 signature · 0 depot/retrait. Aucun endpoint d'execution n'est appele par ce rapport.

Reseau Hyperliquid : **joignable** — OK — 232 marches perp visibles

## Synthese

| # | Controle | Nature | Statut | Verdict | Duree |
|---|---|---|---|---|---|
| 1 | **Garde ASCII des .cmd — cmd.exe ne doit pas executer ses commentaires** | 🔒 bloquant | `OK` | — | 1 s |
| 2 | **Audit code + suite de tests complete** | 🔒 bloquant | `OK` | — | 564 s |
| 3 | **Pourquoi le bot n'ouvre aucune position** | mesure | `OK` | 🟠 Le Bot N'Est Pas Casse | 0 s |
| 4 | **Seuil de funding du Grinder — atteignable ?** | mesure | `OK` | 🟠 Quasi-Mort | 1 s |
| 5 | **Carnet L2 — le market making a-t-il de l'espace ?** | mesure | `OK` | 🔴 Aucun Marche Ne Survit | 1 s |
| 6 | **Carry delta-neutre — la jambe spot existe-t-elle ?** | mesure | `OK` | 🟠 Spot_Trop_Mince | 2 s |
| 7 | **Diagnostic brut du marche SPOT (anti-chiffre-impossible)** | mesure | `OK` | — | 1 s |
| 8 | **Cimetiere — les hypotheses deja tuees par une mesure** | mesure | `OK` | — | 0 s |

> **`ECHEC` ≠ verdict rouge.** Un `ECHEC` veut dire que le CODE est casse (seul l'audit peut en produire un : c'est la seule section bloquante). Un `VERDICT(code=N)` veut dire que le MARCHE a repondu non — ce n'est pas une panne, et ca n'interdit pas de commiter.

### ✅ Aucun echec technique — commit autorise.

*Attention : « aucun echec technique » ne veut PAS dire « le bot gagne de l'argent ». Un verdict 🔴 ci-dessus (ex. « aucun marche ne survit ») est une REPONSE mesuree, pas une panne.*

---

## 1. Garde ASCII des .cmd — cmd.exe ne doit pas executer ses commentaires

*Un seul octet non-ASCII dans un .cmd, combine a un `chcp`, DECALE l'analyseur de cmd.exe : il perd des octets, saute des REM, et EXECUTE les commentaires. Ce bug est revenu 3 fois (2026-07-12 : "'5001' n'est pas reconnu" en boucle = chcp 65001 ampute de son 6). BLOQUANT : si le .cmd qui lance l'audit se sabote, plus rien n'est verifie.*

- statut : `OK` · code retour : `0` · duree : 0.9 s
- commande : `python tools/garde_cmd_ascii.py .`

```text
==============================================================================
  GARDE ASCII DES .cmd -- un octet non-ASCII fait executer les commentaires
==============================================================================
  propres  : 21
  a risque : 2  (non-ASCII, mais pas de chcp -> mojibake seulement)
  CASSES   : 0  (non-ASCII + chcp -> cmd execute n'importe quoi)

  [a risque] LANCER_HYPERSMART.cmd  (3 lignes non-ASCII, pas de chcp)
  [a risque] tools\run_pipeline.cmd  (1 lignes non-ASCII, pas de chcp)

  OK : aucun .cmd ne peut faire executer ses commentaires.
```

## 2. Audit code + suite de tests complete

*33 controles : syntaxe, imports, secrets, execution reelle, planchers fail-open, modules sans test, couverture fichier par fichier, suite pytest. C'est le SEUL controle bloquant : les autres mesurent le MARCHE, celui-ci mesure le CODE.*

- statut : `OK` · code retour : `0` · duree : 563.8 s
- commande : `python tools/audit_report.py`

```text
+==========================================================================+
| AUDIT HYPERSMART -- lecture seule / paper. Aucun ordre reel possible.    |
| 168 controles.   Duree estimee : ~8m08s                                  |
+--------------------------------------------------------------------------+
| Le rapport est REECRIT APRES CHAQUE CONTROLE.                            |
| Meme si tu fermes la fenetre, resultat-audit.md sera la.                 |
+==========================================================================+


  [----------------------------]   0.0%   [  1/168]   ecoule     0s   reste ~ 8m08s
      ... compile
    [OK   ] 1. Syntaxe : compilation de tout le code
        1866 fichiers, 0 erreur(s)   (4s)

  [----------------------------]   0.8%   [  2/168]   ecoule     4s   reste ~ 8m04s
      ... imports
    [OK   ] 2. Imports : tous les modules du toolkit
        61 modules, 0 casse(s)   (0.4s)

  [----------------------------]   0.9%   [  3/168]   ecoule     5s   reste ~ 8m04s
      ... all imports
    [OK   ] 3. Import de CHAQUE module du projet (pas juste le toolkit)
        795 modules importes, 0 casse(s)   (1s)

  [----------------------------]   1.2%   [  4/168]   ecoule     7s   reste ~ 8m02s
      ... circular
    [OK*  ] 4. Imports circulaires
        887 modules, 2 cycle(s)   (1s)

  [----------------------------]   1.5%   [  5/168]   ecoule     8s   reste ~ 8m01s
      ... arity
    [OK   ] 5. Signatures des appels inter-modules (mauvais branchements)
        6551 appels (38 ignores: depaquetage), 0 probleme(s)   (2s)

  [#---------------------------]   1.9%   [  6/168]   ecoule    11s   reste ~ 7m59s
      ... dead imports
    [OK*  ] 6. Imports inutilises (code mort)
        50 import(s) inutilise(s)   (3s)

  [#---------------------------]   2.5%   [  7/168]   ecoule    14s   reste ~ 7m56s
      ... n
    [OK*  ] 7. Imports a l'interieur de fonctions (souvent un contournement de cycle)
        131 occurrence(s) -- signe d'une dependance circulaire   (0.3s)

  [#---------------------------]   2.6%   [  8/168]   ecoule    15s   reste ~ 7m56s
      ... n
    [OK   ] 8. `from x import *` (pollue l'espace de noms, masque les erreurs)
        0 occurrence(s) -- on ne sait plus d'ou vient quoi   (0.3s)

  [#---------------------------]   2.6%   [  9/168]   ecoule    16s   reste ~ 7m55s
      ... empty files
    [OK   ] 9. Fichiers Python vides ou quasi vides
        0 fichier(s) vide(s)   (0.2s)

  [#---------------------------]   2.7%   [ 10/168]   ecoule    16s   reste ~ 7m55s
      ... init with logic
    [OK   ] 10. __init__.py contenant de la LOGIQUE (effets de bord a l'import)
        0 __init__ avec logique   (0.1s)

  [#---------------------------]   2.7%   [ 11/168]   ecoule    17s   reste ~ 7m55s
      ... duplicate module names
    [OK*  ] 11. Noms de modules DUPLIQUES entre paquets (confusion garantie)
        69 nom(s) duplique(s)   (0.1s)

  [#---------------------------]   2.8%   [ 12/168]   ecoule    18s   reste ~ 7m55s
      ... module docstrings
    [OK*  ] 12. Modules sans docstring (on ne sait pas a quoi ils servent)
        299 module(s) non documente(s)   (0.7s)

  [#---------------------------]   2.9%   [ 13/168]   ecoule    19s   reste ~ 7m54s
      ... type hints
    [OK*  ] 13. Taux de fonctions annotees (types)
        97% des fonctions sont annotees (3411/3522)   (1.0s)

  [#---------------------------]   3.1%   [ 14/168]   ecoule    20s   reste ~ 7m53s
      ... secrets
    [OK   ] 14. Scan de secrets (cle privee / seed / mnemonic)
        0 secret(s) reel(s) detecte(s)   (0.4s)

  [#---------------------------]   3.2%   [ 15/168]   ecoule    21s   reste ~ 7m53s
      ... no real exec
    [OK   ] 15. Aucun chemin d'execution reelle (hors tests/mocks)
        0 chemin(s) dangereux   (0.3s)

  [#---------------------------]   3.2%   [ 16/168]   ecoule    22s   reste ~ 7m52s
      ... n
    [OK   ] 16. Aucune librairie de signature/cle (eth_account, web3, coincurve...)
        0 occurrence(s) -- une lib de signature n'a RIEN a faire dans un bot paper   (0.3s)

  [#---------------------------]   3.3%   [ 17/168]   ecoule    23s   reste ~ 7m52s
      ... n
    [OK   ] 17. Aucune variable d'env de cle privee lue par le code
        0 occurrence(s) -- lire une cle = premier pas vers l'execution reelle   (0.3s)

  [#---------------------------]   3.4%   [ 18/168]   ecoule    24s   reste ~ 7m52s
      ... n
    [OK   ] 18. Aucune URL d'execution (endpoint /exchange)
        0 occurrence(s) -- l'endpoint d'ordre reel ne doit exister nulle part   (0.3s)

  [#---------------------------]   3.4%   [ 19/168]   ecoule    25s   reste ~ 7m51s
      ... n
    [OK   ] 19. Aucun wallet-connect
        0 occurrence(s) -- aucun moyen de signer pour agir   (0.3s)

  [#---------------------------]   3.5%   [ 20/168]   ecoule    26s   reste ~ 7m51s
      ... n
    [OK   ] 20. Aucun subprocess shell=True (injection de commande)
        0 occurrence(s) -- injection de commande possible   (0.2s)

  [#---------------------------]   3.6%   [ 21/168]   ecoule    27s   reste ~ 7m51s

   [...] 697 lignes coupees [...]

        200 combinaisons testees, 0 signe(s) faux   (0.0s)

  [####------------------------]  14.7%   [161/168]   ecoule  2m17s   reste ~ 6m57s
      ... fuzz costs never help
    [OK   ] 161. PROPRIETE : les frais ne peuvent JAMAIS augmenter le PnL (200 trades)
        200 trades, 0 anomalie(s)   (0.0s)

  [####------------------------]  14.7%   [162/168]   ecoule  2m18s   reste ~ 6m56s
      ... all modules have public api
    [OK   ] 162. Chaque module du toolkit expose au moins une fonction publique
        0 module(s) sans API publique   (0.1s)

  [####------------------------]  14.7%   [163/168]   ecoule  2m18s   reste ~ 6m56s
  >>> ETAPE LONGUE (~3m24s). NE FERME PAS, NE FAIS PAS CTRL-C.
  >>> Le rapport est deja sur le disque : tu ne perdras rien.
      ... tests
   >>> PARTIE LONGUE (2 a 6 min). NE FERME PAS, NE FAIS PAS CTRL-C.
   >>> Le rapport est deja sur le disque : tu ne perdras rien.
   >>> Un test bloque > 180s est tue et signale (il ne peut plus figer l'audit).
   (sous coverage -> couverture fichier par fichier en prime)
   | ============================= test session starts =============================
   | rootdir: C:\Users\flo\Desktop\Projet invest
      [###-------------------------]  11%   ecoule 10s   reste ~1m20s   << ca AVANCE, ne ferme pas
      [#####-----------------------]  17%   ecoule 20s   reste ~1m37s   << ca AVANCE, ne ferme pas
      [#######---------------------]  25%   ecoule 30s   reste ~1m30s   << ca AVANCE, ne ferme pas
      [#########-------------------]  32%   ecoule 40s   reste ~1m25s   << ca AVANCE, ne ferme pas
      [##########------------------]  37%   ecoule 50s   reste ~1m25s   << ca AVANCE, ne ferme pas
      [############----------------]  44%   ecoule 1m00s   reste ~1m16s   << ca AVANCE, ne ferme pas
      [#############---------------]  47%   ecoule 1m10s   reste ~1m18s   << ca AVANCE, ne ferme pas
      [##############--------------]  50%   ecoule 1m20s   reste ~1m20s   << ca AVANCE, ne ferme pas
      [###############-------------]  52%   ecoule 1m30s   reste ~1m23s   << ca AVANCE, ne ferme pas
      [################------------]  56%   ecoule 1m40s   reste ~1m18s   << ca AVANCE, ne ferme pas
      [###################---------]  68%   ecoule 1m50s   reste ~51s   << ca AVANCE, ne ferme pas
      [####################--------]  70%   ecoule 2m00s   reste ~51s   << ca AVANCE, ne ferme pas
      [####################--------]  70%   ecoule 2m10s   reste ~55s   << ca AVANCE, ne ferme pas
      [####################--------]  70%   ecoule 2m20s   reste ~1m00s   << ca AVANCE, ne ferme pas
      [####################--------]  70%   ecoule 2m30s   reste ~1m04s   << ca AVANCE, ne ferme pas
      [####################--------]  70%   ecoule 2m40s   reste ~1m08s   << ca AVANCE, ne ferme pas
      [####################--------]  70%   ecoule 2m50s   reste ~1m12s   << ca AVANCE, ne ferme pas
      [####################--------]  72%   ecoule 3m00s   reste ~1m10s   << ca AVANCE, ne ferme pas
      [######################------]  80%   ecoule 3m10s   reste ~47s   << ca AVANCE, ne ferme pas
      [###########################-]  98%   ecoule 3m20s   reste ~4s   << ca AVANCE, ne ferme pas
   | ============================== warnings summary ===============================
   | ============== 3251 passed, 22051 warnings in 202.34s (0:03:22) ===============
    [OK   ] 163. Suite de tests complete
        ============== 3251 passed, 22051 warnings in 202.34s (0:03:22) ===============   (3m27s)

  [################------------]  57.2%   [164/168]   ecoule  5m47s   reste ~ 3m29s
      ... coverage
    [OK*  ] 164. Couverture de tests REELLE, fichier par fichier
        couverture globale 84% | 97 fichier(s) a 0%   (4s)

  [################------------]  58.1%   [165/168]   ecoule  5m52s   reste ~ 3m24s
      ... critical coverage
    [OK*  ] 165. Couverture des paquets CRITIQUES (risk, paper_trading, edge, signals)
        6 fichier(s) critique(s) sous 60% de couverture   (0.0s)

  [################------------]  58.2%   [166/168]   ecoule  5m52s   reste ~ 3m24s
      ... slow tests
    [OK   ] 166. Tests LENTS (> 5s) -- ralentissent chaque audit
        0 test(s) lent(s)   (0.0s)

  [################------------]  58.2%   [167/168]   ecoule  5m53s   reste ~ 3m24s
  >>> ETAPE LONGUE (~3m28s). NE FERME PAS, NE FAIS PAS CTRL-C.
  >>> Le rapport est deja sur le disque : tu ne perdras rien.
      ... flaky
   | ============================= test session starts =============================
   | rootdir: C:\Users\flo\Desktop\Projet invest
      [###-------------------------]  11%   ecoule 10s   reste ~1m20s   << ca AVANCE, ne ferme pas
      [#####-----------------------]  17%   ecoule 20s   reste ~1m37s   << ca AVANCE, ne ferme pas
      [########--------------------]  28%   ecoule 30s   reste ~1m17s   << ca AVANCE, ne ferme pas
      [#########-------------------]  33%   ecoule 40s   reste ~1m21s   << ca AVANCE, ne ferme pas
      [##########------------------]  37%   ecoule 50s   reste ~1m25s   << ca AVANCE, ne ferme pas
      [############----------------]  44%   ecoule 1m00s   reste ~1m16s   << ca AVANCE, ne ferme pas
      [#############---------------]  47%   ecoule 1m10s   reste ~1m18s   << ca AVANCE, ne ferme pas
      [###############-------------]  52%   ecoule 1m20s   reste ~1m13s   << ca AVANCE, ne ferme pas
      [###############-------------]  52%   ecoule 1m30s   reste ~1m23s   << ca AVANCE, ne ferme pas
      [#################-----------]  60%   ecoule 1m40s   reste ~1m06s   << ca AVANCE, ne ferme pas
      [###################---------]  68%   ecoule 1m50s   reste ~51s   << ca AVANCE, ne ferme pas
      [####################--------]  70%   ecoule 2m00s   reste ~51s   << ca AVANCE, ne ferme pas
      [####################--------]  70%   ecoule 2m10s   reste ~55s   << ca AVANCE, ne ferme pas
      [####################--------]  70%   ecoule 2m20s   reste ~1m00s   << ca AVANCE, ne ferme pas
      [####################--------]  70%   ecoule 2m30s   reste ~1m04s   << ca AVANCE, ne ferme pas
      [####################--------]  70%   ecoule 2m40s   reste ~1m08s   << ca AVANCE, ne ferme pas
      [####################--------]  70%   ecoule 2m50s   reste ~1m12s   << ca AVANCE, ne ferme pas
      [####################--------]  72%   ecoule 3m00s   reste ~1m10s   << ca AVANCE, ne ferme pas
      [######################------]  80%   ecoule 3m10s   reste ~47s   << ca AVANCE, ne ferme pas
      [############################]  99%   ecoule 3m20s   reste ~2s   << ca AVANCE, ne ferme pas
   | ============================== warnings summary ===============================
   | ============== 3251 passed, 22051 warnings in 201.88s (0:03:21) ===============
    [OK   ] 167. Tests flaky (2e passe : meme resultat ?)
        0 test(s) flaky   (3m24s)

  [############################]  99.9%   [168/168]   ecoule  9m19s   reste ~    0s
      ... doctor
    [OK   ] 168. Doctor (sante du runtime)
        doctor OK   (2s)

+==========================================================================+
| [############################] 100%   TERMINE en 9m23s                   |
+--------------------------------------------------------------------------+
| Controles reussis ..............  168 / 168                              |
| ECHECS BLOQUANTS ...............    0                                    |
| Echecs non bloquants ...........    0                                    |
| Avertissements a regarder ...... 1531                                    |
+--------------------------------------------------------------------------+
| RAPPORT : resultat-audit.md  (a la racine du projet)                     |
+==========================================================================+

   >>> Envoie `resultat-audit.md` a Claude : il contient TOUT le detail.
```

## 3. Pourquoi le bot n'ouvre aucune position

*Confronte l'edge MESURE (table de calibration, prix reels) au cout aller-retour reel. Repond a la seule question qui compte : le bot est-il casse, ou a-t-il raison de refuser ?*

- statut : `OK` · code retour : `0` · duree : 0.4 s
- commande : `python tools/pourquoi_zero_position.py`

```text
==============================================================================
  POURQUOI LE BOT N'OUVRE AUCUNE POSITION ?
==============================================================================

  Verrou d'edge empirique : ACTIF
  Cout aller-retour reel  : 13.0 bps (taker Hyperliquid 4,5 bps x2 + spread + slippage)
  Table mesuree le        : 2026-07-11T20:53:30+00:00
  Source                  : runtime/replay/_archive/run_20260709_152414

     fraicheur du signal       n   edge MESURE   apres couts   verdict
  ---------------------- ------- ------------- -------------   ------------------------
                  5-15 s     302        -2.17b       -15.17b   refuse (edge < couts)
                 15-60 s    1582        -0.56b       -13.56b   refuse (edge < couts)
                60-300 s    1688        -0.23b       -13.23b   refuse (edge < couts)

  --------------------------------------------------------------------------
  >>> LE BOT N'EST PAS CASSE. IL A RAISON.
  --------------------------------------------------------------------------

  Toutes les bandes de fraicheur mesurees donnent un edge NEGATIF. Apres un ordre de
  whale, le prix ne va nulle part -- ni dans son sens, ni contre. Et chaque aller-retour
  coute 13 bps.

  Chaque position qu'il n'ouvre pas est de l'argent qu'il ne perd pas.

  Ce que ca ne dit PAS : que le systeme est inutile. Ca dit que LE COPY-TRADING n'a pas
  d'edge. La piste ouverte aujourd'hui est le carnet L2 (encaisser le spread au lieu de
  le payer) -- elle ne parie sur aucune prediction, et elle n'a jamais ete mesuree.

  Carnet L2 collecte : 9543 releves dans 4 fichier(s). La mesure est possible.
```

## 4. Seuil de funding du Grinder — atteignable ?

*Le verrou d'entree du funding-arb exige 2,5 bps/h. Hyperliquid paie a l'HEURE (le repo d'origine visait une place qui paie aux 8 h). Si le funding reel reste loin sous le seuil, le verrou est MORT : zero trade garanti par construction.*

- statut : `OK` · code retour : `0` · duree : 0.8 s
- commande : `python tools/measure_funding_gate.py`

```text
FUNDING HYPERLIQUID — instantané réel, 232 marchés
    médiane |funding|  :   0.1250 bps/heure
    90e centile        :   0.1250 bps/heure
    99e centile        :   1.8822 bps/heure
    maximum            :   5.5908 bps/heure

    SEUIL DU BOT       :   2.5000 bps/heure
    marchés qui passent : 1 / 232 (0.4 %)
    exemples            : CASHCAT

    VERDICT : QUASI-MORT — moins de 2 % des marchés franchissent le seuil

  ⚠  Un instantané ne prouve rien seul — le funding varie dans le temps.
     Pour trancher : HYPERSMART_RECORD_MICROSTRUCTURE=1 puis relire l'historique.
```

## 5. Carnet L2 — le market making a-t-il de l'espace ?

*Un MM gagne le spread et paie les frais. Chez Hyperliquid le maker PAIE 1,5 bps (aller-retour 3 bps). Si le spread median est 10x plus petit que les frais, le MM est arithmetiquement mort — quel que soit le reglage.*

- statut : `OK` · code retour : `0` · duree : 0.6 s
- commande : `python tools/mesurer_spread_carnet.py`

```text
9543 releves - 173 marches
  Cout aller-retour maker/maker : 3.0 bps
  Taille visee : $500  (il faut $2500 au carnet pour ne pas ETRE le carnet)

  coin          spread   profond.      net  toxicite   vol 24h  verdict
  ----------- -------- ---------- -------- --------- ---------  --------------------------------
  HMSTR          48.4b     36119$  +21.21b      1.0x      361k  DESERT ($361k/24h)
  PURR           42.3b       535$  +18.13b      0.0x      116k  DESERT ($116k/24h)
  CASHCAT        35.5b      2316$  +14.77b      0.6x     40.0M  TU ES le carnet (trop mince)
  NOT            26.1b     15462$  +10.07b      0.0x       32k  DESERT ($32k/24h)
  BOME           24.2b     21589$   +9.12b      0.0x       50k  DESERT ($50k/24h)
  USUAL          20.2b      6739$   +7.11b      1.6x      281k  DESERT ($281k/24h)
  MEME           18.0b     30716$   +6.00b      0.0x      193k  DESERT ($193k/24h)
  RSR            16.0b      6562$   +5.01b      0.1x       62k  DESERT ($62k/24h)
  TNSR           15.9b      2421$   +4.95b      0.5x      101k  DESERT ($101k/24h)
  XAI            14.2b     16541$   +4.11b      0.5x       63k  DESERT ($63k/24h)
  ACE            13.6b     13633$   +3.78b      0.5x       81k  DESERT ($81k/24h)
  DYM            12.7b      7830$   +3.35b      0.5x       87k  DESERT ($87k/24h)
  SKR            12.1b      3036$   +3.07b      0.7x      116k  DESERT ($116k/24h)
  TURBO          11.8b     26162$   +2.90b      0.0x      170k  DESERT ($170k/24h)
  KAITO          11.5b      3284$   +2.77b      0.6x      4.6M  DESERT ($4619k/24h)
  SUPER          11.4b      2465$   +2.72b      0.0x      124k  DESERT ($124k/24h)
  REZ            11.4b      6026$   +2.69b      0.8x      131k  DESERT ($131k/24h)
  FOGO           11.3b      3836$   +2.64b      0.7x       92k  DESERT ($92k/24h)
  MERL           11.1b      3834$   +2.53b      1.2x      203k  DESERT ($203k/24h)
  VINE           10.6b      4013$   +2.30b      0.7x      155k  DESERT ($155k/24h)
  RESOLV         10.4b      2608$   +2.19b      0.8x      200k  DESERT ($200k/24h)
  W              10.3b     15359$   +2.17b      1.0x      256k  DESERT ($256k/24h)
  GRIFFAIN        9.7b      3241$   +1.84b      0.6x      178k  DESERT ($178k/24h)
  AXS             9.0b      2691$   +1.49b      0.1x       83k  DESERT ($83k/24h)
  GOAT            8.7b      3158$   +1.37b      0.9x      111k  DESERT ($111k/24h)

  spread median global : 1.77 bps
  volume minimum exige : $5M / 24h
  survivants aux 3 filtres : 0 / 173 marches

  --------------------------------------------------------------------------
  >>> AUCUN MARCHE NE SURVIT. Ce n'est pas une panne, c'est une reponse.
  --------------------------------------------------------------------------
      Les spreads larges sont sur des marches DESERTS, des carnets vides, ou des
      prix qui te passent dessus. Les carnets profonds ont des spreads 10x plus
      petits que les frais. Le market making retail n'a pas d'espace ici.
```

## 6. Carry delta-neutre — la jambe spot existe-t-elle ?

*Le funding est le seul signal du projet a structure reelle (autocorrelation +0,70 a 1 h). Ce qui le tuait, c'est la jambe NUE (281 bps de prix subi pour 1 bps encaisse). Sans marche SPOT pour couvrir, la zone morte FUNDING_JAMBE_NUE reste fermee.*

- statut : `OK` · code retour : `0` · duree : 2.0 s
- commande : `python tools/mesurer_carry_neutre.py`

```text
Lecture des marches PERP et SPOT d'Hyperliquid (public, lecture seule)...
  232 perps - 296 marches spot - **8 coins ont LES DEUX**

  Coins couvrables : AZTEC, BERA, HYPE, MON, PUMP, PURR, STABLE, TRUMP

  Cout des DEUX jambes : 6 bps en maker, 18 bps en taker
  Plancher protocolaire Hyperliquid : 0,125 bps/h PERMANENT (11,6 %% APR au short).
  Il ne s'eteint pas. Les 6 bps sont rembourses en 48 h, puis c'est du portage pur.

  coin        funding/h      base    spot 24h  cout ent.     net 24h  verdict
  ---------- ---------- --------- ----------- ---------- -----------  ----------------------------------
  HYPE          +0.125b     -1.0b       34.3M      +7.0b      +83.0b  VIABLE -- rembourse en 57 h (2.4 j), puis portage pur -- 83.0 bps nets sur 30 jours
  AZTEC         +0.125b    +11.1b          0k      +0.0b          --  SPOT_TROP_MINCE_POUR_MONTER_LA_JAMBE
  PURR          +0.125b    +61.2b        219k      +0.0b          --  SPOT_TROP_MINCE_POUR_MONTER_LA_JAMBE
  STABLE        +0.125b    -15.6b          0k      +0.0b          --  SPOT_TROP_MINCE_POUR_MONTER_LA_JAMBE

  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!
  MAPPING PERP<->SPOT CASSE sur 4 coin(s) — ECARTE, PAS INTERPRETE :
      BERA       base = +2392875 bps  (impossible : > 2000 bps)
      MON        base = +39226 bps  (impossible : > 2000 bps)
      PUMP       base = +148163 bps  (impossible : > 2000 bps)
      TRUMP      base = +85471081 bps  (impossible : > 2000 bps)
  Ce n'est PAS une opportunite d'arbitrage : c'est un bug de lecture.
  Diagnostic : python tools/diagnostic_spot_hyperliquid.py
  !!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!!

  >>> 1 carry(s) delta-neutre(s) VIABLE(S). Gain cumule : 83.0 bps / 24 h.
      Sur 500 $ par paire : 4.15 $ / jour / paire en moyenne.
      ⚠️  ESTIMATION. Le spot Hyperliquid est MINCE : la liquidite affichee est
      une fraction du volume 24 h, pas une profondeur de carnet mesuree.
      Prochaine etape : lire le CARNET spot, pas seulement son volume.

  rapport : data\reports\carry_delta_neutre.json
```

## 7. Diagnostic brut du marche SPOT (anti-chiffre-impossible)

*Garde-fou : dumpe la structure reelle du payload spot. Existe parce que l'outil de carry a sorti « base HYPE = +177 721 383 bps ». Un chiffre impossible ne se commente pas, il se debogue. Ce controle empeche de conclure sur une mesure fausse.*

- statut : `OK` · code retour : `0` · duree : 1.2 s
- commande : `python tools/diagnostic_spot_hyperliquid.py`

```text
==============================================================================
  DIAGNOSTIC BRUT — SPOT HYPERLIQUID (on arrete de deviner)
==============================================================================

  tokens   : 471
  universe : 310 paires
  assetCtxs: 701       <-- si != universe, l'alignement zip() est FAUX

  CLES d'un token   : ['deployerTradingFeeShare', 'evmContract', 'fullName', 'index', 'isCanonical', 'name', 'szDecimals', 'tokenId', 'weiDecimals']
  CLES d'une paire  : ['index', 'isCanonical', 'name', 'tokens']
  CLES d'un ctx     : ['circulatingSupply', 'coin', 'dayBaseVlm', 'dayNtlVlm', 'markPx', 'midPx', 'prevDayPx', 'totalSupply']

  ECHANTILLON BRUT (paire 0) :
    universe[0] = {"tokens": [1, 0], "name": "PURR/USDC", "index": 0, "isCanonical": true}
    ctxs[0]     = {"prevDayPx": "0.091132", "dayNtlVlm": "218642.7406800002", "markPx": "0.092099", "midPx": "0.0924395", "circulatingSupply": "595201980.0698399544", "coin": "PURR/USDC", "totalSupply": "595201986.5926200151", "dayBaseVlm": "2405490.0"}

  --------------------------------------------------------------------------
  LES PAIRES SPOT DES COINS QUI DECIDENT
  --------------------------------------------------------------------------
  coin       paire                markPx        dayNtlVlm       ctx#
  ---------- ------------ -------------- ---------------- ----------
  PURR       PURR/USDC          0.092099 218642.7406800002          0
             (midPx = 0.0924395)
  TRUMP      @9                 0.000185              0.0          9
             (midPx = 0.000285)
  PUMP       @20              0.00009231              0.0         20
             (midPx = 0.00009245)
  HYPE       @107                0.15906       117.453125        105
             (midPx = 0.158825)
  BERA       @117               0.042242              0.0        115
             (midPx = 0.042305)
  MON        @129               0.027957       1.36122633        127
             (midPx = 0.027999)
  HYPE       @207                    1.0              0.0        197
  HYPE       @232                    3.0              0.0        218
  HYPE       @255               0.003793     579.07395083        240
             (midPx = 0.003787)
  STABLE     @258               0.023437     5694.5143028        243
             (midPx = 0.023383)
  AZTEC      @285                 580.99      1644.991486        269
             (midPx = 580.105)

  AUCUNE PAIRE SPOT pour : VINE, POL, LIT, ZRO, HEMI, APEX, ACE, SYRUP, SAGA, ZEC
  -> pour ces coins, la couverture spot sur Hyperliquid est IMPOSSIBLE.
     (ce n'est pas un bug de lecture : la paire n'existe pas)

  --------------------------------------------------------------------------
  LES 15 PLUS GROS MARCHES SPOT (par dayNtlVlm) — controle de bon sens
  --------------------------------------------------------------------------
  WOW        @109          vol24 =       34292904 $   markPx = 68.235
  NEKO       @144          vol24 =       13002253 $   markPx = 64144.0
  QUANT      @155          vol24 =        7899451 $   markPx = 1821.0
  BUDDY      @160          vol24 =        5283777 $   markPx = 77.523
  QQQ        @288          vol24 =        3971046 $   markPx = 542.24
  RUB        @173          vol24 =        1251124 $   markPx = 0.99939
  GLD        @276          vol24 =         736615 $   markPx = 329.79
  PURR       PURR/USDC     vol24 =         218643 $   markPx = 0.092099
  UZEC       @272          vol24 =         194777 $   markPx = 0.022942
  PUP        @223          vol24 =         175085 $   markPx = 0.091205
  WOULD      @198          vol24 =         146020 $   markPx = 0.0014602
  NBT        @245          vol24 =         109423 $   markPx = 0.99995
  USDT0      @166          vol24 =         101484 $   markPx = 0.15036
  RIVER      @301          vol24 =          85650 $   markPx = 0.004666
  FEUSD      @153          vol24 =          77718 $   markPx = 0.9998

  volume spot TOTAL 24 h : 67860744 $
  >>> Volume non nul : le champ `dayNtlVlm` est le bon. Les zeros affiches
      sont alors de VRAIS marches spot morts, pas une erreur de lecture.
```

## 8. Cimetiere — les hypotheses deja tuees par une mesure

*Le registre des zones mortes : chaque impasse deja payee, sa mesure, sa taille d'echantillon, et sa CONDITION DE REOUVERTURE. Une zone morte n'est pas un dogme — mais on ne re-paie pas deux fois la meme impasse.*

- statut : `OK` · code retour : `0` · duree : 0.1 s
- commande : `python tools/consulter_memoire.py`

```text
==============================================================================
  LE CIMETIERE — 7 hypotheses TUEES PAR UNE MESURE
==============================================================================

  [COPY_TRADING_NO_EDGE]  2026-07-11
     on croyait : Copier les fills des whales rapporte, si on filtre/regle assez bien.
     la mesure  : edge net median apres un fill de leader, hors echantillon = -7.97 bps  (sur 24 133 observations)
     verdict    : Le copy-trading n'a AUCUN edge, a AUCUN horizon.
     LECON      : Un score de wallet n'est pas un edge en bps. Un consensus n'est pas une preuve de rentabilite. MEME A COUT ZERO l'esperance reste negative : aucun reglage de seuil, de SL/TP, de filtre ou de hedge ne peut sauver un signal qui ne predit rien.
     rouvrir si : un mecanisme STRUCTURELLEMENT different (ex. acces au flux d'ordres AVANT execution, pas apres), ou une source de signal qui n'est pas le fill public d'un leader

  [LATENCE_NEST_PAS_LE_PROBLEME]  2026-07-11
     on croyait : Si on decidait plus vite (sub-seconde), l'edge de copie apparaitrait.
     la mesure  : edge median a 500 ms apres le fill du leader = -3.74 bps  (sur 15 571 observations)
     verdict    : La courbe edge/horizon est PLATE. Le probleme n'a jamais ete la latence.
     LECON      : Aller plus vite vers un signal qui ne dit rien fait perdre de l'argent plus vite. Un gain de fraicheur est un gain TECHNIQUE ; il ne devient economique que si la courbe edge/horizon montre un edge a ces horizons. Ici elle n'en montre a AUCUN.
     rouvrir si : des donnees a resolution < 100 ms sur un signal DIFFERENT du fill public

  [FUNDING_JAMBE_NUE]  2026-07-11
     on croyait : Encaisser un funding eleve rapporte, meme sans jambe de couverture.
     la mesure  : ratio median funding / bruit de prix, sur 232 marches = +0.0036 ratio  (sur 9 512 observations)
     verdict    : Le prix noie le funding d'un facteur ~281. Une jambe nue est un pari, pas un carry.
     LECON      : PIEGE CONTRE-INTUITIF : monter le seuil de funding ne filtre PAS le risque, il le CONCENTRE. Le funding est eleve PRECISEMENT la ou le marche est dangereux. Le gate a 2,5 bps/h ne laissait passer que CASHCAT... qui bouge de 219 bps/h.
     rouvrir si : une VRAIE jambe de couverture (spot ou perp oppose) qui annule le risque de prix -- un frais forfaitaire n'est PAS une couverture

  [EDGE_FABRIQUE]  2026-07-11
     on croyait : On peut deriver un edge en bps d'un score de consensus.
     la mesure  : constantes inventees dans la formule d'edge (45, 9, 0.55, 10, 25000) = +45 constante sans source  (sur 24 133 observations)
     verdict    : `dominance x 45 + bonus` n'a JAMAIS touche un prix. C'etait une fiction.
     LECON      : UN EDGE EST UN MOUVEMENT DE PRIX ATTENDU, MESURE. Pas un score de vote converti en bps par une constante. J'ai optimise un seuil, recalibre des SL/TP et lance un replay de 150 millions de scenarios SUR CE CHIFFRE -- sans jamais ouvrir la fonction qui le produisait. On optimise une fiction avec une grande rigueur.
     rouvrir si : jamais pour une formule inventee ; un edge doit venir d'une table MESUREE (runtime/calibration/empirical_edge.json)

  [BUS_GITHUB_EXTERNE]  2026-07-12
     on croyait : Lancer des profils de strategies GitHub comme moteurs donne un edge.
     la mesure  : profit factor net des 38 profils externes = +0.61 PF  (sur 810 observations)
     verdict    : PF net 0,61. Ecarte -- mais reste ALLUME dans le code pendant des semaines.
     LECON      : Un moteur abandonne doit etre eteint DANS LE CODE, pas dans les tetes. Son defaut etait `priority` : personne ne l'avait rallume, il n'avait jamais ete eteint. 810 evaluations pour 21 entrees reelles, dans le hot path.
     rouvrir si : une idee distillee A LA MAIN dans un module HyperSmart teste -- jamais du code upstream lance comme moteur autonome

  [MM_SUR_LES_MAJORS]  2026-07-12
     on croyait : On peut faire du market making sur BTC/ETH/SOL.
     la mesure  : spread median BTC contre cout aller-retour maker/maker (3,0 bps) = +0.16 bps de spread  (sur 1 363 observations)
     verdict    : Les frais maker sont 10 a 20x le spread. Arithmetiquement mort.
     LECON      : Chez Hyperliquid le maker PAIE 1,5 bps (pas de rebate avant les tiers institutionnels). Sur un carnet parfait, l'espace est nul : c'est le metier de gens avec des rebates et de la colocation. Le spread ne se capture pas la ou tout le monde le voit.
     rouvrir si : un tier de frais avec rebate maker negatif (>500 M$ de volume / 14 j) -- hors de portee ; ou un marche FIN avec du flux reel (mesure en cours)

  [CALIBRAGE_SLTP_OOS]  2026-07-09
     on croyait : Un meilleur reglage SL/TP peut rendre le PnL positif.
     la mesure  : nombre de configurations robustes sur holdout, sur 150 millions de scenarios = +0 configurations robustes  (sur 150 000 000 observations)
     verdict    : Aucun calibrage n'est positif hors echantillon. Le meilleur choix = NE PAS TRADER.
     LECON      : La boucle generer/tester/selectionner a PARFAITEMENT fonctionne : elle a correctement rapporte que rien ne survit hors echantillon. Une boucle de recherche ne PEUT PAS creer un edge qui n'existe pas. Il ne manquait pas la recherche, il manquait quelque chose qui vaille la peine d'etre cherche.
     rouvrir si : un SIGNAL d'entree different (pas un reglage de sortie) dont l'edge est mesure positif

==============================================================================
  Une zone morte n'est PAS un dogme : chacune dit ce qui la rouvrirait.
  Mais on ne re-paie pas une impasse deja payee.
==============================================================================
```

---

## Ce que ce rapport ne dit pas

- Il ne promet **aucun PnL positif**, et n'en promettra jamais.
- Un verdict vert sur l'audit signifie que le **code** est sain, pas que la **strategie** gagne.
- Les mesures reseau sont des **instantanes** : le funding, les spreads et la liquidite varient dans le temps. Un instantane ne tranche pas une question de regime.
