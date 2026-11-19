# errand serve (et sviz) : tour 3

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris autre chose (réponse, objection, commentaire) sous n'importe quelle question, puis Envoyer.

Tour 2 : tout accepté. Le service est posé ; ce tour relie sviz, les vues d'errand et la sécurité, et
fixe l'ordre du travail.

## Q1 : La vue d'un répertoire, ramenée en direct

Aujourd'hui `errand.view( fichier )` ramène ce fichier dès qu'il est nommé, et de nouveau à chaque fois
qu'il est renommé ( la dernière version arrive toujours, jamais un transfert par appel ). Pour un
répertoire :

- **nommé à nouveau = ramène ce qui a changé** : les fichiers absents ici, et ceux dont la taille ou la
  date diffère ( le manifeste ) ; rien n'est supprimé ici ;
- le Recorder ( par le Visualizer en mode store ) renomme la vue après chaque frame écrite : une ligne
  de journal, rien de plus ;
- errand ne surveille pas le dossier de lui-même : c'est le run qui dit quand il a changé ;
- le manifeste est ramené en dernier, pour qu'une page ne lise jamais une frame qu'il annonce et qui
  ne serait pas encore là.

➡️ **Recommandé :** oui.

**Réponse :**

---

## Q2 : Qui ouvre quoi : des « ouvreurs » selon le nom

Pour qu'errand ouvre un `xyz.sviz` avec sviz sans rien savoir de sdot :

- **(a) des ouvreurs déclarés**, comme les services : `errand.openers[ "*.sviz" ] = "sviz open --url {path}"`
  ( dans `~/.config/errand/services.py`, ou un fichier de projet ; sdot peut en suggérer un ). La
  commande rend une URL ; errand la dit ( `OUTPUT: http://…` ) au lieu du chemin, et `errand web` met
  un bouton « ouvrir » ;
- **(b) le répertoire dit lui-même son ouvreur** ( un fichier dedans ) : rejeté, ce serait un run, peut-
  être sur une autre machine, qui choisit une commande exécutée ici ;
- **(c) errand sert lui-même tout répertoire qui contient un `index.html`** : marche sans sviz, mais
  refait dans `errand web` ce que sviz fait.

➡️ **Recommandé :** (a) ; pas (b) ; (c) non plus pour l'instant.

**Réponse :**

Je pensais que sviz allait lancer lui même errand avec le bon serveur.
Pour la visu dans le html, il faudra effectivement des règles.

---

## Q3 : Qui peut se connecter à un service ?

Un port sur 127.0.0.1 est ouvert à **tous les utilisateurs** de la machine. Sur lmo, partagé, le port
d'Ollama l'est déjà aujourd'hui ; le port interne d'un service l'est forcément ( c'est le serveur qui
l'ouvre ). errand peut ne pas ajouter de porte de plus :

- **le port annoncé est optionnel** : sans `port =`, pas d'écoute TCP publique ; on n'y accède que par
  `connect` / `forward`, qui passent par l'agent de l'utilisateur ( socket unix à lui seul ) ;
- avec `port =` ( le navigateur local de sviz en a besoin ), errand ne contrôle pas l'accès : c'est au
  service de le faire. **sviz met un jeton dans son URL** ( comme `errand web` ) ;
- la doc le dit : un port déclaré sur une machine partagée est visible des autres comptes.

➡️ **Recommandé :** oui.

**Réponse :**

---

## Q4 : Les commandes de sviz, et les exports

- `sviz open DIR` : le service ( par errand s'il est là, sinon détaché ), le répertoire inscrit, le
  navigateur ouvert ; `--url` rend l'URL sans ouvrir ( pour l'ouvreur d'errand ) ; `--there` plus tard
  ( par `forward` ).
- `sviz export DIR --html out.html [--every k] [--frames a:b] [--max-mb N]` : la page autonome.
- `sviz export DIR --vtk out/` : la série ParaView ( `write_vtk` existe ).
- **le GIF ( et une vidéo )** reste un bouton de la page, qui sait déjà le faire ; `sviz export --gif`
  en ligne de commande viendra plus tard, s'il le faut ( il demande un navigateur sans écran ).

➡️ **Recommandé :** oui.

**Réponse :**

---

## Q5 : Le nom de l'extension

`xyz.sdot_viz` ( ta proposition ) ou `xyz.sviz` ( le nom de la commande, plus court ) ? Sous macOS, l'un
ou l'autre peut devenir un « paquet » que le Finder ouvre avec une petite application plus tard.

➡️ **Recommandé :** `.sviz`.

**Réponse :**

---

## Q6 : Les ADR et l'ordre du travail

- **ADR 0017 réécrit** : le format du répertoire, le Visualizer en mode store, la page qui lit des
  chunks, sviz, la vue d'un répertoire ramenée en direct, les ouvreurs. La route `/s/<cap>/` disparaît.
- **ADR 0018 `errand serve`** : tout ce qui a été décidé sur les services, `connect`, `forward`,
  `errand hold`, la file FIFO.

Ordre proposé, du gain le plus immédiat ( les pages d'otrec ) au plus général :

1. sdot : store, page qui lit les chunks, `sviz open` / `export` seul, sans errand ;
2. otrec : `Recorder( store = )` ;
3. errand : vue d'un répertoire ramenée en direct, ouvreurs ;
4. errand serve : gardien, sonde, FIFO, `connect`, `hold` ( remplace `ollama-errand` ) ; sviz passe
   par lui ;
5. `forward`, puis `sviz open --there`.

➡️ **Recommandé :** deux ADR, dans cet ordre.

**Réponse :**

---
