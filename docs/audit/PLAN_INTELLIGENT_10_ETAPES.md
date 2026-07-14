# Plan intelligent en 10 étapes — améliorer scans, modules & rigueur (2026-07-10)

> **Cadrage honnête.** Ces étapes ne "règlent" pas le PnL en positif par du réglage — c'est prouvé
> impossible (1,4M calibrages → robust=0 ; l'oracle montre que le gain est un problème de *prédiction*,
> pas de *calibrage*). Elles rendent le système **meilleur, plus honnête, et sondent les seuls fronts
> qui restent**. Si un edge existe, ce plan le trouvera ; sinon, il le dira proprement. Zéro promesse.

## Les 10 étapes

**1. Acter le verdict de calibrage comme fondation.** Arrêter de re-tuner SL/TP et seuils de scan
(exhaustivement testé). C'est un *acquis*, pas un échec — ça libère l'énergie pour ce qui peut bouger.

**2. Instrumenter la latence bout-en-bout.** Mesurer précisément `timestamp fill leader → notre
décision`. La dégradation de copie (~13 bps) est le **seul** levier d'edge identifié ; on ne peut
l'attaquer que si on la mesure au millième. Livrable : un module de mesure + un histogramme de latence.

**3. Collecter l'historique de funding.** La seule avenue structurellement différente jamais testée
faute de données. L'enregistrer sur un run propre → la rendre backtestable avec `funding_arb_paper`.

**4. Ajouter la microstructure du carnet (L2 orderbook).** Aujourd'hui on n'a que les *mids*. Le vrai
edge d'exécution/market-making est dans le **bid/ask, la profondeur, le flux**. Collecter le L2 permet
des tests maker/MM *réalistes* (fin du "mid-touch = fill" optimiste).

**5. Explorer la prédiction comme RECHERCHE (le vrai frontier).** L'oracle prouve que le gain est dans
le *timing* de sortie = un problème de prédiction. Construire un petit modèle (features → proba de
mouvement favorable), testé en OOS strict + contre le hasard. **Attente honnête : ça échouera
probablement** (marché efficient) — mais c'est *le* seul endroit intellectuellement correct où chercher,
et on apprend énormément.

**6. Renforcer la validation.** Ajouter walk-forward multi-fenêtres + split par régime (vol haute/basse)
+ le **contrôle aléatoire systématique** dans chaque test. Chaque expérience devient une *preuve*.

**7. Backtester sur beaucoup plus de données.** 6h = trop court (survivorship). Collecter des semaines
de prix (incluant des crashes) pour que grid, réversion, momentum voient les *vrais* régimes.

**8. Construire un "harnais d'expérience" réutilisable.** Standardiser : toute idée = module pur + test
+ run OOS + contrôle aléatoire + rapport. On l'a fait à la main aujourd'hui ; en faire un pipeline.

**9. Documenter chaque expérience comme une étude.** Chaque test (copy, maker, grid, réversion, scan,
oracle) devient une page de recherche claire. C'est le **portfolio** ET la mémoire du projet.

**10. Définir un critère d'arrêt honnête, à l'avance.** Décider *maintenant* ce qui compterait comme
"edge réel" : net > 0 en OOS **ET** bat le hasard **ET** passe le Monte-Carlo **ET** tient sur plusieurs
régimes. Sans ce garde-fou écrit à l'avance, on chercherait indéfiniment un mirage. C'est l'étape la
plus importante — celle qui te protège de toi-même.

## Comment lire ce plan

- Étapes **2, 3, 4, 7** = *plus de vérité et de données* (les seuls carburants qui peuvent changer une
  conclusion).
- Étape **5** = le seul front avec une chance réelle (faible, honnête) d'un edge — et c'est de la
  recherche, pas du réglage.
- Étapes **1, 6, 8, 9, 10** = rigueur, méthode, portfolio, discipline anti-illusion.

**Ce que ce plan ne fait pas** : promettre un PnL positif. **Ce qu'il fait** : te donner la meilleure
chance *honnête* d'en trouver un s'il existe, te rendre meilleur quant à chaque étape, et t'empêcher de
te raconter des histoires. C'est ça, chercher intelligemment.
