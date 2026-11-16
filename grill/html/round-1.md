# errand html : tour 1

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris n'importe quoi d'autre (réponse, objection, commentaire) sous une question, puis Envoyer.

Contexte : `errand tui` demande déjà tout aux agents ( `look` : `table`, `seen`, `ls`, `tail`, `kill` ) via `tui/machines.py`, et construit la liste dans `tui/rows.py`. La page HTML montrerait la même chose : machines, ce qui tourne, ce qui attend, VMs et invités, historique, fichiers et sortie d'un run.

## Q1 : où tourne le serveur HTTP ?

- **(a) Un serveur local** ( `errand web` ), sur la machine où on le lance : il demande à chaque machine via son agent, exactement comme `errand tui` ( `machines.watched()` + hub ). Aucun code nouveau dans les agents ; une seule page pour toutes les machines.
- **(b) Dans chaque agent** : chaque agent sert sa propre page. Il faut ouvrir un port par machine, l'auth sur chaque machine partagée, et la vue « toutes les machines » n'existe plus (ou un agent doit demander aux autres).

Le `decisions.md` du tui disait « served by the agents » ; je pense que (a) donne la même chose en plus simple et plus sûr.

➡️ **Recommandé :** (a) un serveur local `errand web`, qui demande aux agents comme le tui.

**Réponse :**

L'idée, c'est (b), mais sans auth, uniquement pour un accès local. Je ne m'attend pas à ce qu'on cherche à se connecter à distance.

---

## Q2 : port et accès

Si Q1 = (a) : écoute sur `127.0.0.1` seulement, port fixe par défaut ( ex. `8793` ), `--port` pour changer, et `errand web` ouvre le navigateur. Pour voir depuis ailleurs ( ex. lancé sur lmo, regardé depuis le Mac ) : `ssh -L 8793:localhost:8793 lmo`, rien de plus. Pas de socket unix (les navigateurs ne savent pas s'y connecter sans proxy).

➡️ **Recommandé :** `127.0.0.1:8793`, `--port`, ouverture du navigateur ; l'accès distant par tunnel ssh.

**Réponse :**

---

## Q3 : authentification

Sur une machine partagée ( lmo, n22 ), `127.0.0.1` est visible de tous les utilisateurs de la machine : n'importe qui peut lire tes fichiers de run ( `tail` ) et tuer tes process ( `kill` ). Sur le Mac c'est sans enjeu, mais autant faire pareil partout.

Proposition : un jeton aléatoire tiré au démarrage, mis dans l'URL ouverte ( `http://127.0.0.1:8793/?t=…` ), puis posé en cookie `HttpOnly; SameSite=Strict` ; toute requête sans le bon jeton → 403. Ça couvre aussi les autres pages web de ton navigateur (CSRF, DNS rebinding : on vérifie aussi l'en-tête `Host`).

➡️ **Recommandé :** jeton aléatoire par lancement, dans l'URL puis cookie, + contrôle de `Host`.

**Réponse :**

---

## Q4 : arrêter depuis la page ?

Le tui permet `s` + confirmation ( ligne `cancel` puis INT/TERM/KILL via l'op `kill` ). Dans la page : un bouton « arrêter » sur un process, avec confirmation ( `confirm()` ), en POST protégé par le jeton. Arrêt d'une VM : pareil si le tui le fait. Pas d'arrêt d'agent.

➡️ **Recommandé :** oui, mêmes actions que le tui (process, VM), POST + confirmation + jeton.

**Réponse :**

---

## Q5 : rafraîchissement

- **Polling** : la page redemande `/state` (JSON) toutes les 2–3 s et redessine ; la sortie d'un run se suit avec `tail` à partir d'un offset. Simple, marche avec `http.server` + `ThreadingHTTPServer`.
- **SSE** : le serveur pousse ; plus réactif, mais une connexion tenue par onglet et plus de code, pour un gain faible vu que les tables sont lues toutes les 2–3 s de toute façon.

Rendu : une seule page HTML + un peu de JS inline (pas de framework, pas de build), le serveur ne sert que du JSON après la page.

➡️ **Recommandé :** polling ( 2 s ), page unique avec JS inline, JSON derrière.

**Réponse :**

Polling pour l'instant

---
