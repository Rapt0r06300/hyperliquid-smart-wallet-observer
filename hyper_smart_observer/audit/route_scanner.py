from __future__ import annotations


def audit_routes(routes: list[str]) -> tuple[bool, str]:
    dangerous = [route for route in routes if any(word in route.lower() for word in ("trade", "order", "execute", "exchange"))]
    return not dangerous, f"dangerous routes: {dangerous}"
