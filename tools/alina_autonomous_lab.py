"""Point d'entrée public et explicite du laboratoire autonome Alina.

Ce module ne lance rien par défaut. Il rend les briques autonomes joignables depuis
un outil de production versionné dans le dépôt principal et fournit un diagnostic
simple. Les vrais jobs restent déclenchés par le plan de contrôle GitHub/self-hosted.
"""
from __future__ import annotations

import argparse
import json
from typing import Iterable

from hl_observer.datasets import max_data_policy, max_data_router
from hl_observer.ops import autonomous_research_brain
from hl_observer.ops import autonomous_research_guard
from hl_observer.ops import autonomous_research_job
from hl_observer.ops import autonomous_research_job_router
from hl_observer.ops import autonomous_research_status
from hl_observer.ops import self_hosted_control
from hl_observer.ops import self_hosted_return

MAX_DATA_ROUTE = "src/hl_observer/datasets/max_data_router.py"


def _check_payload() -> dict[str, object]:
    return {
        "schema": "alina.autonomous_lab_entrypoint.v4",
        "job_schema": autonomous_research_job.SCHEMA,
        "job_router_module": autonomous_research_job_router.__name__,
        "control_schema": self_hosted_control.CONTROL_SCHEMA,
        "return_schema": self_hosted_return.SCHEMA,
        "max_cycle_seconds": autonomous_research_guard.MAX_ALLOWED_SECONDS,
        "status_schema": autonomous_research_status.STATUS_SCHEMA,
        "brain_module": autonomous_research_brain.__name__,
        "max_data_module": max_data_policy.__name__,
        "max_data_router_module": max_data_router.__name__,
        "max_data_route": MAX_DATA_ROUTE,
        "self_hosted_control_module": self_hosted_control.__name__,
        "self_hosted_return_module": self_hosted_return.__name__,
        "target_net_usd_per_family": max_data_policy.TARGET_NET_USD_PER_FAMILY,
        "paper_only": True,
        "real_execution": False,
        "self_hosted_ready_in_code": True,
        "compact_return_ready_in_code": True,
        "active_family_full_cold_economic_routing": True,
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
    job = sub.add_parser("job", help="Délègue au worker autonome routé et validé.")
    job.add_argument("args", nargs=argparse.REMAINDER)
    control = sub.add_parser(
        "control",
        help="Canonise une commande GitHub en requête worker self-hosted verrouillée.",
    )
    control.add_argument("args", nargs=argparse.REMAINDER)
    compact_return = sub.add_parser(
        "return",
        help="Construit le retour compact GitHub/ChatGPT d'un gros run terminé.",
    )
    compact_return.add_argument("args", nargs=argparse.REMAINDER)
    max_data = sub.add_parser(
        "max-data",
        help="Délègue à la politique MAX DATA routée, sans modifier son classement ni le holdout.",
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
        return autonomous_research_job_router.main(args.args)
    if args.command == "control":
        return self_hosted_control.main(args.args)
    if args.command == "return":
        return self_hosted_return.main(args.args)
    if args.command == "max-data":
        return max_data_router.main(args.args)
    parser.error("commande inconnue")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
