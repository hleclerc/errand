# errand serve (et sviz) : tour 1

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris autre chose (réponse, objection, commentaire) sous n'importe quelle question, puis Envoyer.

Contexte : un **service** est un processus de longue durée, lancé à la demande, arrêté quand plus personne
ne s'en sert, éventuellement sous une réservation de la file (Ollama : 10 Go de carte, busy/warm). Deux
usages : le gardien `ollama-errand` de boucles sur lmo, et `sviz`, le petit serveur qui montre les
répertoires `.sdot_viz`. Ce tour pose ce qui ne dépend pas encore du code ( une exploration de
`queue.py`, des agents et de leur transport est en cours pour le tour 2 ).

## Q1 : À qui appartient un service ?

Deux possibilités :

- **(a) à l'agent de la machine** (l'agent hôte, celui qui possède déjà ce qu'il lance, ADR 0008) : la
  commande qui l'a demandé peut partir, le service reste, `errand status` le voit, l'agent l'arrête.
  `errand serve …` rend la main une fois le service prêt (ou reste au premier plan avec `-f`, et
  Ctrl-C l'arrête) ;
- **(b) à un processus `errand serve` au premier plan**, comme `ollama serve` : c'est lui le gardien ;
  pour le faire durer, il faut le détacher soi-même (nohup, systemd, le relais qui le lance).

(b) est ce que fait le script aujourd'hui. (a) supprime le « qui lance le gardien, sous quel verrou » :
c'est l'agent, qui est déjà unique par utilisateur et par machine.

➡️ **Recommandé :** (a), avec `-f` pour le premier plan.

**Réponse :**

---

## Q2 : Qu'est-ce que « plus personne ne s'en sert » ? ( ta remarque )

Le risque que tu soulignes : un serveur qui réfléchit longtemps avant de répondre ne fait passer aucun
octet, et un compteur de débit le croirait abandonné.

Proposition : **l'activité, ce sont les connexions ouvertes, pas les octets.**

- tant qu'au moins une connexion est ouverte, le service est utilisé, même silencieux pendant une
  heure ;
- tant que la sonde (s'il y en a une) dit `busy`, il est utilisé, même sans connexion ( Ollama avec un
  modèle chargé ) ;
- l'horloge de `--idle` ne part qu'au moment où il n'y a **plus aucune connexion et pas de busy** ; elle
  repart de zéro à la connexion suivante.

Un client qui garde une connexion ouverte pour rien (keep-alive HTTP d'un navigateur, d'une
bibliothèque) retarde l'arrêt : c'est le prix, et c'est le bon sens du risque ( garder trop longtemps,
jamais tuer en plein calcul ). Le `--idle` d'un serveur sans réservation ( sviz ) ne coûte que de la
mémoire.

➡️ **Recommandé :** oui, connexions ouvertes + sonde busy ; jamais le débit.

**Réponse :**

---

## Q3 : Comment errand voit-il les connexions ?

Q2 suppose qu'errand compte les connexions. Trois moyens :

- **(a) errand tient le port** : le service écoute sur un port interne qu'errand lui donne ( `$PORT`,
  ou `{port}` dans sa commande ), et l'agent écoute sur le port annoncé, et relaie. Toute connexion
  passe par errand, qui la compte. Coût : un saut de plus, en Python ( négligeable pour des tokens
  d'Ollama ou des frames de 80 kB ) ;
- **(b) errand regarde le système** : les connexions établies sur le port ( `/proc/net/tcp` sous
  Linux, `lsof`/`netstat` sur macOS, autre chose sous Windows ) ;
- **(c) seulement les connexions qui passent par `errand serve connect` / `forward`** : un client
  qui va directement sur le port n'est pas vu.

(a) est portable et exact ; (b) dépend du système ; (c) rate le navigateur local de sviz.

➡️ **Recommandé :** (a), errand tient le port.

**Réponse :**

---

## Q4 : Un service a un nom, et il n'y en a qu'un par nom ?

Un service est identifié par **( utilisateur, machine, nom )**. `errand serve --ensure ollama` :
s'il tourne, rend son adresse ; sinon le lance, attend qu'il réponde ( une connexion acceptée sur son
port interne ), et rend l'adresse. Deux demandes simultanées n'en lancent qu'un ( c'est l'agent qui
décide, sous son verrou ). Le nom par défaut : l'étiquette ( `-n` ) ou le premier mot de la commande.

➡️ **Recommandé :** oui.

**Réponse :**

---

## Q5 : Où est écrite la définition d'un service ?

Le relais de boucles est une commande imposée dans `authorized_keys` : il ne peut porter que le nom du
service, pas toute sa définition ( besoins, sonde, commande, variables ). Deux formes :

- **(a) déclarée, comme les envs** : `errand.services[ "ollama" ] = errand.Service( [ "ollama", "serve" ],
  gpus = 1, gpu_ram = "10G", idle = "10m", probe = …, env = { … } )` dans un fichier de l'utilisateur sur
  la machine, puis `errand serve ollama`, `errand serve connect ollama` ;
- **(b) seulement en ligne de commande** : `errand serve --gpus 1 … -- ollama serve`, et le relais
  répète la commande entière.

Les deux peuvent coexister : la ligne de commande pour un essai, le fichier pour ce qui dure. (Où vit
ce fichier : tour 2, selon ce qu'errand lit déjà par utilisateur.)

➡️ **Recommandé :** (a) déclarée, (b) aussi pour un service ad hoc.

**Réponse :**

---

## Q6 : sviz : où tourne le serveur d'un run fait sur lmo ?

- **(a) ici, sur le Mac**, sur le répertoire `.sdot_viz` qu'errand ramène en direct ( la vue d'un
  répertoire, ADR 0017 révisé ) ; `sviz` est un service de l'agent du Mac, sans réservation ;
- **(b) sur lmo**, comme service de l'agent de lmo, atteint par `errand serve forward` : rien n'est
  ramené, seules les frames regardées traversent.

(a) d'abord : plus simple, marche après coup et hors ligne ; (b) devient possible gratuitement dès
que `forward` existe ( il sert aussi à Ollama ), pour des runs trop gros à ramener.

➡️ **Recommandé :** (a) par défaut ; (b) possible avec `sviz open --there` une fois `forward` fait.

**Réponse :**

---

## Q7 : sviz dépend-il d'errand ?

`sviz open xyz.sdot_viz` :

- avec errand installé : `errand serve --ensure sviz` ( un serveur par utilisateur, qui sert tous les
  répertoires ouverts ), inscrit le répertoire, ouvre le navigateur ;
- sans errand : lance le même serveur détaché, qui s'arrête de lui-même après inactivité.

sdot ne dépend donc pas d'errand ; le serveur de sviz est en Python stdlib ( fichiers statiques + la
surveillance du dossier ), et ne s'exécute **jamais dans le processus de l'agent** ( un processus
possédé par l'agent : l'agent reste léger, et un bug du viewer ne l'emporte pas ).

➡️ **Recommandé :** oui à tout cela.

**Réponse :**

---
