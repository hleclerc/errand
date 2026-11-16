# errand tui, refonte : tour 1

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris n'importe quoi d'autre (réponse, objection, commentaire) sous une question, puis Envoyer.

Contexte : `errand status` sait déjà tout lire. Il lit `table.scan()` ici, et `standing.remote_table()` sur chaque machine du ledger. Le second passe par un ssh qui ne démarre pas d'agent, et coûte **1,35 s pour lmo** (mesuré aujourd'hui). Les `waiting` (ADR 0009), les VMs, les zygotes, les orphelins et les « unowned » sont déjà dans la table. La TUI actuelle fait 1 400 lignes de curses (`errand/tui/`) plus `errand/session.py`. Seule la TUI se sert de `session.py`, qui a aussi ses propres tests (`tests/test_session.py`, `tests/_demo.py`).

---

## Q1 : écran principal

Que montre l'écran principal ?

- **A. Une liste unique, groupée par machine, avec un panneau de détail.** À gauche, chaque machine a sa ligne d'en-tête : `lmo   agent ok · 3 running · 1 waiting · lu il y a 4 s`, ou `n22   ne répond pas (timeout)`. Sous elle viennent ses VMs (`windows vm 3fa2c1 ready, 8 cpus 16G`) puis ses processus, sur une ligne chacun : projet, ce que ça fait, `--env`, depuis combien de temps, état (running, `waiting: slurm job 81234 pending, 2 min`, orphaned, unowned). Les guests sont rangés sous leur VM. À droite, le processus sélectionné : méta (pid/pgid, agent, store, cwd, depuis), son attente, et la fin de sa sortie (out et err), suivie en direct.
- B. Deux listes séparées, machines en haut et processus en bas, avec un filtre machine.
- C. Une liste à plat des processus, triée par âge, la machine en colonne.

➡️ **Recommandé :** A. Une machine, puis ce qu'elle porte, c'est l'arbre que tu as décrit (quoi tourne où) et que `status` imprime déjà. Le détail à droite évite une page de plus.

**Réponse :**

A avec tout ce que tu dis + les fichiers modifiés/en sortie qu'on pourrait lire même si ce n'est pas fini.

---

## Q2 : quels projets

Par défaut, faut-il montrer tous les projets en entier, ou seulement le projet courant en entier et une ligne par autre projet, comme `status` ?

➡️ **Recommandé :** tous les projets en entier, avec le projet courant en surbrillance, et une touche (`p`) qui restreint au projet courant. La TUI sert à surveiller les machines, et ce qui tourne pour un autre projet y occupe autant de place. Elle se lance aussi hors de tout projet : sans projet, il n'y a pas de surbrillance.

**Réponse :**

---

## Q3 : rafraîchissement et coût

- Ici (`table.scan`, lecture disque) : toutes les 2 s.
- Machines du ledger : `remote_table` dans un thread par machine, relancé 10 s après la fin du précédent. On n'en a jamais plus d'un en vol par machine, donc ça fait au plus un ssh toutes les ~11 s par machine. L'en-tête de chaque machine dit l'âge de ses données (`lu il y a 7 s`) et, en cas d'échec, l'erreur, en gardant grisée la dernière table reçue. `r` relance tout de suite.
- Le processus sélectionné : sa sortie est relue toutes les 2 s (un petit ssh `tail -c` côté machine distante), et seulement le sien.

Autre voie : faire passer tout ça par les agents via le hub (un nouvel op `table` dans `agent.py`). Ce serait plus rapide une fois le flux ouvert, mais il faut un agent démarré, et ça touche au protocole.

➡️ **Recommandé :** le ssh de `remote_table`, tel quel, au rythme ci-dessus. Il ne démarre rien, et on passera par l'agent le jour où 1,35 s gênera.

**Réponse :**

ça me paraît logique de passer par les agents.

---

## Q4 : actions

Lesquelles faut-il ?

1. **Arrêter** (`s`, puis confirmation `y`) le processus sélectionné, sur sa machine : INT, TERM après 2 s, KILL après 5 s sur le groupe (`end_group`), et d'abord la ligne `cancel` qu'il a laissée (un job Slurm, par exemple). Pour un processus distant, c'est un ssh qui lance un petit `python -m errand.agents stop <agent> <id>` (nouveau, dans `agents/__main__.py`). Ça vaut aussi pour les orphelins et les unowned.
2. **Voir la sortie entière** (`o`) dans `$PAGER` (less), curses suspendu, avec le fichier rapatrié si le processus est distant.
3. **Shell** (`x`) : `ssh -t machine` dans le cwd du processus, curses suspendu, et on revient à la sortie.
4. Arrêter une VM (`s` sur une ligne VM) : on arrête son keeper, ce qui fait comme `errand vm stop` pour cette VM seulement.
5. Arrêter un agent (`errand agents stop NAME`) depuis la ligne de la machine.

➡️ **Recommandé :** 1, 2, 3 et 4. Le 5 attendra : arrêter un agent qui tourne encore revient à arrêter ses processus, ce que le 1 fait déjà un par un.

**Réponse :**

---

## Q5 : les anciennes fonctions (lancer des cas)

Que deviennent les cases à cocher, le dialogue « où lancer », la page runs et ses fichiers, et l'aperçu ?

➡️ **Recommandé :** tout supprimer : `errand/tui/{actions,dialog,lists,tree,keys,screen,loop}.py`, `errand/session.py`, `tests/test_session.py`, et `_demo.py` s'il ne sert plus. On ne déplace rien vers `errand run`, qui affiche déjà sa sortie. On garde `terminal.py` (souris, `without_rep` pour le ncurses de macOS), `drawing.py` et `panes.py`, qui ne lancent rien. `errand tui` garde son nom, et sa ligne d'aide devient « suivre ce qui tourne, où, depuis quand ».

**Réponse :**

on supprime

---

## Q6 : bibliothèque

➡️ **Recommandé :** garder curses, de la bibliothèque standard. errand s'installe toujours sans rien, et le code souris/terminfo de macOS est déjà écrit et testé. Textual serait plus joli, mais c'est une dépendance pour une seule commande.

**Réponse :**

---

## Q7 : clavier

Dans l'ancienne TUI, les lettres servaient à chercher et les verbes étaient sur les touches de fonction. Ici, on tape peu.

➡️ **Recommandé :** les lettres comme verbes, et `/` pour un filtre texte (machine, projet ou commande, `esc` l'efface). Le jeu de touches : ↑↓ / clic pour choisir, ←→ pour plier ou déplier une machine, `s` arrêter, `o` sortie entière, `x` shell, `p` projet courant ou tout, `r` relire maintenant, `tab` pour passer du focus à la sortie (défilement), `?` aide, `q` quitter. La molette garde le comportement actuel (elle fait défiler ce qui est sous le pointeur). La ligne du bas rappelle les touches.

**Réponse :**

---

## Q8 : ce qui est fini

La table ne garde que ce qui tourne. Un processus qui finit pendant qu'on regarde disparaît-il ?

➡️ **Recommandé :** il reste grisé pendant 5 min avec `ended`, et son code de sortie si on peut le lire (fichier `exit` dans son store). La TUI ne le montre que parce qu'elle l'a vu tourner. On ne liste pas l'historique : c'est le travail des sorties du projet.

**Réponse :**

Ça sera très utile de voir aussi les anciennes sorties. Je reconnais que ça va à l'encontre de l'idée selon laquelle il ne faut pas accumuler dans le home... Peut être ça pourrait le faire si on se contente d'accumuler des liens vers des dossiers qui eux contiennent toutes les infos (historique des sorties, ...), et qui se met à jour de temps en temps lorsqu'on efface ces dossiers.

Rq en passant: comme on a des agents qui tournent en permanence, on pourra aussi faire des petits serveurs http. ça permettra de voir à la fois ce qui tourne et d'aller lire les sorties. Vu qu'on a un canal en plus des std entre les agents et les processus, je serais tenté de permettre d'envoyer des infos d'étapes qu'errand pourrait afficher en temps-réel. Pourquoi se priver ?

---

## Q9 : « la place dans la queue »

Par « attente de place », entends-tu les `waiting` déjà écrits par l'ADR 0009 (job Slurm pending, VM qui boote, place sur la machine, tout ça vient de `queue.py` via `arrival`), ou veux-tu en plus voir la file `errand queue` de chaque machine (claims en cours, demandes exclusives en attente) ?

➡️ **Recommandé :** les `waiting` de l'ADR 0009 suffisent, puisqu'ils sont attachés au processus qui attend. Plus, sur l'en-tête de chaque machine, un résumé de sa queue si `table` le donne pour pas cher : `queue : 2 claims, 1 en attente`. Il faudrait ajouter `queue.held()` et `waiting_exclusive()` à `table.scan()`, ce qui fait une petite fonction en plus dans `table.py`.

**Réponse :**

les waitings suffisent.

---
