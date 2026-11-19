# errand serve (et sviz) : tour 2

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris autre chose (réponse, objection, commentaire) sous n'importe quelle question, puis Envoyer.

Tour 1 : tout accepté ( `decisions.md` ). Ce tour s'appuie sur ce que fait le code aujourd'hui
( `facts.md` ) : une réservation est un fichier tenu par un fil qui le touche toutes les 5 s ;
`python -m errand.queue hold` dit `granted`, lit `warm` / `busy`, dit `evict` ; l'agent arrête un
groupe de processus par INT, TERM à 2 s, KILL à 5 s ; un processus `keep=True` survit à son client
( le gardien de la VM Windows ) ; les trames des agents portent déjà des octets bruts ( rsync y passe ),
mais il n'y a ni redirection de port ni opération « socket ».

## Q1 : Qui fait tourner la boucle du service ?

Un **gardien** par service, processus `keep=True` de l'agent hôte, comme celui de la VM :
`python -m errand.serve keep <nom>`, stdlib seulement. Il tient la réservation ( le fil de 5 s ), le
port annoncé et le relais vers le port interne, la sonde, le processus du service ( son enfant, dans
son groupe ), les règles d'arrêt. L'agent ne fait que le lancer sous son verrou, le lister, l'arrêter.
Un gardien qui meurt : l'agent tue le groupe du service ( ADR 0008 ) et la réservation périme en 30 s.

➡️ **Recommandé :** oui, un gardien par service, sur le modèle de celui de la VM.

**Réponse :**

---

## Q2 : La forme de la sonde

Elle ne sert qu'à dire `busy` ( réservation ferme ) ou non ; l'activité par les connexions existe
sans elle ( tour 1 ). Formes proposées :

- **dans la déclaration ( Python )** : une fonction, `busy = lambda port: …`, ou des aides toutes
  faites, par exemple pour Ollama
  `busy = errand.http_json( "/api/ps", lambda r: bool( r[ "models" ] ) )` ;
- **en ligne de commande** : `--busy-if CMD` ( code de sortie 0 = occupé ; `{port}` remplacé ) ;
- appelée toutes les 2 s par le gardien, avec un délai ( 5 s ).

**Une sonde qui ne répond pas, ou échoue, compte comme busy** : un serveur saturé qui ne répond plus
à `/api/ps` est justement en plein calcul ( c'est ta remarque, appliquée à la sonde ). Revers : un
serveur planté garde la carte ; le gardien le voit mourir par son processus, pas par la sonde. Sans
sonde, un service avec réservation est warm dès qu'il n'a plus de connexion.

➡️ **Recommandé :** fonction dans la déclaration, `--busy-if CMD` en ligne de commande, échec = busy.

**Réponse :**

---

## Q3 : « Sans être doublée » : l'ordre de la file

Aujourd'hui, seule une demande **exclusive** ( ou qui grandit ) s'inscrit dans `waiting/` ; une demande
ordinaire n'est inscrite nulle part, re-demande toutes les 0,25 s, et une demande arrivée après elle qui
tient passe devant. Pour qu'un service qui attend sa carte ne soit pas doublé :

- **(a) toute demande en attente s'inscrit**, et `_fits` fait passer en premier la plus ancienne
  ( FIFO pour tous, `errand run` compris ) ;
- **(b) seulement les services** s'inscrivent.

(a) change la file pour tout le monde, mais c'est la règle qu'on attendrait ; un petit calcul qui
tiendrait à côté d'une demande qui attend toute la carte attendrait derrière elle ( pas de « backfill » ).

➡️ **Recommandé :** (a), FIFO pour toute demande, sans backfill pour l'instant.

**Réponse :**

---

## Q4 : Pendant l'attente de la carte

Le port annoncé est tenu dès le lancement : une connexion qui arrive pendant l'attente est acceptée et
**attend** ( comme ton relais ), puis est relayée dès que le service répond. Le gardien abandonne
l'attente quand **plus personne n'attend** depuis `--idle` ( plus aucune connexion ouverte, plus
aucun `--ensure` en cours ) : c'est ton `ATTENTE_MAX`, ramené à la même règle. `errand status` montre
« waits for gpu ( 2 connections waiting ) ».

➡️ **Recommandé :** oui.

**Réponse :**

---

## Q5 : Prêt, et ports

- **Prêt** = le port interne accepte une connexion ( ou `ready = ` une fonction, si un serveur
  accepte avant d'être prêt ).
- **Port interne** : choisi libre par errand, donné à la commande par `{port}` dans ses arguments et
  dans son `env` ( `OLLAMA_HOST = "127.0.0.1:{port}"` ) et par `$PORT`.
- **Port annoncé** : `port = 11435` s'il est déclaré ; sinon errand en choisit un et **le garde pour ce
  nom** ( noté dans `~/.cache/errand/` ), pour que l'URL de sviz reste la même d'une fois à l'autre.
  Toujours sur 127.0.0.1.

➡️ **Recommandé :** oui.

**Réponse :**

---

## Q6 : `connect` et `forward`

- **`errand serve connect <nom>`**, sur la machine du service : lance le service s'il manque, attend,
  relaie l'entrée et la sortie standard vers le port annoncé. C'est ce que met `command=` dans
  `authorized_keys` ( le relais de boucles ).
- **`errand serve forward --env lmo <nom> [--port N]`**, ici : un port local, chaque connexion passant
  par les agents ( une voie par connexion TCP ) jusqu'au port annoncé là-bas, le service lancé s'il
  manque. Une **opération native de l'agent** ( « ouvre une connexion à 127.0.0.1:P et relaie-la » )
  plutôt qu'un petit processus pont par connexion. Le transfert reste dans le canal ssh déjà ouvert :
  pas de `ssh -L`.

`forward` peut venir après le reste ( sviz n'en a pas besoin au début, tour 1 Q6 ).

➡️ **Recommandé :** les deux, `connect` d'abord, `forward` en opération native de l'agent ensuite.

**Réponse :**

---

## Q7 : Où vit la déclaration d'un service ?

Les envs sont lus dans le projet et ses parents ( `~/Projects/errand-envs.py` ) ; errand ne lit rien
par utilisateur hors d'un projet. Or un service est à une machine et un utilisateur, pas à un projet :
le relais de boucles est lancé par ssh depuis `~`, hors de tout projet.

- **(a) un fichier par utilisateur** : `~/.config/errand/services.py` ( `$XDG_CONFIG_HOME` ), lu par
  `errand serve` où qu'on soit ; un projet peut aussi déclarer les siens dans ses fichiers ;
- **(b) seulement dans les fichiers de projet**, et le relais fait `cd` dans un projet d'abord.

➡️ **Recommandé :** (a), plus les fichiers de projet.

**Réponse :**

---

## Q8 : L'arrêt

Le gardien arrête le service par la séquence de l'agent ( INT, TERM, KILL sur le groupe ), avec
`grace = ` ( délai avant KILL, 10 s par défaut pour un serveur qui doit vider sa carte ), puis rend la
réservation. Quand :

- expulsion demandée **pendant warm** ( une demande busy efface l'expulsion, comme aujourd'hui ) ;
- `--idle` passé sans connexion ni busy ;
- Ctrl-C au premier plan ( `-f` ), ou `errand serve stop <nom>` ;
- le service meurt de lui-même : le gardien s'arrête aussi ( pas de relance automatique ; la
  connexion suivante le relance ).

➡️ **Recommandé :** oui.

**Réponse :**

---

## Q9 : Ce qu'on voit, et `errand hold`

- `errand status` liste les services : nom, état ( waits for gpu, starting, busy, warm, idle depuis ),
  connexions, port ; et, au passage, les réservations de la file, qu'il ne montre pas aujourd'hui.
  `errand queue` les montre avec leur étiquette et « kept warm: gives way » quand warm.
- `errand hold [besoins] [-n étiquette]` : le protocole actuel de `python -m errand.queue hold`
  ( `granted`, `warm` / `busy`, `evict`, fin à la fermeture de l'entrée ) devient une commande
  documentée, sans changement pour la VM.
- La doc dit que la file est par utilisateur et par machine : un serveur lancé sous un autre compte
  ( un service systemd ) n'est pas vu.

➡️ **Recommandé :** oui.

**Réponse :**

---
