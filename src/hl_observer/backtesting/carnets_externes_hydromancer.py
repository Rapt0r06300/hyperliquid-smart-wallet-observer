"""Carnets EXTERNES à la minute (Hydromancer Reservoir, CC BY 4.0) : un carnet pour chaque instant, jamais une preuve.

Pourquoi : 65 % des candidats du labo sont rejetés faute de carnet à la SORTIE (``STALE_OR_MISSING_EXIT_BOOK``) ; la
collecte d'Alina ne tient pas une même connexion L2 tout au long d'une position. Le Reservoir publie, pour 463 perps
sur 10 venues, 20 niveaux par côté CHAQUE MINUTE du 15/12/2025 au 17/11/2026 : n'importe quel instant a un carnet à
30 s au plus, et la source est continue par construction.

Ce que ce lecteur garantit :
- seuls les fichiers ``EXTERNAL_VALIDATED`` du manifeste sont lus (``tools/ingerer_hydromancer.py``) ;
- l'heure d'un carnet est ``block_time_ms`` (l'heure du BLOC, donc de la bourse), jamais une heure de réception ;
- chaque carnet rendu porte ``causal_observation: False`` et ``data_origin: EXTERNAL_HISTORICAL`` : les prédicats de
  rejouabilité du labo (``fenetres_de_signal.predicats_de_rejouabilite``) le comptent NON causal, il ne peut donc
  jamais devenir une preuve SAFE -- au mieux un backtest sous hypothèses explicites ;
- ``carnet_a`` ne rend jamais un carnet plus loin que la tolérance demandée, et dit de quel côté il est.
Lecture seule. Les fichiers sont lus par jour et par coin, à la demande, puis gardés en cache.
"""
from __future__ import annotations

import bisect
import json
import re
from pathlib import Path
from typing import Any

DOSSIER = Path("runtime") / "history" / "hydromancer"
SOURCE = "HYDROMANCER_RESERVOIR_1M"
JOUR_MS = 86_400_000


class CarnetsHydromancer:
    def __init__(self, root: Path, *, niveaux: int = 5) -> None:
        self.root = Path(root)
        self.niveaux = int(niveaux)
        self._jours: dict[str, Path] = {}
        try:
            man = json.loads((self.root / DOSSIER / "MANIFESTE.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            man = {"fichiers": {}}
        for cle, m in man.get("fichiers", {}).items():
            j = re.search(r"orderbooks_perps_(\d{4}-\d{2}-\d{2})\.parquet$", cle)
            if j and m.get("statut") == "EXTERNAL_VALIDATED" and (self.root / DOSSIER / cle).is_file():
                self._jours[j.group(1)] = self.root / DOSSIER / cle
        #: jour -> (table du jour, {coin: (heures triées, lignes)}) ; un jour est lu UNE fois pour tous les coins
        self._jours_charges: dict[str, tuple[Any, dict[str, tuple[list[int], list[int]]]]] = {}
        self._ordre: list[str] = []
        self.jours_en_memoire = 3

    @property
    def jours(self) -> list[str]:
        return sorted(self._jours)

    def _jour(self, jour: str):
        if jour in self._jours_charges:
            return self._jours_charges[jour]
        chemin = self._jours.get(jour)
        if chemin is None:
            return None
        import pyarrow.parquet as pq

        t = pq.read_table(chemin, columns=["coin", "block_time_ms", "bids", "asks"])
        coins = t.column("coin").to_pylist()
        temps = t.column("block_time_ms").to_pylist()
        par: dict[str, list[tuple[int, int]]] = {}
        for i, (c, ts) in enumerate(zip(coins, temps)):
            par.setdefault(c, []).append((int(ts), i))
        index = {c: ([ts for ts, _ in sorted(v)], [i for _, i in sorted(v)]) for c, v in par.items()}
        self._jours_charges[jour] = (t, index)
        self._ordre.append(jour)
        while len(self._ordre) > self.jours_en_memoire:              # mémoire bornée : quelques jours à la fois
            self._jours_charges.pop(self._ordre.pop(0), None)
        return self._jours_charges[jour]

    def _carnet_ligne(self, t, i: int, coin: str) -> dict[str, Any] | None:
        r = t.slice(i, 1).to_pylist()[0]
        bids = [[float(x["px"]), float(x["sz"])] for x in (r["bids"] or [])[: self.niveaux]]
        asks = [[float(x["px"]), float(x["sz"])] for x in (r["asks"] or [])[: self.niveaux]]
        if not bids or not asks or bids[0][0] >= asks[0][0]:
            return None                               # côté vide ou carnet croisé : jamais rendu comme un prix
        return {"coin": coin, "exchange_ts_ms": int(r["block_time_ms"]), "bid": bids[0][0], "ask": asks[0][0],
                "bids5": bids, "asks5": asks, "source": SOURCE, "causal_observation": False,
                "data_origin": "EXTERNAL_HISTORICAL"}

    def carnet_a(self, coin: str, t_ms: int, *, tolerance_ms: int = 30_000, cote: str = "plus_proche"
                 ) -> dict[str, Any] | None:
        """Le carnet le plus proche de ``t_ms`` (``cote`` : ``plus_proche``, ``avant`` ou ``apres``), à
        ``tolerance_ms`` au plus ; ``None`` sinon. Le résultat dit son écart (``ecart_ms``, signé)."""
        import datetime as dt

        candidats: list[tuple[int, Any, int]] = []
        for decalage in (0, -JOUR_MS, JOUR_MS):           # un instant proche de minuit regarde le jour voisin
            ts_jour = int(t_ms) + decalage
            if decalage and abs((int(t_ms) % JOUR_MS) - (JOUR_MS if decalage > 0 else 0)) > tolerance_ms:
                continue                                  # loin de minuit : le jour voisin ne peut rien apporter
            jour = dt.datetime.fromtimestamp(ts_jour / 1000, dt.timezone.utc).strftime("%Y-%m-%d")
            charge = self._jour(jour)
            if charge is None:
                continue
            t, index = charge
            temps, lignes = index.get(coin, ([], []))
            i = bisect.bisect_left(temps, int(t_ms))
            for k in range(max(0, i - 3), min(len(temps), i + 3)):   # voisins : un carnet cassé passe au suivant
                ecart = temps[k] - int(t_ms)
                if abs(ecart) <= tolerance_ms and not (cote == "avant" and ecart > 0) and not (cote == "apres" and ecart < 0):
                    candidats.append((abs(ecart), t, lignes[k]))
        for _, t, i in sorted(candidats, key=lambda x: x[0]):
            c = self._carnet_ligne(t, i, coin)
            if c is not None:
                return {**c, "ecart_ms": c["exchange_ts_ms"] - int(t_ms)}
        return None


__all__ = ["CarnetsHydromancer", "SOURCE"]
