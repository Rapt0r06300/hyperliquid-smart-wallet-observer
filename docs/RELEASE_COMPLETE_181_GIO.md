# Release complète téléchargeable

Le lanceur CREER_RELEASE_COMPLETE.cmd construit une copie vérifiée du dossier
du dépôt, y compris .git, runtime, l'environnement Python portable et les
données. La seule exclusion est son propre dossier de sortie sous
runtime/portable-build afin d'éviter que l'archive se contienne elle-même.

La construction produit :

- Installer-Alina-SmartFlow.exe, un bootstrap Windows d'environ 2,5 Mio ;
- ALINA_FULL_FOLDER_RELEASE.json, le manifeste de release ;
- ALINA_FULL_FOLDER_INVENTORY.json, l'inventaire SHA-256 de chaque fichier ;
- des volumes Alina-SmartFlow-Full.7z.001, .002, etc. de 1 900 Mio au plus ;
- ASSETS_A_TELECHARGER.txt, la liste exacte des assets à publier.

Le constructeur refuse les noms de fichiers correspondant à des secrets,
refuse une source Git divergente de origin/main, et refuse toute modification
d'un fichier source pendant la création. Les jonctions internes ne sont pas
suivies : leur cible relative est inscrite dans l'inventaire et l'installateur
les recrée après vérification.

Un cache Python compilé sous __pycache__ peut être inscrit comme exclu s'il est
réellement illisible à cause de son ACL Windows. Aucun autre fichier illisible
n'est toléré.

Après avoir poussé le commit et installé GitHub CLI, la publication s'effectue
avec tools/publish_full_folder_release.ps1 en lui passant BuildDirectory, qui
doit désigner le sous-dossier produit sous runtime/portable-build.

Sur le PC cible, l'installateur télécharge les volumes avec reprise HTTP,
contrôle leur taille et leur SHA-256, extrait dans un dossier temporaire,
contrôle ensuite chaque fichier et publie le dossier final seulement après
validation complète. La destination par défaut est le dossier Projet invest
sur le Bureau. Elle doit être absente ou vide.

Options disponibles : --yes, --destination, --cache et --keep-cache.
