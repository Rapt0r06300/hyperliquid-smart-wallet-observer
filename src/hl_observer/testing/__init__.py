"""Outils de TEST DES TESTS (2026-07-13).

Ce paquet ne teste pas le bot : il teste **ce que valent nos tests**.

Il naît d'une phrase qui revient dans toutes les post-mortems de ce projet :

    « Un garde-fou qui ne peut pas echouer ne garde rien. »

Et d'une variante decouverte aujourd'hui, pire :

    « Un test qui passe pour la MAUVAISE RAISON est un test qui MENT. »
    (mon test du RL passait... parce qu'un mot-cle de 2 caracteres ne matchait jamais)

Deux modules, zero dependance :

  * `mutation`       -- IDEA-93 : on CASSE le code exprès. Si les tests restent VERTS, ils ne
                        gardaient rien. C'est la seule mesure honnete de la valeur d'une suite.
  * `property_based` -- IDEA-92 : au lieu de 3 exemples choisis par moi (donc biaises par ce que
                        j'imagine), on genere des centaines de cas et on verifie une PROPRIETE
                        qui doit tenir pour TOUS.

Aucun ordre reel.
"""
from __future__ import annotations

__all__ = ["mutation", "property_based"]
