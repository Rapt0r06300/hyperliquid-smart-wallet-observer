"""Point d'entrée public et explicite du laboratoire autonome Alina.

Ce module ne lance rien par défaut. Il rend les briques autonomes joignables depuis
un outil de production versionné dans le dépôt principal et fournit un diagnostic
simple. Les vrais jobs restent déclenchés par le plan de contrôle privé.
"""
from __future__ import annotations

import argparse
import json
from typing import Iterable

from hl_observer.datasets import max_data_policy
from hl_observer.ops import autonomous_research_brain
from hl_observer.ops import autonomous_research_guard
from hl_observer.ops import autonomous_research_job
from hl_observer.ops import autonomous_research_status


def _check_payload() -> dict[str, object]:
    return {
        "schema": "alina.autonomous_lab_entrypoint.v1",
        "job_schema": autonomous_research_job.SCHEMA,
        "max_cycle_seconds": autonomous_research_guard.MAX_ALLOWED_SECONDS,
        "status_schema": autonomous_research_status.SCHEMA,
        "brain_module": autonomous_research_brain.__name__,
        "max_data_module": max_data_policy.__name__,
        "target_net_usd_per_family": max_data_policy.TARGET_NET_USD_PER_FAMILY,
        "paper_only": True,
        "real_execution": False,
    }


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Diagnostic et délégation sûre des briques du laboratoire autonome Alina."
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("check", help="Vérifie que les briques autonomes sont importables et câblées.")
    guard = sub.add_parser("guard", help="Délègue au garde timebox du laboratoire.")
    guard.add_argument("args", nargs=argparse.REMAINDER)
    brain = sub.add_parser("brain", help="Délègue au cerveau de recherche.")
    brain.add_argument("args", nargs=argparse.REMAINDER)
    job = sub.add_parser("job", help="Délègue au worker autonome validé.")
    job.add_argument("args", nargs=argparse.REMAINDER)
    max_data = sub.add_parser(
        "max-data",
        help="Délègue à la politique MAX DATA avec garde disque et objectifs économiques séparés.",
    )
    max_data.add_argument("args", nargs=argparse.REMAINDER)
    args = parser.parse_args(list(argv) if argv is not None else None)

    if args.command == "check":
        print(json.dumps(_check_payload(), ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.command == "guard":
        return autonomous_research_guard.main(args.args)
    if args.command == "brain":
        return autonomous_research_brain.main(args.args)
    if args.command == "job":
        return autonomous_research_job.main(args.args)
    if args.command == "max-data":
        return max_data_policy.main(args.args)
    parser.error("commande inconnue")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
