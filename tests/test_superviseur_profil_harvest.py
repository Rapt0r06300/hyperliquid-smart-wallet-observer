"""[LANCEUR bloc 1] Profil officiel HARVEST (item 1) + sortie non-zero si une source OBLIGATOIRE manque
(item 8). Prouvé sans Windows.

- HARVEST est un profil de récolte DENSE, distinct de research : il inclut le socle CORE
  (prix/microstructure/userFills) plus les collecteurs de récolte qui possèdent un VRAI runner
  présent sur le disque. Les briques encore BLOCKED (node fills, HF recorder, TWAP, Bybit)
  restent honnêtement HORS profil tant qu'un collecteur réseau réel n'est pas branché.
- POLITIQUE dYdX UNIQUE (AUD-044) : Hyperliquid-first. dydx-live a un vrai runner et figure dans
  HARVEST comme source SECONDAIRE non-bloquante (obligatoire=False dans preuve_de_vie.SOURCES_HARVEST),
  JAMAIS dans le socle CORE/REQUIS — son absence dégrade la récolte sans bloquer READY.
- Le CLI `demarrer-tous` BLOQUE (exit 3) dès qu'un collecteur REQUIS (= CORE) n'a pas démarré :
  le moteur ne doit jamais tourner au-dessus d'une source obligatoire morte.
"""
from __future__ import annotations

from pathlib import Path

from hl_observer.ops import preuve_de_vie as PV
from hl_observer.ops import superviseur_collecteurs as SC

RACINE = Path(__file__).resolve().parents[1]


def test_harvest_est_un_profil_officiel_distinct_de_research():
    assert "harvest" in SC.PROFILS_VALIDES and SC.normaliser_profil("harvest") == "harvest"
    noms_harvest = {c["nom"] for c in SC.collecteurs_pour_profil("harvest")}
    noms_research = {c["nom"] for c in SC.collecteurs_pour_profil("research")}
    # HARVEST inclut le socle CORE ; research l'EXCLUT -> deux profils réellement distincts.
    assert SC.COLLECTEURS_CORE <= noms_harvest and not (SC.COLLECTEURS_CORE & noms_research)
    assert noms_harvest != noms_research and len(noms_harvest) > len(SC.COLLECTEURS_CORE)


def test_harvest_ne_contient_que_des_collecteurs_avec_un_vrai_runner():
    harvest = SC.collecteurs_pour_profil("harvest")
    # chaque collecteur retenu appartient bien au REGISTRE et son script existe sur le disque
    assert SC.COLLECTEURS_HARVEST <= {c["nom"] for c in SC.REGISTRE}
    for c in harvest:
        assert c["nom"] in SC.COLLECTEURS_HARVEST
        assert (RACINE / c["script"]).exists(), c["script"]


def test_cli_demarrer_tous_bloque_si_source_obligatoire_absente(monkeypatch):
    assert SC.COLLECTEURS_REQUIS == SC.COLLECTEURS_CORE

    # une source CORE non démarrée -> exit 3 (le lanceur s'arrête, pas seulement un affichage)
    def _ko(root, **kw):
        return {"run_id": "r", "profil": "harvest", "selectionnes": 12,
                "pids": {"allmids-collector": 1}, "reutilises": [],
                "manquants": ["bbo-collector", "vault-collector"]}

    monkeypatch.setattr(SC, "demarrer_tous", _ko)
    assert SC._cli(["demarrer-tous", "harvest"]) == 3

    # tout le CORE démarré (un non-requis manquant ne bloque pas) -> exit 0
    def _ok(root, **kw):
        return {"run_id": "r", "profil": "harvest", "selectionnes": 12,
                "pids": {n: 1 for n in SC.COLLECTEURS_CORE}, "reutilises": [],
                "manquants": ["vault-collector"]}

    monkeypatch.setattr(SC, "demarrer_tous", _ok)
    assert SC._cli(["demarrer-tous", "harvest"]) == 0


def test_dydx_live_est_une_source_harvest_secondaire_pas_core():
    """AUD-044 — POLITIQUE dYdX UNIQUE, épinglée. Hyperliquid-first :
    dydx-live est une source SECONDAIRE du harvest (présente, non-bloquante),
    JAMAIS dans le socle CORE obligatoire. Épingle l'absence de contradiction
    « hors profil » et l'alignement inter-module avec preuve_de_vie."""
    harvest = {c["nom"] for c in SC.collecteurs_pour_profil("harvest")}

    # (1) PRÉSENTE dans le harvest, en tant que secondaire avec un vrai runner sur le disque
    assert "dydx-live" in SC.COLLECTEURS_HARVEST
    assert "dydx-live" in harvest
    dydx = next(c for c in SC.REGISTRE if c["nom"] == "dydx-live")
    assert (RACINE / dydx["script"]).exists(), dydx["script"]

    # (2) PAS dans le socle CORE / obligatoire -> son absence ne bloque JAMAIS READY
    assert "dydx-live" not in SC.COLLECTEURS_CORE
    assert "dydx-live" not in SC.COLLECTEURS_REQUIS
    assert SC.profil_collecteur("dydx-live") != "core"

    # (3) MÊME politique côté preuve_de_vie : source secondaire, obligatoire=False
    src = {s.nom: s for s in PV.SOURCES_HARVEST}
    assert "dydx-live" in src
    assert src["dydx-live"].obligatoire is False
