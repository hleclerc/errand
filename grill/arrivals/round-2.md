# Arrivées (ADR 0009) : tour 2

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris n'importe quoi d'autre (réponse, objection, commentaire) sous n'importe quelle question, puis appuie sur Envoyer.

Décisions du tour 1 : `grill/arrivals/decisions.md`.

## Q5 : arrivée exclusive ou partagée

Deux sortes d'arrivées :

- **Exclusive** : elle n'est demandée que par une commande. C'est le cas d'un `srun` ou d'un `salloc` attendu : le job est à elle.
- **Partagée** : plusieurs commandes peuvent l'attendre ou s'en servir. C'est le cas de l'allocation chaude, qui est un seul `sbatch` retrouvé par toutes les commandes du même environnement (`~/.cache/errand/alloc/<nom>/job`), et de la VM.

Annuler une arrivée partagée parce qu'**une** commande est partie casserait les autres.

➡️ **Recommandé :**
- Une arrivée exclusive enregistre une annulation, comme aujourd'hui pour `srun`.
- Une arrivée partagée n'en enregistre pas : chaque commande qui l'attend tient **son propre bail** (`wanted-<id>`), et l'agent qui arrive part tout de suite si aucun bail n'est frais.
- Un job partagé encore en file ne coûte rien. S'il démarre sans personne pour l'attendre, il s'arrête dans la minute.

**Réponse :**

En fait, pour moi, tout était partagé. L'idée pour srun pourrait être que les processus à lancer y sont exclusifs par défaut, mais l'allocation et l'agent sont partagés.

---

## Q6 : la passation

Que devient l'annulation enregistrée quand l'arrivée a son propre propriétaire ?

Dans le seul cas exclusif qu'on ait, `srun`, aucun agent n'arrive sur le nœud : `srun` reste le lien jusqu'au bout, et l'annulation n'est lancée qu'à la fin d'un stop (ADR 0008). Si le job est déjà fini, `scancel` d'un nom qui n'existe plus ne fait rien.

➡️ **Recommandé :** pas de retrait explicite. L'annulation reste armée tant que le process qui attend vit, et elle n'est lancée qu'à la fin d'un stop : elle n'agit que sur ce qui reste. Un retrait ne deviendrait nécessaire que si une arrivée exclusive survivait au process qui l'attend, ce qui n'existe pas aujourd'hui.

**Réponse :**

---

## Q7 : la VM est-elle déjà conforme ?

Pour la VM, ces règles sont déjà en place depuis l'étape 2 de l'ADR 0008 :
- le keeper est le propriétaire, sur le même hôte que QEMU ;
- le bail, c'est `use.lock`, tenu par chaque commande, plus le guest occupé ;
- l'arrivée orpheline, c'est le `keep` : sans commande, la VM s'arrête après son délai.

La seule différence avec la décision du tour 1 : une VM que plus personne n'attend pendant son boot reste jusqu'à la fin de son `keep` au lieu de partir tout de suite.

➡️ **Recommandé :** la VM est conforme. On ajoute seulement : si plus personne ne tient `use.lock` à la fin du boot et que la VM n'a jamais servi, elle s'arrête tout de suite au lieu d'attendre son `keep`.

**Réponse :**

---

## Q8 : affichage des attentes dans `status`

Le process qui attend écrit dans sa fiche un fichier `waiting` (`{ "what", "since", "for", "job" }`), mis à jour quand l'état change (en file, en configuration, en cours). `table` le lit avec les process, et `status` l'affiche :

```
  sdot-ffi
    jz   3f2a9c1e  run tests/x.py::*  --env h100  waiting: slurm job 81234 pending, 2 h 10
  lmo: windows vm 80103674 booting, 4 min
```

Pour l'allocation chaude, c'est la boucle du nœud de login qui l'écrit (en file, puis démarrée).

➡️ **Recommandé :** oui, un fichier `waiting` dans la fiche du process, écrit par celui qui attend ; le texte affiché vient de lui (« slurm job 81234 pending »).

**Réponse :**

---
