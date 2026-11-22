r"""Le rattrapage se règle sur le COFFRE, pas sur sa propre mémoire.

Demande de l'utilisateur (22/11/2026) : « le rattrapage doit utiliser le coffre-fort ». Jusqu'ici
`RATTRAPAGE.cmd` décidait de ce qui manque à partir du curseur de `backfill_candles_vaults`
(`runtime/data/backfill_candles_etat.json`) : « j'ai demandé BTC 1 h jusqu'à telle heure ». Or le
labo et le moteur ne lisent QUE le coffre. Une page écrite puis jamais scellée — écartée, coupée,
ou perdue avec un dossier de travail — restait « faite » pour le curseur et absente pour le labo :
plus personne ne la redemandait.

Ici : la couverture RÉELLE du coffre, série par série et coin par coin (premier et dernier pas),
lue dans les shards certifiés (avec un cache par shard, un shard étant immuable). Puis on recule
le curseur partout où il promet plus que le coffre n'a — vers l'avant (dernier pas) comme vers le
passé (profondeur du funding). Le curseur n'avance JAMAIS ici : seul un téléchargement le fait.
LECTURE SEULE du coffre ; seul le curseur du rattrapage est réécrit (copie gardée à côté).
"""
from __future__ import annotations

import gzip
import json
import os
import time
from pathlib import Path
from typing import Any

#: Pas de chaque série, en millisecondes. Le funding est horaire.
PAS_MS = {"5m": 300_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000, "funding": 3_600_000}
#: Un curseur en avance de plus d'un pas et demi sur le coffre promet une donnée absente.
TOLERANCE_PAS = 1.5
CACHE = Path("runtime") / "data" / "rattrapage_couverture_coffre.json"
#: Quand un coin n'a RIEN de plus ancien, `backfill_candles_vaults` met son front arrière au PLANCHER
#: (`maintenant - profondeur`) : « origine atteinte, ne plus demander ». Ce n'est pas une promesse de
#: données. Mesuré le 22/11 : 211 coins, tous à 1 106 jours — pris d'abord à tort pour 129 015
#: jours-coins de funding absents du coffre. Un front arrière plus vieux que ce seuil est un plancher.
PROFONDEUR_FUNDING_J = 1100.0
MARGE_PLANCHER_J = 30.0
SCHEMA_CACHE = "hypersmart.rattrapage_couverture_coffre.v1"


def _series_d_un_shard(chemin: Path, famille: str) -> dict[str, dict[str, list[int]]]:
    """{série: {coin: [premier_ms, dernier_ms]}} d'un shard. Seuls les backfills REST comptent."""
    out: dict[str, dict[str, list[int]]] = {}
    with gzip.open(chemin, "rt", encoding="utf-8") as f:
        for ligne in f:
            try:
                x = json.loads(ligne)
            except ValueError:
                continue
            if famille == "funding_history":
                serie, t = "funding", x.get("ts_ms")
            else:
                if not str(x.get("source") or "").startswith("REST_BACKFILL"):
                    continue                     # la bougie du direct n'est pas ce que le rattrapage télécharge
                serie, t = x.get("interval"), x.get("open_ts_ms")
            coin = x.get("coin")
            if serie not in PAS_MS or not coin or not isinstance(t, int) or isinstance(t, bool):
                continue
            borne = out.setdefault(serie, {}).setdefault(str(coin), [t, t])
            if t < borne[0]:
                borne[0] = t
            if t > borne[1]:
                borne[1] = t
    return out


def couverture_du_coffre(root: Path, *, cache: bool = True) -> dict[str, dict[str, list[int]]]:
    """La couverture réelle du coffre. Index illisible -> {} (on ne recule alors RIEN : on ne
    conclut pas « tout manque » d'un index qu'on n'a pas su lire)."""
    root = Path(root)
    try:
        index = json.loads((root / "runtime" / "coffre_certifie" / "LOCAL_INDEX.json").read_text(encoding="utf-8"))
        shards = [s for s in index["shards"] if s.get("famille") in ("candle", "funding_history")]
    except (OSError, ValueError, KeyError, TypeError):
        return {}
    memo: dict[str, Any] = {}
    if cache:
        try:
            brut = json.loads((root / CACHE).read_text(encoding="utf-8"))
            if brut.get("_schema") == SCHEMA_CACHE:
                memo = brut.get("shards") or {}
        except (OSError, ValueError, AttributeError):
            memo = {}
    total: dict[str, dict[str, list[int]]] = {}
    neuf: dict[str, Any] = {}
    for s in shards:
        cle = f"{s.get('shard')}|{s.get('shard_sha256')}"
        resume = memo.get(cle)
        if resume is None:
            try:
                resume = _series_d_un_shard(root / s["shard"], s["famille"])
            except OSError:
                continue                         # shard illisible : il ne prouve rien, on ne l'invente pas
        neuf[cle] = resume
        for serie, par_coin in resume.items():
            for coin, (a, b) in par_coin.items():
                borne = total.setdefault(serie, {}).setdefault(coin, [a, b])
                borne[0], borne[1] = min(borne[0], a), max(borne[1], b)
    if cache:
        try:
            chemin = root / CACHE
            chemin.parent.mkdir(parents=True, exist_ok=True)
            tmp = chemin.with_name(f"{chemin.name}.{os.getpid()}.tmp")
            tmp.write_text(json.dumps({"_schema": SCHEMA_CACHE, "maj_ms": int(time.time() * 1000), "shards": neuf}),
                           encoding="utf-8")
            os.replace(tmp, chemin)
        except OSError:
            pass
    return total


def couverture_des_rubans(root: Path, series: set[str], rubans: dict[str, Path]) -> dict[str, dict[str, list[int]]]:
    """Ce que les rubans LOCAUX du rattrapage contiennent déjà, pour les séries demandées.

    Un rattrapage interrompu (Ctrl+C) laisse ses pages sur le disque sans les sceller : elles ne sont
    pas au coffre, mais les redemander serait payer deux fois. Seule une donnée absente des DEUX
    est redemandée ; celle qui n'attend que le scellage est comptée à part."""
    out: dict[str, dict[str, list[int]]] = {}
    for serie in sorted(series):
        chemin = rubans.get(serie)
        if chemin is None:
            continue
        champ = "ts_ms" if serie == "funding" else "open_ts_ms"
        try:
            with open(Path(root) / chemin, "rb") as f:
                for ligne in f:
                    try:
                        x = json.loads(ligne)
                    except ValueError:
                        continue
                    coin, t = x.get("coin"), x.get(champ, x.get("t_ms"))
                    if serie != "funding" and x.get("interval", serie) != serie:
                        continue
                    if not coin or not isinstance(t, int) or isinstance(t, bool):
                        continue
                    borne = out.setdefault(serie, {}).setdefault(str(coin), [t, t])
                    borne[0], borne[1] = min(borne[0], t), max(borne[1], t)
        except OSError:
            continue
    return out


def ecarter_ce_qui_attend_le_scellage(a_faire: list[dict[str, Any]], rubans: dict[str, dict[str, list[int]]],
                                      ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """(à redemander, déjà sur le disque en attente du scellage)."""
    garder, en_attente = [], []
    for c in a_faire:
        base = "funding" if c["serie"] == "funding_ancien" else c["serie"]
        tolerance = TOLERANCE_PAS * PAS_MS[base]
        borne = rubans.get(base, {}).get(c["coin"])
        if borne is not None and (borne[0] - c["curseur_ms"] <= tolerance if c["serie"] == "funding_ancien"
                                  else c["curseur_ms"] - borne[1] <= tolerance):
            en_attente.append(c)
        else:
            garder.append(c)
    return garder, en_attente


def corrections(curseur: dict[str, dict[str, int]], couverture: dict[str, dict[str, list[int]]],
                *, now_ms: int | None = None, profondeur_funding_j: float = PROFONDEUR_FUNDING_J
                ) -> list[dict[str, Any]]:
    """Où le curseur promet plus que le coffre. Ne propose JAMAIS d'avancer un curseur."""
    out: list[dict[str, Any]] = []
    maintenant = int(time.time() * 1000) if now_ms is None else int(now_ms)
    plancher_max = maintenant - (profondeur_funding_j - MARGE_PLANCHER_J) * 86_400_000
    if not couverture:
        return out
    for serie, par_coin in (curseur or {}).items():
        base = "funding" if serie == "funding_ancien" else serie
        pas = PAS_MS.get(base)
        if pas is None or not isinstance(par_coin, dict):
            continue
        tolerance = TOLERANCE_PAS * pas
        vu = couverture.get(base, {})
        for coin, valeur in par_coin.items():
            if not isinstance(valeur, int) or isinstance(valeur, bool):
                continue
            borne = vu.get(coin)
            if serie == "funding_ancien":
                # profondeur : le curseur dit « creusé jusqu'à » ; le coffre doit commencer aussi tôt
                if borne is None or borne[0] - valeur <= tolerance:
                    continue                     # sans rien au coffre, la passe vers l'avant s'en charge
                if valeur <= plancher_max:
                    continue                     # marque de plancher : « origine atteinte », pas une donnée
                out.append({"serie": serie, "coin": coin, "curseur_ms": valeur, "coffre_ms": borne[0],
                            "nouveau_ms": borne[0], "motif": "PROFONDEUR_ABSENTE_DU_COFFRE"})
            elif borne is None:
                out.append({"serie": serie, "coin": coin, "curseur_ms": valeur, "coffre_ms": None,
                            "nouveau_ms": None, "motif": "RIEN_AU_COFFRE"})
            elif valeur - borne[1] > tolerance:
                out.append({"serie": serie, "coin": coin, "curseur_ms": valeur, "coffre_ms": borne[1],
                            "nouveau_ms": borne[1], "motif": "FIN_ABSENTE_DU_COFFRE"})
    return out


def appliquer(curseur: dict[str, dict[str, int]], a_faire: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """Nouveau curseur : reculé là où il le faut ; un coin sans rien au coffre repart de zéro."""
    neuf = {serie: dict(v) for serie, v in (curseur or {}).items() if isinstance(v, dict)}
    for c in a_faire:
        serie = neuf.setdefault(c["serie"], {})
        if c["nouveau_ms"] is None:
            serie.pop(c["coin"], None)
        else:
            serie[c["coin"]] = int(c["nouveau_ms"])
    return neuf


def aligner_le_curseur_sur_le_coffre(root: Path, *, ecrire: bool, cache: bool = True) -> dict[str, Any]:
    """Mesure, et (si `ecrire`) recule le curseur du rattrapage. Rend le bilan."""
    import sys
    root = Path(root)
    outils = str(Path(__file__).resolve().parents[3] / "tools")
    if outils not in sys.path:
        sys.path.insert(0, outils)
    from backfill_candles_vaults import ETAT, SCHEMA_ETAT

    chemin = root / ETAT
    try:
        brut = json.loads(chemin.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"statut": "CURSEUR_ABSENT", "corrections": []}
    if brut.get("_schema") != SCHEMA_ETAT or not isinstance(brut.get("intervalles"), dict):
        return {"statut": "CURSEUR_ILLISIBLE", "corrections": []}
    couverture = couverture_du_coffre(root, cache=cache)
    if not couverture:
        return {"statut": "COFFRE_ILLISIBLE", "corrections": []}
    a_faire = corrections(brut["intervalles"], couverture)
    en_attente: list[dict[str, Any]] = []
    if a_faire:
        from backfill_candles_vaults import SORTIE_FUNDING, SORTIES
        series = {"funding" if c["serie"] == "funding_ancien" else c["serie"] for c in a_faire}
        locaux = couverture_des_rubans(root, series, {**SORTIES, "funding": SORTIE_FUNDING})
        a_faire, en_attente = ecarter_ce_qui_attend_le_scellage(a_faire, locaux)
    bilan = {"statut": "ALIGNE" if not a_faire else ("RECULE" if ecrire else "A_RECULER"),
             "corrections": a_faire, "en_attente_de_scellage": len(en_attente),
             "series_au_coffre": {s: len(v) for s, v in couverture.items()}}
    if a_faire and ecrire:
        copie = chemin.with_name(f"{chemin.stem}.avant-coffre-{time.strftime('%Y%m%dT%H%M%S')}.json")
        copie.write_text(json.dumps(brut, ensure_ascii=False), encoding="utf-8")     # rien n'est perdu
        neuf = {**brut, "intervalles": appliquer(brut["intervalles"], a_faire),
                "aligne_sur_le_coffre_ms": int(time.time() * 1000)}
        tmp = chemin.with_name(f"{chemin.name}.{os.getpid()}.tmp")
        tmp.write_text(json.dumps(neuf, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, chemin)
        bilan["copie_avant"] = str(copie)
    return bilan
