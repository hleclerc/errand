# La page d'un run, ses sorties, et sviz dedans : tour 4

> Laisse **Réponse** vide pour accepter la recommandation. `?` pour plus de détails.
> Écris autre chose (réponse, objection, commentaire) sous n'importe quelle question, puis Envoyer.

Ce qui existe déjà dans errand (lu dans le code ce matin) :

- `errand web` est servi par l'agent hôte, sur `http://127.0.0.1:<20000 + uid % 10000>/`, sans jeton dans le chemin. L'accès
  passe par un **cookie de session** ( `HttpOnly; SameSite=Strict`, sans durée : il disparaît quand le navigateur redémarre ),
  obtenu par un code à usage unique valable 2 min ( `?o=CODE`, ce que fait `errand web` ). Sans cookie : un formulaire de login.
- Il y a **déjà une page par run** : `/job?key=["work", machine, dossier]`, avec à gauche les faits, l'étape, les vues
  ( `errand.view` ) et les sorties ( les fichiers du dossier du run ), à droite l'aperçu : une image, un HTML dans une iframe
  sandboxée, du texte, ou la liste d'un répertoire. Les fichiers passent par `/file`, au plus 64 Mo.
- Dans le terminal, une vue s'écrit `↗ file://…` ( texte simple, que le terminal reconnaît : pas d'OSC 8 ). errand
  n'imprime **jamais** de lien http vers la page d'un run, et rien n'ouvre de navigateur pendant un run.
- Pas encore : les vues de répertoires ( ramener un `.sviz` en direct ), les ouvreurs, `errand serve`.

---

## Q1 : Le lien du run, imprimé au départ

Au lancement, la ligne de tête du run dans le terminal porte un lien vers sa page :

    ▸ exp_2d_real.py::foam (lmo-torch)  ↗ http://127.0.0.1:20501/job?key=…

Le problème, c'est l'accès : un ctrl+clic ouvre le navigateur, qui n'a peut-être plus le cookie ( il disparaît au redémarrage
du navigateur ). Trois façons :

- **(a) Le cookie dure** ( `Max-Age` d'un mois, par exemple ) : le lien reste simple, sans secret. Le premier clic après
  l'expiration montre le login ( `errand web` le règle ).
- (b) Le lien porte un code à usage unique ( `?o=` ) : il marche une fois, puis tombe sur le login s'il n'y a pas de cookie.
  Un lien qui reste dans le défilement du terminal et ne marche qu'une fois, c'est trompeur.
- (c) Un jeton propre au run dans le lien ( une capacité ) : il marche toujours, mais un lien copié ailleurs donne accès,
  et on avait écarté les capacités dans errand web.

Une machine distante : la page est celle de **mon** errand web ( l'agent hôte local lit le run à travers les agents ), donc
le lien est toujours en 127.0.0.1 local.

➡️ **Recommandé :** (a). Le cookie d'errand web dure 30 jours ( renouvelé à chaque visite ). Le lien du run, imprimé une fois
sur la ligne de tête, ne porte aucun secret.

**Réponse :**

---

## Q2 : Ouvrir la page automatiquement

Un flag de `errand run` qui ouvre la page du run dans le navigateur dès son départ.

- Le nom : `--open`, ou `--browse` ( ce que `errand web` fait déjà par défaut ) ?
- Avec plusieurs runs ( `-j`, une grille ) : un onglet par run, ou la page principale d'errand web ?
- Une valeur par défaut par utilisateur ( dans la config ), pour ceux qui le veulent toujours ?

➡️ **Recommandé :** `--open` ( court : `-O` ). Jusqu'à 4 runs, un onglet chacun ; au-delà, un seul onglet sur la page
principale. Une valeur par défaut dans la config utilisateur ( `~/.config/errand/…`, le fichier de l'ADR 0018 ) :
`errand.configure( open = True )`.

**Réponse :**

---

## Q3 : La liste à gauche

Pour démarrer, la page du run garde sa mise en page : la liste à gauche, l'aperçu à droite. Ce qui change :

- les **sorties « riches »** ( un `.html`, un `.sviz`, une image, un pdf ) viennent **en tête**, avant les fichiers ordinaires
  ( console, logs ), avec une icône par sorte ;
- un `.sviz` est **une seule ligne** ( pas la liste de ses `frames/*.bin` ), avec son état : `120 frames`, `en cours` tant
  que son manifeste n'est pas `complete` ;
- un clic l'affiche à droite ; un double-clic l'ouvre dans un onglet à lui ( comme aujourd'hui pour un HTML ).

➡️ **Recommandé :** comme ci-dessus. Les vues ( `errand.view` ) et les sorties fusionnent en une seule liste, les riches
d'abord, dans l'ordre où elles sont apparues.

**Réponse :**

---

## Q4 : Comment errand sait qu'un `.sviz` s'ouvre par un serveur

Un `.sviz` ne se lit pas en `file://` : il lui faut un serveur ( `sviz`, qui lancera lui-même `errand serve` quand
l'ADR 0018 sera fait, comme tu le voulais au tour 3 ). errand doit donc savoir, pour cette sortie, **quelle commande donne
son URL**. Deux façons :

- **(a) C'est le producteur qui le dit.** Le Visualizer en mode store, quand errand est là, déclare sa vue avec son
  ouvreur : `errand.view( "foam.sviz", open = "sviz open --url {path}" )`. errand garde ça dans le journal du run ; il n'a
  rien à savoir de sviz. Marche pour tout utilisateur de sdot, sans configuration.
- (b) Une table d'ouvreurs côté utilisateur ( `errand.openers[ "*.sviz" ] = "sviz open --url {path}"` dans
  `~/.config/errand/…` ) : à déclarer sur chaque machine, par chaque utilisateur.

Dans les deux cas, errand lance la commande **sur la machine qui conduit le run** ( là où le répertoire est ramené ), lit
l'URL qu'elle imprime, et la met dans la page et dans le terminal.

➡️ **Recommandé :** (a), avec (b) en surcharge possible plus tard si un besoin apparaît. La forme : un paramètre `open`
de `errand.view`, une commande avec `{path}`, qui imprime une URL et rend la main ( le serveur, lui, reste ).

**Réponse :**

---

## Q5 : Un `.sviz` dans la page du run, et dans le terminal

Avec son URL ( `http://127.0.0.1:<port de sviz>/<jeton>/<id>/` ) :

- **dans la page du run** : l'aperçu à droite est une iframe sur cette URL. Elle est d'une autre origine ( autre port ), et
  le jeton est dans le chemin : pas de cookie à partager, rien à ouvrir dans errand web. Le viewer suit le run tout seul
  ( il relit son manifeste ) ;
- **dans le terminal** : la vue s'écrit `↗ http://127.0.0.1:…/<jeton>/<id>/` au lieu de `↗ file://…/index.html`, qui ne
  marcherait pas ; un ctrl+clic ouvre le viewer directement ;
- le HTML autonome de la fin ( `foam.html` ) reste une sortie comme les autres, en `file://`.

Un run **distant** : le `.sviz` est ramené en direct dans le projet ( l'étape 5 de l'ADR 0017, les vues de répertoires ), et
c'est la copie locale que sviz sert. Avant l'étape 5, il n'arrive qu'à la fin, avec `-o`.

➡️ **Recommandé :** comme ci-dessus. La ligne `↗ http://…` est imprimée dès que le store a sa première frame ramenée.

**Réponse :**

---

## Q6 : L'ordre du travail

1. **Le lien du run et `--open`** ( Q1, Q2 ) : utile tout de suite, pour tous les runs.
2. **La liste à gauche** ( Q3 ) : les sorties riches d'abord, un `.sviz` sur une ligne.
3. **Les vues de répertoires** : un `.sviz` ramené en direct d'une machine distante ( ADR 0017, étape 5 ).
4. **Les ouvreurs** ( Q4, Q5 ) : `errand.view( open = )`, l'URL de sviz dans la page et le terminal ; sdot déclare son ouvreur.
5. Plus tard, avec l'ADR 0018 : sviz passe par `errand serve --ensure`.

Ces décisions vont dans l'ADR 0017 ( sa section 5 est réécrite ), pas dans un nouvel ADR.

➡️ **Recommandé :** cet ordre, et la section 5 de l'ADR 0017 réécrite avant de coder.

**Réponse :**

---
