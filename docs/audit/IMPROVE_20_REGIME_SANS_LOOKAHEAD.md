# IMPROVE-20 (#127) — le régime, et la mine de lookahead qu'il cachait (2026-07-13)

## 1. Le gate qui se dégradait en silence

`validation_gates.regime_robustness_gate` est le contrôle qui donne son sens au mot **« robuste »**
dans la recherche de scénarios (150 M). Sa promesse : *« le profit ne vient-il pas d'un seul régime
de marché chanceux ? »*

Son code cherchait un champ `regime` sur chaque trade :

```python
has_regime = any(isinstance(t, dict) and t.get("regime") for t in (trades or ()))
```

**Personne ne l'écrivait jamais.** Pire : `eval_trades` renvoie une **liste de floats**, pas de
dicts — la branche « régime » était donc **structurellement inatteignable**. Le gate retombait
*toujours* sur un découpage en tranches de temps… en s'appelant `regime_robustness`.

Conséquence directe : **IMPROVE-10 (« split par régime systématique, vol haute/basse »), marquée
*completed*, n'a jamais eu lieu.**

> Un nom qui promet un contrôle que le code ne fait pas est **pire** qu'un contrôle absent :
> il rassure.

C'est la 8ᵉ occurrence de la même maladie : *une capacité présente, un chaînon manquant, et
personne qui se plaint.*

## 2. La mine désamorcée en chemin

En voulant brancher `regime_detection` (Kalman, GARCH, CUSUM — tout ce code existe, testé, et
n'est appelé par personne), j'ai trouvé pire que le câblage mort :

**`garch11_variance` lit le futur. Deux fois.**

```python
var = sum(r * r for r in rs) / len(rs)   # (1) amorçage sur TOUTE la série — le futur inclus
for r in rs:
    var = omega + alpha * r * r + beta * var
    out.append(var)                      # (2) out[i] est calculé APRÈS avoir vu r[i]
```

La brancher naïvement aurait injecté du **lookahead dans le garde-fou anti-lookahead**.

Correctif : `garch11_variance_causale` — amorçage sur le *warmup* du passé, et on **émet** la
variance *avant* d'apprendre de `r[i]`. Les premières valeurs sont `None` : **« je ne sais pas »
est une information ; un chiffre inventé n'en est pas une.**

## 3. Le seuil aussi peut mentir

Séparer HAUTE_VOL / BASSE_VOL par la **médiane de tout l'échantillon** serait un lookahead plus
discret mais tout aussi réel : le seuil connaîtrait le test. `regime_label.seuil_depuis_le_train`
le calcule donc sur le **TRAIN seul**, et refuse (`None`) si le train est trop court.

## 4. Le test qui ne peut pas être trompé

Le test central est **différentiel** (méthode H-157) : il ne lit pas le code, il **change le futur**
et vérifie que le **passé ne bouge pas**.

```
test_LA_VERSION_HISTORIQUE_DE_GARCH_LIT_LE_FUTUR      -> le passé BOUGE  (elle triche)
test_LA_VERSION_CAUSALE_NE_LIT_PAS_LE_FUTUR           -> le passé TIENT  (elle est honnête)
```

Le premier test existe pour prouver que le second **sait dire non**. *Un garde-fou qui ne peut pas
échouer ne garde rien.*

## 5. Ce que j'ai changé — et ce que je n'ai PAS changé

| | |
|---|---|
| ✅ | `garch11_variance_causale` + docstring d'INTERDICTION sur la version ex-post |
| ✅ | `backtesting/regime_label.py` : labels causaux, seuil TRAIN-only, `INCONNU` jamais fabriqué |
| ✅ | `regime_robustness_gate` **DÉCLARE** son mode (`regime` vs `tranches_temporelles_FAUTE_DE_LABEL`) |
| ⛔️ | **Le pass/fail du gate est INCHANGÉ.** Je n'ai pas profité de la correction pour bouger un seuil. |
| ⚠️ | **PARTIAL_NOT_WIRED** : `regime_label` n'est pas encore consommé par `scenario_search` (tâche #595) |

Tant que le gate affiche `mode: tranches_temporelles_FAUTE_DE_LABEL`, « robuste » signifie
**robuste dans le TEMPS**, pas **robuste au RÉGIME**. Les deux sont utiles. Ce ne sont pas les mêmes.
La différence, désormais, est **écrite dans la sortie** au lieu d'être tue.

## 6. Résultat

```
tests/test_regime_label.py ........................ 8 passed
gates + regime + scenario_search (non-régression) . 17 passed
safety-audit ...................................... 8/8 ok
```

**Sécurité : 0 ordre réel · 0 argent réel · 0 clé privée · 0 signature · 0 dépôt/retrait.**
