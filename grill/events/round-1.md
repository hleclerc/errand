# Des événements plutôt que de l'interrogation : tour 1

> Laisse **Réponse** vide pour accepter la recommandation. `?` pour plus de détails.
> Écris autre chose ( réponse, objection, commentaire ) sous n'importe quelle question, puis Envoyer.

Ce qui est déjà poussé, et ce qui interroge encore ( lu dans le code ) :

- **Agent → veilleur** ( errand web, la TUI ) : déjà un flux ouvert ( `op: watch` ), qui envoie `table`, `seen`,
  `resources`, `alive`. L'agent réveille déjà ses veilleurs quand il lance un process ou le voit finir ( `look.nudge` ).
- **Mais la boucle `watch` de l'agent interroge** : la date de quelques dossiers toutes les quelques secondes, la table
  entière au moins toutes les 2 s, l'historique toutes les 5 s ( le coût d'avant-hier : 1,2 s à chaque fois ), les
  ressources toutes les 5 s, un battement toutes les 10 s.
- **La page interroge errand web** toutes les 2 s ( `/state`, `/detail` ) : peu coûteux ( il répond de mémoire ), mais
  c'est 2 s de retard sur tout.
- **La console d'un run en cours** est relue par sa fin ( `tail` ), par l'agent, à chaque `/detail`.

Ce que les agents savent sans regarder : un run commence et finit dans un process qu'ils ont lancé ( le lien `seen` est
écrit au début, `result.yaml` à la fin ) ; sa sortie passe par leur tuyau ; ses étapes et ses vues passent par sa session
en marques.

---

## Q1 : Le but

« Rien ne tourne quand rien ne se passe » : un agent ne fait rien entre deux événements, sauf ce qui ne peut pas
s'annoncer ( la charge d'une carte, d'un CPU ) et un balayage lent de sécurité. Une page ou la TUI voient un changement
**dès qu'il a lieu** ( pas 2 s plus tard ).

➡️ **Recommandé :** ce but, pour l'agent, errand web, la page et la TUI.

**Réponse :**

---

## Q2 : Ce que l'agent annonce

Des événements qui portent **ce qui a changé**, pas tout l'état :

- un process lancé, fini ( avec sa ligne de la table ) ;
- un run noté ( son lien `seen` ), un run fini ( son statut, sa durée, ses paramètres, ses résultats ), un run effacé ;
- une étape d'un run ( `errand.step` ), une vue ( `errand.view` ) ;
- des lignes de sortie d'un run en cours ( pour qui les demande, Q6 ) ;
- les ressources, mesurées ( Q4 ).

À l'abonnement, et après une reconnexion, **un état complet** ( la table, l'historique ), puis les événements. Pas de
rejeu d'événements manqués : l'état complet suffit.

➡️ **Recommandé :** comme ci-dessus.

**Réponse :**

---

## Q3 : Ce que l'agent ne voit pas passer

Un process orphelin, une VM qui s'arrête, un run lancé sans errand dans un dossier suivi, un dossier de run effacé à la
main. Pour eux :

- **(a) un balayage lent** : la table et l'historique recalculés toutes les **60 s**, et à chaque nouvel abonnement ;
  un écart trouvé est annoncé comme un événement ;
- (b) des notifications du système de fichiers ( kqueue, inotify ) : hors de la bibliothèque standard de Python, et
  différentes sur chaque système.

➡️ **Recommandé :** (a).

**Réponse :**

---

## Q4 : Les ressources

La charge CPU, GPU, la mémoire ne s'annoncent pas : il faut les mesurer.

- **(a) seulement quand quelqu'un les regarde** : un veilleur dit s'il veut les ressources ( l'onglet machines ouvert,
  la jauge d'une machine affichée ) ; sinon l'agent ne mesure rien ; quand il mesure, toutes les 5 s, envoyé seulement
  si ça a bougé de quelques points ( comme aujourd'hui ) ;
- (b) toujours toutes les 5 s, comme aujourd'hui.

➡️ **Recommandé :** (a).

**Réponse :**

---

## Q5 : La page et errand web

- **(a) un flux poussé** ( Server-Sent Events, `/events` : un `EventSource` du navigateur, la bibliothèque standard
  côté serveur ) : errand web y envoie un court avis « la liste a changé », « le détail de ce run a changé » dès qu'un
  événement d'agent arrive ; la page relit alors `/state` ou `/detail` comme aujourd'hui. Plus d'interrogation toutes
  les 2 s ;
- (b) le flux porte les lignes elles-mêmes ( plus de travail côté page, moins de requêtes ) ;
- (c) des WebSockets ( pas dans la bibliothèque standard ).

➡️ **Recommandé :** (a) : peu de changement dans la page ( elle sait déjà relire ), et une requête seulement quand il y a
quelque chose.

**Réponse :**

---

## Q6 : La console d'un run en cours

- **(a) en flux** : quand le détail d'un run en cours est ouvert, errand web s'abonne à sa sortie auprès de l'agent
  ( comme `errand attach` le fait déjà ), et la pousse dans la page ligne à ligne ; plus de `tail` répétés ;
- (b) garder la relecture par la fin, mais seulement quand l'agent annonce de la nouvelle sortie.

➡️ **Recommandé :** (a).

**Réponse :**

---

## Q7 : La TUI

Elle reçoit déjà les événements des agents ( le même `watch` ). Elle redessine aujourd'hui sur une minuterie.

➡️ **Recommandé :** elle redessine sur un événement ou une touche ; seules les durées qui défilent ( « 13 s so far » )
avancent à la seconde, sans rien demander à personne.

**Réponse :**

---

## Q8 : Les agents d'anciennes sources

Un agent qui tourne encore l'ancien code ne parle pas ce protocole.

➡️ **Recommandé :** le veilleur accepte les deux : un agent ancien garde sa boucle qui interroge ( elle est la sienne ),
un agent récent pousse ; rien de plus. Les agents se remplacent d'eux-mêmes ( un agent par empreinte des sources ).

**Réponse :**

On peut virer les anciens agents. Je relancerai les calculs

---

## Q9 : L'ADR et l'ordre du travail

Un ADR 0024 ( « les agents disent ce qui change » ), puis :

1. l'agent : les événements, le balayage de 60 s, les ressources à la demande ;
2. errand web : `/events`, la page qui ne relit que sur avis ;
3. la console en flux ;
4. la TUI.

➡️ **Recommandé :** cet ordre, l'ADR d'abord.

**Réponse :**

---
