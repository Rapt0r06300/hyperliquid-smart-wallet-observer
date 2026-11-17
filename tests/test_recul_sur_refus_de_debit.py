"""UN REFUS DE DÉBIT NE DOIT PAS TUER UNE PASSE — sur AUCUN des trois sites.

LE DÉFAUT, MESURÉ DANS LA NUIT DU 16 AU 17/11/2026. Le rattrapage `--long` (budget 12 h) s'est
terminé en **1 h 29**. Sa passe `funding-profond` s'est arrêtée à la ronde 5, après **37 minutes**,
sur un unique `LIMITE_DEBIT` à 600 u/min — alors qu'il restait **334 minutes** de budget et
**9 872 jours-coins** à creuser :

```
[funding] R5   30/62 CAKE   + 499 points | remonte a 981 j | 36 min ecoulees, 334 restantes
[funding] ARRET : LIMITE_DEBIT -> la passe suivante reprend ici
```

Le correctif du 16/11 (« deux refus ne doivent pas tuer la passe » : recul géométrique, abandon
après `REFUS_AVANT_ABANDON` refus CONSÉCUTIFS) n'avait été posé que sur **un site sur trois** :

| site                         | avant le 17/11           |
|------------------------------|--------------------------|
| funding, front AVANT         | 5 refus avec recul  ✅   |
| funding, front de CREUSAGE   | arrêt au **1er** refus   |
| bougies                      | arrêt au **2e** refus    |

Une règle écrite à trois endroits finit par diverger : elle vit désormais dans `avec_recul`, que
les trois sites appellent. Et le helper ne rejoue JAMAIS une requête sans avoir d'abord attendu —
rejouer immédiatement après un 429 est exactement ce qui fait bannir.

Aucun réseau : le serveur est un double qui refuse N fois puis accepte.
"""
from __future__ import annotations

import importlib.util
import json
import urllib.error
from pathlib import Path

RACINE = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "bcv_recul", RACINE / "tools" / "backfill_candles_vaults.py")
BC = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(BC)

HEURE = 3_600_000
NOW = 1_790_000_000_000 // HEURE * HEURE


def _refus() -> urllib.error.HTTPError:
    return urllib.error.HTTPError("https://exemple.invalid", 429, "Too Many Requests", {}, None)


def _racine(tmp_path: Path, coins: list[str]) -> Path:
    (tmp_path / "config").mkdir(parents=True, exist_ok=True)
    (tmp_path / "config" / "copy_vault_coins.json").write_text(
        json.dumps({"coins": coins}), encoding="utf-8")
    return tmp_path


def _etat_funding(root: Path, *, recent: dict, ancien: dict) -> None:
    (root / "runtime" / "data").mkdir(parents=True, exist_ok=True)
    (root / BC.ETAT).write_text(json.dumps({
        "_schema": BC.SCHEMA_ETAT,
        "intervalles": {BC.SERIE_FUNDING: recent, BC.SERIE_FUNDING_ANCIEN: ancien}}),
        encoding="utf-8")


def _serveur_funding(refus_avant_succes: int, appels: list):
    """Refuse les `refus_avant_succes` premiers appels (429), puis sert un point par heure."""
    etat = {"refus": refus_avant_succes}

    def poster(coin, a, b):
        appels.append((coin, int(a), int(b)))
        if etat["refus"] > 0:
            etat["refus"] -= 1
            raise _refus()
        return [{"coin": coin, "fundingRate": "0.00001", "premium": "0.0002", "time": t}
                for t in range(int(a), int(b) + 1, HEURE)][:BC.PAGE_FUNDING]
    return poster


# ─────────────────────── le helper : la règle, à un seul endroit ───────────────────────
class _Cadence:
    def __init__(self):
        self.refus_vus = 0

    def refus(self):
        self.refus_vus += 1


def test_un_premier_resultat_SAIN_ne_declenche_aucun_nouvel_appel():
    appels, siestes, cadence = [], [], _Cadence()
    resultat, refus = BC.avec_recul(("ok", None), lambda: appels.append(1) or ("ko", "LIMITE_DEBIT"),
                                    erreur_de=lambda r: r[1], cadence=cadence, dormir=siestes.append)
    assert resultat == ("ok", None) and refus == 0
    assert appels == [] and siestes == [] and cadence.refus_vus == 0


def test_le_helper_ATTEND_avant_chaque_nouvel_essai_et_de_plus_en_plus():
    """Rejouer immédiatement après un 429 est ce qui fait bannir : l'attente précède l'essai."""
    journal: list[str] = []
    reponses = iter([("x", "LIMITE_DEBIT"), ("x", "LIMITE_DEBIT"), ("ok", None)])

    def appel():
        journal.append("appel")
        return next(reponses)

    cadence = _Cadence()
    resultat, refus = BC.avec_recul(("x", "LIMITE_DEBIT"), appel, erreur_de=lambda r: r[1],
                                    cadence=cadence,
                                    dormir=lambda s: journal.append(f"dort {s:g}"))
    assert resultat == ("ok", None)
    assert refus == 3 and cadence.refus_vus == 3, "chaque refus doit faire reculer le debit"
    attente = BC.ATTENTE_REFUS_S
    assert journal == [f"dort {attente:g}", "appel", f"dort {2 * attente:g}", "appel",
                       f"dort {3 * attente:g}", "appel"], (
        "l'ordre doit etre : dormir PUIS appeler, avec une attente qui s'allonge")


def test_le_helper_renonce_apres_REFUS_AVANT_ABANDON_refus_consecutifs():
    appels: list[int] = []

    def appel():
        appels.append(1)
        return ("x", "LIMITE_DEBIT")

    resultat, refus = BC.avec_recul(("x", "LIMITE_DEBIT"), appel, erreur_de=lambda r: r[1],
                                    cadence=_Cadence(), dormir=lambda s: None)
    assert resultat[1] == "LIMITE_DEBIT"
    assert refus == BC.REFUS_AVANT_ABANDON
    assert len(appels) == BC.REFUS_AVANT_ABANDON, "ni plus ni moins d'essais que la regle"


# ─────────────── site 2 : le front de CREUSAGE, celui qui a tué la passe du 17/11 ───────────────
def test_le_front_de_CREUSAGE_survit_a_des_refus_passagers(tmp_path):
    """Le défaut exact : un seul refus arrêtait le creusage avec 334 minutes de budget."""
    root = _racine(tmp_path, ["BTC"])
    _etat_funding(root, recent={"BTC": NOW - HEURE}, ancien={"BTC": NOW - 200 * 24 * HEURE})
    appels: list = []
    bilan = BC.passe_funding(root, now_ms=NOW, poster=_serveur_funding(3, appels),
                             dormir=lambda s: None, univers=None,
                             profondeur_ms=260 * 24 * HEURE)
    assert bilan["arret"] != "LIMITE_DEBIT", (
        "trois refus passagers ne doivent PAS arreter le creusage")
    assert bilan["creuses"] >= 1, "le coin doit avoir ete creuse malgre les refus"
    etat = json.loads((root / BC.ETAT).read_text(encoding="utf-8"))["intervalles"]
    assert (NOW - int(etat[BC.SERIE_FUNDING_ANCIEN]["BTC"])) / (24 * HEURE) > 200.0


def test_le_front_de_CREUSAGE_renonce_quand_la_venue_reste_fermee(tmp_path):
    """L'arrêt doit rester possible : une venue durablement fermée ne doit pas boucler."""
    root = _racine(tmp_path, ["BTC"])
    _etat_funding(root, recent={"BTC": NOW - HEURE}, ancien={"BTC": NOW - 200 * 24 * HEURE})
    appels: list = []
    bilan = BC.passe_funding(root, now_ms=NOW, poster=_serveur_funding(10_000, appels),
                             dormir=lambda s: None, univers=None,
                             profondeur_ms=260 * 24 * HEURE)
    assert bilan["arret"] == "LIMITE_DEBIT"
    assert bilan["refus_consecutifs"] == BC.REFUS_AVANT_ABANDON
    # et l'etat n'a PAS bouge : aucune profondeur n'est inventee sur un refus
    etat = json.loads((root / BC.ETAT).read_text(encoding="utf-8"))["intervalles"]
    assert int(etat[BC.SERIE_FUNDING_ANCIEN]["BTC"]) == NOW - 200 * 24 * HEURE


# ─────────────── site 3 : la passe des bougies, qui renonçait au 2e refus ───────────────
def _serveur_bougies(refus_avant_succes: int, appels: list):
    etat = {"refus": refus_avant_succes}

    def poster(coin, intervalle, a, b):
        appels.append((coin, intervalle, a, b))
        if etat["refus"] > 0:
            etat["refus"] -= 1
            raise _refus()
        pas = BC.INTERVALLES_MS[intervalle]
        premier = -(-a // pas) * pas
        return [{"t": t, "T": t + pas - 1, "s": coin, "i": intervalle, "o": "100", "c": "101",
                 "h": "102", "l": "99", "v": "5"} for t in range(premier, b + 1, pas)]
    return poster


def test_la_passe_des_BOUGIES_survit_a_TROIS_refus_passagers(tmp_path):
    """Avant : arrêt au deuxième refus. Trois refus passagers doivent être absorbés."""
    root = _racine(tmp_path, ["BTC"])
    appels: list = []
    bilan = BC.passe(root, intervalles=("1h",), now_ms=NOW + 1_234_567,
                     poster=_serveur_bougies(3, appels), dormir=lambda s: None, univers={"BTC"})
    assert bilan["arret"] is None, "trois refus passagers ne doivent pas arreter la passe"
    assert (root / BC.SORTIES["1h"]).is_file(), "les bougies doivent avoir ete ecrites"


def test_la_passe_des_BOUGIES_renonce_et_le_DIT_quand_la_venue_reste_fermee(tmp_path):
    root = _racine(tmp_path, ["BTC"])
    appels: list = []
    bilan = BC.passe(root, intervalles=("1h",), now_ms=NOW + 1_234_567,
                     poster=_serveur_bougies(10_000, appels), dormir=lambda s: None,
                     univers={"BTC"})
    assert bilan["arret"] == "LIMITE_DEBIT"
    assert bilan["refus_consecutifs"] == BC.REFUS_AVANT_ABANDON
    assert not (root / BC.SORTIES["1h"]).is_file() or not (
        root / BC.SORTIES["1h"]).read_text(encoding="utf-8").strip(), (
        "aucune bougie ne doit etre inventee sur un refus")


def test_les_TROIS_sites_passent_par_le_meme_helper():
    """Une règle écrite à trois endroits diverge : la preuve en a été faite en production."""
    import inspect

    assert inspect.getsource(BC.passe_funding).count("avec_recul(") == 2, (
        "les DEUX fronts du funding doivent appeler le helper")
    assert inspect.getsource(BC.passe).count("avec_recul(") == 1
