# Services d'une page, par machine : tour 3

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris autre chose (réponse, objection, commentaire) sous n'importe quelle question, puis Envoyer.

Décisions : [decisions.md](decisions.md). Compris pour Q9 : le store copie la **description** (le JSON), le code vient
de dépôts ou d'une install locale. Ce tour en tire les conséquences, puis la forme de l'ADR.

---

## Q15 : La description copiée dans le store : quand compte-t-elle ?

Une description venue du store nomme des sources : `pip: sdot==2026.11.3` sur tel index, `blender` à telle URL avec
tel sha256. Un store malhonnête peut nommer `paquet-piégé` ou `https://evil/blender.tar.xz` avec le bon hash *de son
fichier*. Le code vient bien « d'un dépôt », mais du dépôt choisi par le store.

Proposition :

1. **Pour lancer**, errand n'utilise **jamais** la description du store : seulement celle du paquet **installé sur M**
   (dans l'env qui le fournit). Le store ne sert qu'à *proposer l'installation*.
2. **Pour proposer l'installation**, ordre de confiance : la description d'un paquet installé sur M, puis ici (la
   machine qui sert la page), puis celle du store.
3. **Sources de confiance**, par utilisateur, dans la config d'errand (`errand.sources = [ "https://pypi.org/simple",
   "conda-forge", "https://download.blender.org/" ]`, ces trois par défaut) : une ligne vers une source hors liste
   est montrée **en rouge**, avec « source inconnue, nommée par le store » ; la commande refuse sans `--source <url>`
   répété explicitement par la personne.
4. Une install locale (`pip -e ~/Projects/sdot-ffi`) n'est jamais proposée par errand ; elle est **trouvée** par le
   diagnostic (`direct_url.json` du `dist-info`) et vaut un paquet installé.

➡️ **Recommandé :** les quatre points.

**Réponse :**

---

## Q16 : Copier le store sur une machine qui ne l'a pas

Tu veux qu'errand propose de copier le contenu. Comme pour le reste, une **ligne à taper** (la page ne fait rien) :

```
# copie runs/foam.sviz ( 1.3 GB, 412 fichiers ) vers n14, dans le cache d'errand ( ~/.cache/errand/views/<id>/ )
errand view copy --on n14 <id de la vue>
```

- où : une zone de cache d'errand sur M (ADR 0022 : vue par système de fichiers ; si n14 partage le FS d'une machine
  qui a déjà une copie, rien à copier) ;
- tenue à jour : comme une vue ramenée (ADR 0017), relue quand la vue change ici ; ou copie figée ;
- retirée : avec la vue, par `errand caches` (purge par la main ou l'âge).

➡️ **Recommandé :** ligne `errand view copy --on M <vue>` ; copie dans le cache d'errand, **tenue à jour** tant que
la vue est ouverte ; la taille est dite avant.

**Réponse :**

Ça serait plus facile que la page provoque la copie si appui sur un bouton.

---

## Q17 : Le hash de version, calculé par qui ?

Pour que le diagnostic dise « lmo-jax fournit `blender#3fa29c1e` » sans rien exécuter, errand doit pouvoir calculer la
version **en lisant des fichiers**. Proposition : `errand-services.json` liste, par service, les fichiers qui font sa
version :

```json
"blender": { "protocol": 1, "version_of": [ "viz/services/blender.py" ], … }
```

version = 8 premiers hexa de `sha256( protocol + contenu des fichiers, dans l'ordre )`. Le producteur (sdot, en écrivant
le store) et errand (sur chaque machine) calculent la même chose ; ça marche aussi pour un `pip -e` dont le checkout a
bougé (« le checkout de lmo fournit `blender#91c0d2aa`, le store demande `#3fa29c1e` »). Le contrôle au démarrage
(`GET /errand/identity`, tour 1) devient inutile : errand recalcule juste avant de lancer.

➡️ **Recommandé :** tel quel, et on abandonne `GET /errand/identity`.

**Réponse :**

---

## Q18 : Quand le diagnostic tourne

Le menu propose toutes les machines. Interroger tous les agents à l'ouverture de la page réveille des connexions ssh
vers chaque hôte (n14, Jean Zay…).

- à l'ouverture : l'état de la machine **choisie** pour chaque service (souvent *ici*) ;
- à l'ouverture du menu des machines : les autres, en parallèle, chacune s'affiche quand elle répond (« … » avant,
  « injoignable » après 10 s) ;
- gardé par machine (dans errand, ici) jusqu'à *Refresh* ou un changement des fichiers lus ;
- *Refresh* : la machine choisie, ou toutes si le menu est ouvert.

➡️ **Recommandé :** tel quel.

**Réponse :**

---

## Q19 : La forme du document

Le tour 1 change le format de `services.json`, le modèle de confiance, l'endroit où tourne un service, la liste des
services : c'est plus qu'un amendement.

- **(a) ADR 0027** « A page's services run on the machine one chooses, as packages describe them », qui remplace
  les parties « The directory says what it asks for », « Installing » et « For now, the service runs on this machine »
  de 0026 ; 0026 garde le relais, `.errand/`, `X-Errand-Root`, `?svc.`, et reçoit une ligne « amended by 0027 » ;
- **(b) un amendement** en bas de 0026.

Côté sdot, `sdot-ffi/adr/0001` §3 reçoit un amendement court (le paquet porte `errand-services.json`, le store une copie).

➡️ **Recommandé :** (a), plus l'amendement court côté sdot.

**Réponse :**

---
