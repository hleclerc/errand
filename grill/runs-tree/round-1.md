# L'onglet runs en arbre : tour 1

> Laisse **Réponse** vide pour accepter la recommandation. `?` pour plus de détails.
> Écris autre chose ( réponse, objection, commentaire ) sous n'importe quelle question, puis Envoyer.

Aujourd'hui ( `tui/rows.py`, partagé par `errand tui` et `errand web` ) : « en cours », « en attente », puis les runs finis
**par jour**, toutes machines mêlées. Ce qu'un run sait de lui ( `~/.cache/errand/seen/*.json`, sur sa machine, et son
`result.yaml` ) : son dossier, le projet ( `~/Projects` : le projet errand est tout `~/Projects` ), `what` =
`otrec/experiments/exp_2d_real.py::foam row=500 n=10000 …`, son environnement, sa date, son statut et sa durée.

Faits relevés :

- Un dossier de run : `errand-outputs/runs/<chemin du fichier>/<entrée>/<date>-<env>@<machine>-<paramètres>~<hash>`.
- Un même jeu de paramètres de foam a déjà **34 dossiers** ( des relances ).
- Un run sur lmo ramené par `-o` existe **deux fois** : sur lmo, et sa copie ici, au même chemin relatif.
- L'ADR 0019 dit « ce que fait un run n'est pas à errand de l'enlever » ( dans le cadre des synchronisations ).
  Une suppression **demandée par toi** est un autre cas, à trancher ici ( Q5 ).

---

## Q1 : Les niveaux de l'arbre

« Projet » : comme le projet errand est tout `~/Projects`, les projets au sens où tu l'entends ( otrec, sdot-ffi, errand )
sont les **premiers dossiers du chemin du fichier**. Je propose l'arbre des **chemins** :

    otrec/
      experiments/exp_2d_real.py          ( un dossier qui n'a qu'un enfant est fusionné avec lui )
        foam                              l'entrée ( test, expérience )
          [ tableau des jeux de paramètres ]
            un jeu → ses runs ( dates, machine, env, statut, durée )
    sdot-ffi/
      tests/
        test_viz_store.py
          …

➡️ **Recommandé :** cet arbre ( dossiers → fichier → entrée → jeux de paramètres → runs ), les dossiers à un seul enfant
fusionnés, chaque niveau repliable.

**Réponse :**

---

## Q2 : Machine et environnement

Un même cas tourne sur lmo, sur le Mac, sur node14 :

- **(a) des colonnes** au niveau des runs ( et du jeu de paramètres : « dernier : lmo-torch, PASS, il y a 3 min » ), pas un
  niveau de l'arbre ;
- (b) un niveau de l'arbre ( machine → projet → … ), comme le reste de l'onglet machines.

Le run ramené par `-o` ( sur lmo **et** ici ) : **une seule ligne**, « lmo, copie ici », pas deux.

➡️ **Recommandé :** (a), et un run ramené compté une fois.

**Réponse :**

---

## Q3 : Les jeux de paramètres en tableau

Sous une entrée, un **tableau** : une ligne par jeu de paramètres distinct, une colonne par paramètre ( les noms en tête,
les valeurs alignées ), puis : statut du dernier run, sa date, sa durée, le nombre de runs. Un clic sur un en-tête trie ;
un clic sur une ligne la déplie ( ses runs ). Une entrée sans paramètres : pas de tableau, ses runs directement.

Deux runs sont du **même jeu** quand leurs paramètres sont égaux ; l'environnement et la machine n'en font pas partie.

➡️ **Recommandé :** comme ci-dessus. Les résultats que le run a déclarés ( `p.results[ … ]`, dans `result.yaml` ) en colonnes
aussi, à droite des paramètres, pour comparer.

**Réponse :**

---

## Q4 : L'ordre et ce qui est déplié à l'ouverture

- l'ordre à chaque niveau : **la dernière activité d'abord** ( un dossier remonte quand un de ses runs tourne ) ;
- à l'ouverture : tout replié au niveau des dossiers du haut ( otrec/, sdot-ffi/, errand/ ), sauf **ce qui tourne ou attend**,
  déplié jusqu'à son run ;
- « en cours » et « en attente » restent **en tête**, en liste courte ( comme aujourd'hui ), et les runs y figurent aussi à
  leur place dans l'arbre ;
- ce qui a été déplié ou replié à la main est retenu ( le navigateur, la TUI ).

➡️ **Recommandé :** comme ci-dessus.

**Réponse :**

---

## Q5 : Effacer : quoi, et comment

À chaque niveau ( dossier, fichier, entrée, jeu de paramètres, run ) :

- « **ne garder que le plus récent** » : pour chaque jeu de paramètres dessous, le run le plus récent reste, les autres
  partent ( par jeu **et** par environnement : un résultat sur lmo-torch et un sur jax restent tous deux ) ;
- « **effacer** » : tous les runs dessous.

Ce qui part : le **dossier du run** sur sa machine ( par son agent ) **et** sa copie ici quand elle existe. Rien hors du
dossier d'un run. Jamais un run qui tourne ou attend. Une confirmation qui dit combien de runs, sur quelles machines, et la
place libérée.

La façon :

- **(a) une corbeille** : les dossiers déplacés dans `errand-outputs/trash/<date>/` sur leur machine ( un `mv`, instantané ),
  vidée après 7 jours, ou à la main ( `errand runs empty-trash`, un bouton ) ; « annuler » remet en place tant qu'elle n'est
  pas vidée ;
- (b) effacés pour de bon, tout de suite.

➡️ **Recommandé :** (a). L'ADR 0019 garde son sens ( errand n'enlève jamais de lui-même ce qu'un run a fait ) : ici c'est
toi qui le demandes, run par run, avec une confirmation.

**Réponse :**

b. Et il faudra effacer aussi à distance.

---

## Q6 : La TUI

`tui/rows.py` construit les lignes pour `errand tui` et `errand web` à la fois.

- **(a) le même arbre dans la TUI**, le tableau des paramètres en colonnes alignées ( le tri : une touche, `s`, qui passe
  d'une colonne à la suivante ), effacer par les touches `d` ( effacer ) et `D` ( garder le plus récent ), avec la même
  confirmation ;
- (b) l'arbre seulement dans la page web, la TUI garde la liste par jour.

➡️ **Recommandé :** (a) : un seul modèle, deux dessins.

**Réponse :**

---

## Q7 : Où c'est décrit, et l'ordre du travail

Un nouvel ADR ( 0023, « les runs en arbre, et les effacer » ), puis :

1. le modèle : l'arbre et les jeux de paramètres, depuis les liens `seen` et les `result.yaml` de chaque machine ( un run
   ramené compté une fois ) ;
2. la page web : l'arbre, le tableau triable ;
3. la TUI : le même arbre ;
4. effacer : l'opération de l'agent ( déplacer vers la corbeille ), la confirmation, annuler, la corbeille vidée.

➡️ **Recommandé :** cet ordre, l'ADR écrit d'abord.

**Réponse :**

---
