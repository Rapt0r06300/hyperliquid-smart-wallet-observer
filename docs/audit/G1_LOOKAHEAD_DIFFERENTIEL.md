# G1 — La recherche 150 M lit-elle le futur ? Non. Et le garde-fou qu'on voulait brancher n'aurait rien prouvé.

> Mesuré le 2026-07-13 sur **4 000 candidats réels × 12 scénarios de la vraie grille**.
> Code : `src/hl_observer/backtesting/lookahead_differential.py`. Tests :
> `tests/test_lookahead_differential.py` (10 verts). Outil : `G1-LOOKAHEAD.cmd`.

## L'accusation, et pourquoi elle était mal posée

G1 disait : *« le garde-fou lookahead n'est pas branché sur la recherche 150 M »*. **C'est vrai
comme fait de câblage.** `assert_no_lookahead` n'est importé que par des tests et
`tools/audit_report.py`.

Mais avant de le brancher, une question : **qu'aurait-il vérifié ?**

`backtest/no_lookahead_guard.py` contrôle des paires `(decision_ts, data_ts)` : il râle si une
décision utilise une donnée plus récente qu'elle. Or dans `scenario_search._eval_pairs`, la
décision d'entrée ne lit **que des champs du candidat** — `edge_remaining_bps`, `signal_age_ms`,
`liquidity_score`, `consensus_wallets`, `leader_score`, `copy_degradation_bps` — tous horodatés à
`recorded_at`, **c'est-à-dire à l'instant même de la décision**.

`data_ts == decision_ts` par construction. **Le garde-fou serait passé trivialement, sur tous les
scénarios, toujours.**

> **Un garde-fou qui ne peut pas échouer ne garde rien.**

Le brancher aurait été du **théâtre** : on aurait coché « lookahead : OK » sans rien vérifier.
C'est exactement le faux confort qu'on chasse depuis le début — la capacité présente,
l'interrupteur allumé, et personne qui se plaint.

## Ce qu'on a fait à la place : torturer les données

La seule propriété qui compte, et qu'aucune inspection de timestamps ne peut donner :

> **La sélection d'entrée doit être INVARIANTE au futur.**

Si on change ce qui se passe **après** l'entrée, l'ensemble des candidats acceptés ne doit pas
bouger d'un iota. Le PnL, lui, doit bouger — c'est le résultat. Mais la **décision**, non.

On appelle donc la **vraie** fonction de sélection (`_eval_pairs`, le cœur de la recherche 150 M)
avec un futur détruit de trois façons — **sans jamais lire son code** :

| torture | ce qu'on fait | ce que ça prouve |
|---|---|---|
| **FUTUR_BROUILLÉ** | les marks postérieurs deviennent du bruit | si la sélection change → **elle a lu le futur** |
| **FUTUR_INVERSÉ** | le chemin futur est retourné (le prix fait l'inverse) | idem, et c'est le test le plus dur |
| FUTUR_EFFACÉ | les marks postérieurs sont supprimés | mesure la **survivance**, pas le lookahead |

Le passé, lui, reste **intact** — sinon on accuserait à tort tout sélecteur honnête.

## 🚩 Mon outil a crié « FUITE ». Il avait tort.

Premier passage : les 12 scénarios ressortaient « FUITE ». J'ai failli conclure que tous les
résultats de recherche étaient à jeter.

**Mon détecteur était binaire là où il fallait distinguer.** Il criait dès qu'*une* torture faisait
bouger la sélection. Or les trois ne disent pas la même chose :

- **BROUILLÉ / INVERSÉ** : le futur *existe* mais il *ment*. Si la sélection change, elle l'a **lu**.
  C'est du lookahead. **Fatal.**
- **EFFACÉ** : le futur *n'existe plus*. La sélection change forcément — sans prix futur, il n'y a
  **pas de PnL à mesurer** (`simulate_exit_on_path` rend `None`). Ce n'est pas de la triche, c'est
  de la **mesurabilité**.

**Une fausse alarme fait jeter un résultat valide. C'est aussi grave qu'un faux OK.** Le détecteur
distingue maintenant les deux, et un test le vérifie
(`test_le_detecteur_NE_CONFOND_PAS_survivance_et_lookahead`).

## Le résultat

| | FUTUR_BROUILLÉ | FUTUR_INVERSÉ | FUTUR_EFFACÉ |
|---|---|---|---|
| **12 scénarios / 4 000 candidats** | **OK** | **OK** | change (80–86 %) |

### 1. Lookahead : **NON**

On peut **brouiller** le futur, ou même l'**inverser** — faire faire au prix exactement le
contraire de ce qu'il a fait. **La recherche accepte exactement les mêmes candidats.** Elle ne le
lit pas.

> **Conséquence : « 0 config robuste sur 150 M » n'est PAS un artefact de lookahead. Ce résultat
> tient.** La cause est ailleurs — voir H-181 (*on teste les configs qui sur-ajustent le plus*).

Et le détecteur **sait** attraper une fuite : on lui donne un tricheur explicite (« n'accepte que
les trades gagnants »), et il l'épingle. Un détecteur qui ne dit jamais « fuite » ne détecte rien.

### 2. Survivance : **84 %**

**84 % des candidats acceptés disparaissent si on efface le futur.** La recherche ne juge que les
signaux qui ont *eu la chance* d'être suivis par un mark. Les marchés peu marqués sont
silencieusement absents.

Ce n'est pas du lookahead — mais c'est un **biais réel**, et il fallait le chiffrer plutôt que de
le laisser dans l'ombre.

**Atténuation** : le filtre est **scénario-indépendant** et s'applique à l'identique au train
**et** au test. Il ne peut donc pas fabriquer un faux gagnant hors échantillon — il rétrécit
l'univers, il ne le déforme pas en faveur d'une config.

## ⚠️ Ce que ce test ne couvre pas

Il prouve que la **recherche** ne lit pas le futur. Il ne peut **pas** savoir si un champ du
candidat a été calculé avec de l'information future **au moment de l'enregistrement**. Cette
question appartient au collecteur, pas au backtest.

Un test ne peut pas prouver ce qu'il ne voit pas, et prétendre le contraire serait exactement le
mensonge qu'on essaie d'éviter.

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
