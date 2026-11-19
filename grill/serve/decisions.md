# errand serve (et sviz) : décisions

- **Propriétaire** : un service appartient à l'agent hôte de la machine ; `errand serve` rend la main une fois prêt, `-f` le garde au premier plan ( Ctrl-C l'arrête ).
- **Activité** : les connexions ouvertes et la sonde quand elle dit busy, jamais le débit ; `--idle` ne part que sans connexion ni busy.
- **Connexions vues** : errand tient le port annoncé et relaie vers un port interne donné au service.
- **Identité** : un service par ( utilisateur, machine, nom ) ; `--ensure` le lance s'il manque, attend qu'il réponde, rend l'adresse ; jamais deux.
- **Définition** : déclarée comme les envs ( `errand.services[ … ] = errand.Service( … )` ), et aussi en ligne de commande pour un service ad hoc.
- **sviz, où** : par défaut sur le Mac, sur le répertoire ramené en direct ; sur lmo par `forward` plus tard ( `sviz open --there` ).
- **sviz et errand** : sdot ne dépend pas d'errand ; serveur stdlib, un par utilisateur, jamais dans le processus de l'agent.
- **Gardien** : un par service, processus `keep=True` de l'agent hôte ( `python -m errand.serve keep <nom>` ), stdlib ; il tient réservation, port et relais, sonde, enfant, arrêts.
- **Sonde** : fonction dans la déclaration ( aides comme `errand.http_json` ), `--busy-if CMD` en ligne de commande ; toutes les 2 s, délai 5 s ; échec ou silence = busy.
- **Ordre de la file** : toute demande en attente s'inscrit, FIFO pour tous ( `errand run` compris ), pas de backfill pour l'instant.
- **Attente de la carte** : le port est tenu dès le lancement, les connexions attendent ; l'attente est abandonnée quand plus personne n'attend depuis `--idle`.
- **Ports** : prêt = le port interne accepte ( ou `ready =` ) ; port interne libre, `{port}` / `$PORT` ; port annoncé déclaré, sinon choisi et gardé par nom ; 127.0.0.1.
- **connect / forward** : `connect` d'abord ( stdio, pour `authorized_keys` ), `forward` ensuite, en opération native de l'agent, une voie par connexion.
- **Déclaration** : `~/.config/errand/services.py` par utilisateur, plus les fichiers de projet.
- **Arrêt** : INT, TERM, KILL sur le groupe, `grace` 10 s ; sur expulsion en warm, `--idle`, Ctrl-C / `stop`, mort du service ( pas de relance automatique ).
- **Visibilité** : services et réservations dans `errand status`, `errand queue` avec « kept warm: gives way » ; `errand hold` documenté, inchangé pour la VM ; doc : file par utilisateur et machine.
- **Vue d'un répertoire** : nommée à nouveau = ce qui a changé est ramené ( absents, taille ou date différentes ), rien supprimé ; le run renomme la vue après chaque frame ; le manifeste en dernier.
- **Deux sens** : sviz lance errand ( `sviz open` → `errand serve --ensure sviz` ) ; dans l'autre sens, errand ( `errand web`, la ligne `OUTPUT:` ) trouve sviz par des règles déclarées, les ouvreurs ( `errand.openers[ "*.sviz" ] = "sviz open --url {path}"` ), jamais par le répertoire lui-même.
- **Accès** : port annoncé optionnel ( sans lui, seulement `connect` / `forward` par l'agent de l'utilisateur ) ; avec lui, au service de contrôler ; sviz met un jeton dans son URL ; la doc le dit.
- **sviz** : `open [--url] [--there plus tard]`, `export --html [--every --frames --max-mb]`, `export --vtk` ; GIF / vidéo par le bouton de la page, en ligne de commande plus tard.
- **Extension** : `.sviz`.
- **ADR et ordre** : 0017 réécrit ( format, store, page, sviz, vues de répertoires, ouvreurs ; plus de `/s/<cap>/` ), 0018 `errand serve` ; ordre : sdot + sviz seul, otrec, vues de répertoires + ouvreurs, errand serve ( remplace ollama-errand ), forward + `--there`.

## Tour 4 ( la page d'un run, ses sorties, sviz dedans )

- **Lien du run**: la ligne de tête d'un run porte `↗ http://127.0.0.1:<port>/job?key=…` ( la page de MON errand web, run local ou distant ), sans secret ; le cookie d'errand web dure 30 jours, renouvelé à chaque visite.
- **Ouverture automatique**: `errand run --open` ( `-O` ) ; jusqu'à 4 runs un onglet chacun, au-delà la page principale ; défaut par utilisateur `errand.configure( open = True )` dans la config utilisateur.
- **Liste à gauche**: vues et sorties fusionnées, les sorties riches ( html, sviz, image, pdf ) d'abord, dans l'ordre d'apparition ; un `.sviz` = une ligne avec son état ( frames, en cours ) ; clic = aperçu, double-clic = onglet.
- **Ouvreur déclaré par le producteur**: `errand.view( path, open = "sviz open --url {path}" )` ; errand lance la commande sur la machine qui conduit, lit l'URL ; une table d'ouvreurs utilisateur seulement plus tard si besoin.
- **sviz dans la page et le terminal**: iframe sur l'URL de sviz ( autre origine, jeton dans le chemin ) ; terminal `↗ http://…` dès la première frame ramenée ; le `foam.html` final reste une sortie `file://`.
- **Ordre**: lien + `--open`, liste à gauche, vues de répertoires, ouvreurs, puis `errand serve` ; la section 5 de l'ADR 0017 réécrite avant de coder.

## Tour 4 révisé et tour 5 ( l'ouvreur décrit par le producteur )

- **Ouvreur déclaré par le producteur, objet riche**: `errand.view( path, open = sdot.sviz.opener )` ; l'objet dit tout ( pas de config utilisateur ).
- **Deux sortes**: `errand.Static( "index.html" )` ( le répertoire porte sa page, servie telle quelle : même version que les données, rien d'exécuté sur le Mac ) ; `errand.Opener( command, env = errand.Uv(...) | Micromamba | ... | Node demain, name )` pour plus tard. sdot prend Static ; `sviz` reste pour qui n'a pas errand et pour `export`.
- **Serveur statique**: un second serveur de l'agent hôte, à côté d'errand web, port fixe, jeton dans le chemin, lecture seule, seulement les répertoires déclarés Static ( copie locale du run ). Pas dans errand web ( iframe sandboxée, `/act` ).
- **Opener programme ( plus tard )**: env construit dans le cache d'errand sur la machine qui conduit, une fois par tampon ; voyage en JSON dans le journal.
- **Sources**: `source = <chemin du paquet>` si éditable, traduit en chemin local quand il est dans un arbre poussé par errand ( `pip install -e` de la copie locale ), sinon `paquet==version` ; `manifest.format` protège.
- **Confiance**: pas de question ; un seul ouvreur : ouvert directement ; une liste ( `open = [ a, b ]` ) : le premier par défaut, les autres par un clic droit.
- **Ordre**: lien du run + `--open`, liste à gauche, vues de répertoires, `errand.Static` + second serveur + sdot le déclare, puis `errand.Opener` et `errand serve`.
