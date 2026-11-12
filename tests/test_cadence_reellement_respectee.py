"""La cadence d'un collecteur doit être PRISE, pas seulement calculée.

Défaut réel du 2026-11-11 : ``Limiteur.attente()`` renvoie le délai à respecter, mais quatre
collecteurs l'appelaient sans dormir. Sur un seul passage du rattrapage des fills, 1 219 fenêtres
de dépôts/retraits sur 2 250 ont été refusées par l'API (HTTP 429)."""
from __future__ import annotations

import ast
import importlib.util
import sys
import urllib.error
from pathlib import Path

import pytest

RACINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RACINE / "src"))

from hl_observer.collection import collecte_fiable as CF  # noqa: E402


def test_patienter_dort_le_delai_du_et_pas_plus():
    limiteur, siestes = CF.Limiteur(2.0), []
    assert limiteur.patienter(siestes.append, maintenant=100.0) == 0.0 and siestes == []     # première action : prête
    assert limiteur.patienter(siestes.append, maintenant=100.5) == pytest.approx(1.5)
    assert siestes == [pytest.approx(1.5)]
    assert limiteur.patienter(siestes.append, maintenant=110.0) == 0.0 and len(siestes) == 1  # délai déjà écoulé
    assert CF.Limiteur(0.0).patienter(siestes.append, maintenant=1.0) == 0.0
    # tout objet qui ne sait que calculer un délai est servi aussi : la pause est prise à sa place
    from types import SimpleNamespace

    siestes.clear()
    assert CF.prendre_la_pause(SimpleNamespace(attente=lambda: 0.7), siestes.append) == 0.7 and siestes == [0.7]
    assert CF.prendre_la_pause(SimpleNamespace(attente=lambda: None), siestes.append) == 0.0 and siestes == [0.7]
    assert CF.prendre_la_pause(CF.Limiteur(0.0), siestes.append) == 0.0


def test_le_budget_de_debit_donne_la_pause_d_une_requete():
    assert CF.pause_pour_poids(CF.POIDS_REQUETE_INFO) == pytest.approx(12.0)       # 20 unités sur 100 par minute
    assert CF.pause_pour_poids(100.0) == pytest.approx(60.0) and CF.pause_pour_poids(0) == 0.0
    # deux rattrapages tournent en même temps : à eux deux, jamais plus du sixième de la limite (1 200)
    assert 2 * CF.BUDGET_POIDS_RATTRAPAGE_PAR_MINUTE <= 200.0


def test_aucun_collecteur_ne_calcule_une_pause_sans_la_prendre():
    """Garde durable : un appel ``x.attente()`` dont la valeur est jetée ne limite rien."""
    fautifs = []
    for dossier in (RACINE / "tools", RACINE / "src" / "hl_observer"):
        for chemin in sorted(dossier.rglob("*.py")):
            texte = chemin.read_text(encoding="utf-8", errors="replace")
            if "attente" not in texte:
                continue                                       # rien à analyser : le mot n'y figure pas
            try:
                arbre = ast.parse(texte)
            except SyntaxError:
                continue
            for noeud in ast.walk(arbre):
                appel = noeud.value if isinstance(noeud, ast.Expr) else None
                if isinstance(appel, ast.Await):
                    appel = appel.value
                if not isinstance(appel, ast.Call):
                    continue
                # x.attente() dont la valeur est jetée, ou to_thread(x.attente) / run_in_executor(..., x.attente)
                direct = isinstance(appel.func, ast.Attribute) and appel.func.attr == "attente"
                delegue = (isinstance(appel.func, ast.Attribute) and appel.func.attr in ("to_thread", "run_in_executor")
                           and any(isinstance(c, ast.Attribute) and c.attr == "attente" for c in appel.args))
                if direct or delegue:
                    fautifs.append(f"{chemin.relative_to(RACINE).as_posix()}:{noeud.lineno}")
    assert not fautifs, "pause calculée mais jamais prise (utiliser patienter()) : " + ", ".join(fautifs)


def _outil(nom: str):
    spec = importlib.util.spec_from_file_location(nom, RACINE / "tools" / f"{nom}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[nom] = module
    spec.loader.exec_module(module)
    return module


def test_le_rattrapage_des_depots_retraits_prend_sa_pause_et_reessaie_un_refus_de_debit(tmp_path, monkeypatch):
    outil = _outil("backfill_vault_fills")
    siestes: list[float] = []
    monkeypatch.setattr(outil.time, "sleep", siestes.append)
    monkeypatch.setattr(CF.time, "sleep", siestes.append)
    appels = {"n": 0}

    def poster(vault, a, b):
        appels["n"] += 1
        if appels["n"] == 2:                                   # un refus de débit, une fois
            raise urllib.error.HTTPError("u", 429, "Too Many Requests", None, None)
        return []

    lignes, audit = outil.backfill_ledger_un_vault_avec_audit(
        tmp_path, "0x" + "a" * 40, lookback_j=3, limiteur=CF.Limiteur(2.0), poster=poster)
    assert audit["requested_windows"] == 3 and audit["complete"] is True and audit["failed_windows"] == []
    assert appels["n"] == 4                                    # la fenêtre refusée a été redemandée une fois
    assert outil.ATTENTE_REFUS_DEBIT_S in siestes              # après avoir attendu
    # et la pause entre requêtes est réellement prise (l'horloge n'avance pas ici : les pauses dues s'allongent)
    assert sum(1 for s in siestes if 1.0 < s < outil.ATTENTE_REFUS_DEBIT_S) >= 2


def test_depots_retraits_fenetres_d_une_semaine_et_reponse_pleine_redemandee_plus_fin(tmp_path, monkeypatch):
    outil = _outil("backfill_vault_fills")
    monkeypatch.setattr(outil.time, "sleep", lambda s: None)
    jour = 24 * 3_600_000
    appels: list[tuple[int, int]] = []

    def poster(vault, a, b):
        appels.append((a, b))
        return []

    _, audit = outil.backfill_ledger_un_vault_avec_audit(
        tmp_path, "0x" + "a" * 40, lookback_j=90, limiteur=CF.Limiteur(0.0), poster=poster,
        fenetre_ms=outil.FENETRE_LEDGER_MS)
    assert audit["requested_windows"] == 13 and audit["complete"] is True            # 90 fenêtres d'un jour auparavant
    assert sum(b - a for a, b in appels) >= 89 * jour                                # toute la période est couverte

    # une réponse pleine peut être tronquée : sa fenêtre est redemandée en deux moitiés, jusqu'à la journée
    appels.clear()

    def plein_si_large(vault, a, b):
        appels.append((a, b))
        return [{"time": a, "hash": f"0x{a:x}", "delta": {"type": "deposit", "usdc": "1"}}] * (
            outil.CAP_LEDGER if b - a > 2 * jour else 3)

    _, audit = outil.backfill_ledger_un_vault_avec_audit(
        tmp_path, "0x" + "a" * 40, lookback_j=7, limiteur=CF.Limiteur(0.0), poster=plein_si_large,
        fenetre_ms=outil.FENETRE_LEDGER_MS)
    assert audit["complete"] is True and len(appels) > 4
    feuilles = [(a, b) for a, b in appels if b - a <= 2 * jour]
    assert sum(b - a for a, b in feuilles) >= 7 * jour - len(feuilles)               # les moitiés recouvrent tout, sans trou

    def toujours_refuse(vault, a, b):
        raise urllib.error.HTTPError("u", 429, "Too Many Requests", None, None)

    _, audit = outil.backfill_ledger_un_vault_avec_audit(
        tmp_path, "0x" + "a" * 40, lookback_j=2, limiteur=CF.Limiteur(2.0), poster=toujours_refuse)
    assert audit["complete"] is False and len(audit["failed_windows"]) == 2      # déclaré, jamais masqué


def test_un_refus_de_debit_est_reessaye_au_lieu_de_perdre_le_releve():
    """Cas réel du 2026-11-11 : 6 vaults sur 69 manquaient à une passe, pour un seul « 429 » chacun."""
    import urllib.error

    def refus(code=429, retry_after=None):
        return urllib.error.HTTPError("https://exemple.invalid", code, "refus", {"Retry-After": retry_after} if retry_after else {}, None)

    siestes: list[float] = []
    reponses = [refus(), refus(), {"ok": True}]

    def appel():
        r = reponses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    assert CF.reprendre_apres_refus_de_debit(appel, dormir=siestes.append) == {"ok": True}
    assert siestes == [3.0, 6.0]                                                   # l'attente double
    # le serveur indique son délai : il est suivi (borné à 30 s)
    siestes.clear()
    reponses[:] = [refus(retry_after="7"), {"ok": 2}]
    assert CF.reprendre_apres_refus_de_debit(appel, dormir=siestes.append) == {"ok": 2} and siestes == [7.0]
    # le dernier refus remonte ; une autre erreur n'est jamais réessayée
    siestes.clear()
    reponses[:] = [refus(), refus(), refus(), refus()]
    with pytest.raises(urllib.error.HTTPError):
        CF.reprendre_apres_refus_de_debit(appel, dormir=siestes.append)
    assert siestes == [3.0, 6.0, 12.0] and reponses == []                         # quatre essais, puis le refus remonte
    reponses[:] = [refus(code=400), {"jamais": "lu"}]
    with pytest.raises(urllib.error.HTTPError):
        CF.reprendre_apres_refus_de_debit(appel, dormir=siestes.append)
    assert len(reponses) == 1


def test_la_cadence_ponderee_deduit_la_duree_de_la_requete():
    temps = [100.0]
    siestes: list[float] = []

    def dormir(s):
        siestes.append(s)
        temps[0] += s

    cadence = CF.CadencePonderee(300.0, horloge=lambda: temps[0], dormir=dormir)
    assert cadence.attendre(22.0) == 0.0                                           # la première part tout de suite
    temps[0] += 1.5                                                                # la requête a duré 1,5 s
    assert cadence.attendre(22.0) == pytest.approx(4.4 - 1.5)                      # 22 unités sur 300/min = 4,4 s
    temps[0] += 10.0                                                               # requête lente : rien à attendre
    assert cadence.attendre(2.0) == 0.0
    assert cadence.attendre(2.0) == pytest.approx(0.4)
    assert siestes == [pytest.approx(2.9), pytest.approx(0.4)]


def test_les_rattrapages_cedent_la_place_quand_un_collecteur_en_direct_est_refuse(tmp_path, monkeypatch):
    """Une seule adresse IP pour tous les collecteurs locaux : le refus de l'un fait attendre les rattrapages."""
    import os
    import urllib.error

    # sans la variable posée par le lanceur : mécanisme inactif (tests, lanes cloud, outils lancés à la main)
    monkeypatch.delenv(CF.SIGNAL_DEBIT_ENV, raising=False)
    CF.signaler_refus_de_debit()
    assert CF.congestion_restante_s() == 0.0 and CF.ceder_au_direct(dormir=lambda s: 1 / 0) == 0.0

    temoin = tmp_path / "runtime" / "data" / "hl_refus_debit.flag"
    monkeypatch.setenv(CF.SIGNAL_DEBIT_ENV, str(temoin))
    assert CF.congestion_restante_s() == 0.0                                        # aucun refus encore
    CF.signaler_refus_de_debit()
    instant = temoin.stat().st_mtime
    assert CF.congestion_restante_s(instant + 10.0) == pytest.approx(CF.DUREE_CONGESTION_S - 10.0)
    siestes: list[float] = []
    assert CF.ceder_au_direct(siestes.append, instant + 40.0) == pytest.approx(5.0) and siestes == [pytest.approx(5.0)]
    assert CF.ceder_au_direct(siestes.append, instant + CF.DUREE_CONGESTION_S + 1.0) == 0.0 and len(siestes) == 1
    # horloge décalée (témoin daté dans le futur) : l'attente reste bornée, jamais de blocage
    os.utime(temoin, (instant + 9_999.0, instant + 9_999.0))
    assert CF.congestion_restante_s(instant) == CF.DUREE_CONGESTION_S

    # un refus réessayé par un collecteur en direct pose le témoin
    temoin.unlink()
    reponses = [urllib.error.HTTPError("https://exemple.invalid", 429, "refus", {}, None), {"ok": True}]

    def appel():
        r = reponses.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    assert CF.reprendre_apres_refus_de_debit(appel, dormir=lambda s: None) == {"ok": True} and temoin.is_file()

    # les deux rattrapages consultent le témoin avant chaque requête
    appels: list[str] = []
    monkeypatch.setattr(CF, "ceder_au_direct", lambda dormir=None, maintenant=None: appels.append("cede") or 0.0)
    bougies = _outil("backfill_candles_vaults")
    bougies.backfill_un_coin("BTC", 1, 2, limiteur=CF.Limiteur(0.0), poster=lambda *a, **k: [], dormir=lambda s: None)
    fills = _outil("backfill_vault_fills")
    fills._paginer_en_avant(lambda *a: [], "0x" + "a" * 40, 1, 2, limiteur=CF.Limiteur(0.0), max_pages=2)
    assert appels == ["cede", "cede"]
