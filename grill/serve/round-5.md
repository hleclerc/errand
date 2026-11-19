# L'ouvreur d'une vue, décrit par le producteur : tour 5

> Laisse **Réponse** vide pour accepter la recommandation. `?` pour plus de détails.

Ta réponse au tour 4 révisé : `errand.view( path, open = sdot.sviz )`, où `sdot.sviz` contient tout, y compris
l'environnement où le lancer ( Python, ou Node si on veut ), avec l'inquiétude du lien aux sources ( un sdot en `pip -e` ).

Faits relevés :

- errand tourne dans le Python de Homebrew, sans sdot ; `sviz` n'est que dans les envs micromamba.
- errand sait déjà décrire, construire et tamponner des environnements : `errand.Uv( pip = [ … ] )`, `Micromamba`, `Venv`,
  `Apptainer`… ( `errand/layers/interpreters.py` ). Pas encore de Node.
- Le run foam sur lmo ( 10 min, 331 frames ) : 25 Mo de `foam.sviz` ramenés par `-o`, et le `foam.html` de la fin ( 32 Mo ).
  `sviz open` le montre bien : une frame qui n'est pas en cache arrive en 16 ms.
- Un `.sviz` contient déjà son `index.html`, écrit par **la version de sdot qui a écrit les données**.

---

## Q1 : Deux sortes d'ouvreurs

- **Statique** : la vue est un répertoire qui porte sa page ; il suffit de le servir tel quel.
  `errand.view( "foam.sviz", open = errand.Static( "index.html" ) )`. Aucun programme lancé sur le Mac, aucun
  environnement : la page est celle du run, donc **de la même version** que ses données ( le problème des sources disparaît ).
- **Programme** : une commande dans un environnement décrit ( `errand.Opener( [ "sviz", "open", "--url", "{path}" ],
  env = errand.Uv( pip = [ … ] ) )` ), quand il faut calculer quelque chose côté Mac : un viewer Node, un serveur qui lit un
  format binaire, etc.

Le producteur choisit. sdot déclare `sdot.viz.sviz.opener = errand.Static( "index.html" )` et l'utilise dès qu'errand est
importable ( comme `announce` ). La commande `sviz` reste pour qui n'a pas errand, et pour `export`.

➡️ **Recommandé :** les deux sortes, et sdot prend **Statique**. On ne construit l'ouvreur « programme » que quand un
premier besoin réel arrive ; l'ADR en fixe déjà la forme ( Q3, Q4 ).

**Réponse :**

---

## Q2 : Qui sert un ouvreur statique

Il ne faut pas le servir **dans** errand web : la page d'un run y est montrée dans une iframe sandboxée ( origine opaque ),
qui ne peut pas relire ses fichiers voisins avec le cookie ; et lui donner `allow-same-origin` laisserait une page de run
appeler les actions d'errand web ( `POST /act` ). Il faut donc **une autre origine** :

- un **second serveur** de l'agent hôte, à côté d'errand web : son propre port ( fixe, comme celui d'errand web ), son
  propre jeton **dans le chemin** ( `http://127.0.0.1:<port>/<jeton>/<id>/` ), qui ne sert que des fichiers, en lecture,
  sous les répertoires que des vues ont déclarés statiques ;
- ou un service `errand serve` ( ADR 0018 ) intégré, démarré à la demande et arrêté quand il ne sert plus.

➡️ **Recommandé :** le second serveur, dans l'agent hôte, toujours là comme errand web ( rien à démarrer, pas d'inactivité à
gérer ). Il ne sert que les répertoires déclarés par une vue `Static`, sous la copie locale du run.

**Réponse :**

---

## Q3 : La forme d'un ouvreur « programme » ( pour plus tard )

    errand.Opener( command, env = None, name = None )

- `command` : une liste, avec `{path}` ( la copie locale de la vue ) ; elle imprime une URL et rend la main ;
- `env` : un environnement errand ( `Uv`, `Micromamba`, `Apptainer`…, demain un `Node` ), construit **dans le cache
  d'errand** sur la machine qui conduit ( pas dans un projet ), une fois par description ( son tampon ), puis réutilisé ;
- l'objet voyage dans la ligne du journal du run ( en JSON ), et errand le reconstruit côté Mac.

➡️ **Recommandé :** cette forme ; l'ADR la décrit, rien n'est codé avant un premier utilisateur.

**Réponse :**

---

## Q4 : Le lien aux sources ( `pip -e` ), pour un ouvreur « programme »

Le run tourne avec un sdot en développement ( une copie du dépôt, poussée par errand sur lmo ). L'environnement de
l'ouvreur, construit sur le Mac, doit avoir **le même code**. Les façons :

- **(a)** la description dit `source = <chemin du paquet>` quand il est installé en éditable ; errand le **traduit en chemin
  local** quand il est dans un arbre qu'il pousse ( `~/Projects-rsync/sdot-ffi` sur lmo → `~/Projects/sdot-ffi` ici ), et
  l'environnement fait `pip install -e` de la copie locale ; sinon, `paquet==version` ;
- (b) toujours `paquet==version` depuis PyPI : faux pour une version pas encore publiée ;
- (c) l'utilisateur dit quel environnement local utiliser : de la configuration, ce que tu voulais éviter.

Le format porte de toute façon un numéro ( `manifest.format` ) : un viewer trop vieux le dit au lieu de mal afficher.

➡️ **Recommandé :** (a).

**Réponse :**

---

## Q5 : Qui décide qu'une description venue d'un run est exécutée ici

Une vue `Static` n'exécute rien sur le Mac : on sert des fichiers, et la page tourne dans le navigateur, sur une origine qui
n'a accès à rien. Un ouvreur « programme », lui, fait exécuter ici une commande choisie par un run, peut-être distant.

➡️ **Recommandé :** pour un ouvreur « programme », la première fois qu'une description apparaît ( son tampon ), errand demande
dans le terminal ( ou sur la page du run ) : « ouvrir avec … ? toujours / non ». La réponse est gardée par machine. Rien à
demander pour `Static`.

**Réponse :**

S'il n'y a pas le choix, on ouvre directement. Sinon (par exemple si on donne une liste d'openers), on pourra faire un clic droit...

---

## Q6 : Ce qui change dans l'ordre du travail

1. Le lien du run et `--open` ( inchangé ).
2. La liste à gauche ( inchangé ).
3. Les vues de répertoires ( un `.sviz` ramené en direct ).
4. **`errand.Static`** : le second serveur, l'URL dans la page du run ( iframe ) et dans le terminal ( `↗ http://…` ) ;
   sdot déclare son ouvreur statique.
5. Plus tard : `errand.Opener` ( programme, environnement, sources, confiance ), et `errand serve` ( ADR 0018 ) pour Ollama.

➡️ **Recommandé :** cet ordre ; la section 5 de l'ADR 0017 réécrite avec les tours 4 et 5 avant de coder.

**Réponse :**

---
