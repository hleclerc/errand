# Services d'une page, par machine : décisions

## Tour 1

- **Verbe** : `errand serve` reste le seul verbe des services (`errand serve install`, `errand serve fetch`) ; pas de `errand server`.
- **Qui sait lancer** : le paquet du producteur, installé sur la machine, décrit ses services en données (`errand-services.json` dans le paquet, lu sans importer) ; le store ne porte que des noms (`name#version`), le protocole, le texte et le paquet qui les fournit. Le store copie la description déclarative (le JSON), jamais du code.
- **Version** : hash fixé par le producteur (code du service + protocole, au choix du producteur), 8 hexa ; plusieurs versions d'un même nom coexistent sur une machine, le relais ne prend que la version exacte ; au démarrage le gardien demande au service son identité (`GET /errand/identity`), un écart = arrêt et état `wrong version`.
- **Machines proposées** : toutes les machines, *ici* en premier, sauf si le service exprime un besoin particulier : alors tri, et les machines qui ne conviennent pas sont grisées avec la raison.
- **Choix de machine** : gardé par errand, par vue, sur la machine qui sert la page (`POST .errand/services/<name> {"on": M}`, refusé hors de la liste) ; effet à la requête suivante, les connexions ouvertes restent où elles sont.
- **Diagnostic** : l'agent lit des fichiers ; idéalement jamais de `--version`. Si une version ne peut vraiment pas se lire sans exécuter, l'utilisateur l'autorise explicitement, avec la commande détaillée.
- **Liste des services** : `errand status` / `errand web` montrent tout ce qui est déclaré ; un déclaré jamais lancé est `ready` ; `spec.json` n'a plus de raison d'être.
- **Paquet absent** : `errand-services.json` dit comment installer le paquet, et errand propose les lignes pour l'installer.

## Tour 2

- **Ce que le store copie** : seulement la description déclarative (les entrées de `errand-services.json`) ; le code vient de dépôts (PyPI, conda-forge, download.blender.org…) ou d'une installation locale (`pip -e`), jamais du store.
- **Machine sans copie du store** : errand propose d'y copier le contenu.
- **Version sans exécuter** : le paquet dit où lire la version de chaque outil dans des fichiers (`Info.plist`, nom de répertoire, base dpkg, snap, `dist-info`) ; sinon « version inconnue » et une ligne explicite `errand serve probe --on M -- <programme> --version` que la personne tape ; résultat gardé par (chemin, taille, date) ; *Refresh* relit, ne réexécute jamais ; version donnable à la main avec le chemin.
- **Plus de `spec.json`** : toute source est une déclaration lisible par nom (`services.py`, `services-installed.json`, ad hoc écrit là avec `adhoc: true` et retiré à l'arrêt, projet relu par son chemin gardé dans `state.json`) ; `state.json` reste.
- **Paquet manquant** : par défaut un env dédié fait par errand (venv uv, `errand-svc-<paquet>-<version>`), un env existant en choix ; la description d'un paquet installé ici d'abord, celle du store sinon, dite.
- **Besoins et tri** : `platforms`, `gpus`/`gpu_ram`/`gpu_kind`/`ram`, `tools`, `package`, le store ; tri prêt → installable (ici d'abord, puis le moins de lignes / le moins à porter) → grisé avec la raison.

## Tour 3

- **Description du store** : pour lancer, jamais celle du store, seulement celle du paquet installé sur M ; pour proposer l'installation : paquet sur M, puis ici, puis store ; sources de confiance par utilisateur (`errand.sources`, défaut PyPI, conda-forge, download.blender.org), une source hors liste en rouge et refusée sans `--source <url>` tapé ; un `pip -e` est trouvé (`direct_url.json`), jamais proposé, et vaut un paquet installé.
- **Copie du store** : un bouton de la page la déclenche (pas de ligne à taper) ; copie dans le cache d'errand sur M, tenue à jour tant que la vue est ouverte, taille dite avant ; rien à copier si M partage le FS d'une machine qui a une copie.
- **Hash de version** : `errand-services.json` liste les fichiers qui font la version (`version_of`) ; version = 8 hexa de `sha256( protocole + contenus )`, calculée pareil par le producteur et par errand en lisant des fichiers ; errand recalcule juste avant de lancer ; `GET /errand/identity` abandonné.
- **Diagnostic, quand** : la machine choisie à l'ouverture ; les autres à l'ouverture du menu, en parallèle (« … », « injoignable » après 10 s) ; gardé par machine jusqu'à *Refresh* ou changement des fichiers lus.
- **Forme** : ADR 0027, qui remplace les parties « services.json », « Installing » et « runs on this machine » de 0026 (0026 garde relais, `.errand/`, `X-Errand-Root`, `?svc.`) ; amendement court à `sdot-ffi/adr/0001` §3.
