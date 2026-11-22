"""FACADE PAR ALIAS DE MODULE -- le module reel vit sous src/hl_observer/dataset/.

21/11/2026 -- VIOLATION DE COUCHES LEVEE.
`src/hl_observer/backtesting/copy_vault_local_lab.py` importait `tools.partitioned_data_index`,
donc le toolkit quant ne s'importait plus sans la racine du depot sur sys.path
(regle d'audit << Le toolkit quant (backtesting/) doit rester SANS dependance
externe >>). Le module a ete DEPLACE, pas duplique, vers
`src/hl_observer/dataset/partitioned_data_index.py` -- seul paquet dont l'__init__ est un
docstring nu, donc sans effet de bord a l'import (celui de `datasets/` importe
`github_release_bridge`, ce qui aurait reintroduit une dependance reseau dans la
chaine d'import du toolkit).

CE FICHIER N'EST PAS UN RE-EXPORT. Il remplace son entree de `sys.modules` par
l'OBJET module reel. Mesure du 21/11/2026 : 51 fichiers referencent ces modules,
dont 31 avec un repli sur le nom nu, et `tests/test_partitioned_data_index.py`
fait deux `monkeypatch.setattr` sur l'objet module. Les cinq motifs ont ete
verifies en bac a sable AVANT la pose :
  * `from tools.partitioned_data_index import f`                               -> OK
  * `from partitioned_data_index import f` (repli nom nu)                      -> OK
  * `import tools.partitioned_data_index` / `import partitioned_data_index`                     -> meme objet
  * `from tools import partitioned_data_index as m` + `monkeypatch.setattr(m, ...)`
    -> `m is` le module reel, donc le patch porte sur la fonction
       REELLEMENT appelee ; un re-export aurait patche la facade seule
  * `python tools/partitioned_data_index.py` (point d'entree CLI)              -> OK
`tools/python/python314._pth` met `..\\..\\src` sur sys.path relativement a
l'interpreteur : aucun bootstrap n'est necessaire, depuis n'importe quel
repertoire, pas seulement depuis la racine du depot.
"""
import sys
from pathlib import Path

# Direct tool execution only adds tools/ to sys.path. Include the checked-out
# src/ package on hosted runners and fresh clones without requiring pip install.
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from hl_observer.dataset import partitioned_data_index as _reel

if __name__ == "__main__":
    raise SystemExit(_reel.main())

sys.modules[__name__] = _reel
