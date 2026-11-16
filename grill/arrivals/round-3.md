# Arrivées (ADR 0009) : tour 3

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris n'importe quoi d'autre (réponse, objection, commentaire) sous n'importe quelle question, puis appuie sur Envoyer.

Ta réponse à Q5 : *tout est partagé ; pour srun, les process à lancer y sont exclusifs par défaut, mais l'allocation et l'agent sont partagés.* Voici ce que j'en comprends, à confirmer.

## Q9 : plus de `srun` sans agent

Aujourd'hui, un `Slurm` passe par deux chemins :

- **L'allocation chaude**, le cas par défaut (`keep_alive` absent, donc `KEEP_WARM = "1m"`). C'est un `sbatch` dont l'étape principale est un agent ; les commandes y passent par cet agent.
- **Un `srun` (ou `salloc`) par commande**, sans agent sur le nœud. Il sert avec `keep_alive = 0`, pour une commande qui ne tient pas dans l'allocation chaude, pour `errand shell` (`--pty`) et quand les agents sont désactivés.

Si tout est partagé, le second chemin disparaît. Toute commande Slurm passe par une allocation qui a son agent :
- **`keep_alive = 0`** : une allocation pour cette commande, rendue dès que la commande se termine.
- **Une commande qui ne tient pas dans l'allocation chaude** : une autre allocation, elle aussi avec son agent, partageable par la suite.
- **`errand shell`** : un terminal à travers l'agent du nœud (les agents savent déjà le faire).
- **Les rangs MPI** : lancés par l'agent du nœud avec un `srun` interne à l'allocation, ce qui est déjà le cas dans l'allocation chaude.
- **Agents désactivés** (`ERRAND_AGENT=off`) : on garde le `srun` actuel, comme repli.

➡️ **Recommandé :** oui, toute commande Slurm passe par une allocation avec agent ; le `srun` par commande ne reste que comme repli quand les agents sont désactivés.

**Réponse :**

Oui... par contre, est-ce qu'il y a des raisons de désactiver les agents ?

---

## Q10 : « process exclusifs par défaut »

Je le comprends ainsi : dans une allocation, une commande prend par défaut **toute** l'allocation. Une deuxième commande qui veut la même allocation attend la fin de la première, ou en prend une autre si elle ne veut pas attendre (Q11). Si la commande demande moins (`--cpus 4`, `--gpus 1`, ou ce que dit l'entrée), elle ne prend que ça, et une autre commande peut tourner à côté. Ce partage se fait par la queue errand du nœud, qui sait déjà découper une machine.

➡️ **Recommandé :** oui. Par défaut, une commande réserve toute l'allocation dans la queue du nœud ; avec des besoins déclarés, elle n'en réserve qu'une part.

**Réponse :**

Oui c'est exactement ça. En fait, il y a aussi la question de la granularité de slurm. Certains queues prioritaires peuvent fonctionner avec un seuil. On pourrait demander ce seuil (en option dans la layer) pour que ça passe dans cette queue prioritaire, en précisant que le calcul prend moins, ce qui permet de passer un autre calcul dans la foulée...

Je ne pense pas que ça soit malpoli, mais je veux bien en discuter.

---

## Q11 : une allocation occupée

Une commande arrive alors que l'allocation existante est occupée (Q10) ou trop petite. Deux possibilités :

- **(a) Attendre** dans la queue du nœud que la place se libère.
- **(b) Demander une nouvelle allocation** à Slurm, avec son propre agent, partageable ensuite.

Aujourd'hui, une commande qui ne tient pas passe par un `srun` à elle (b), après avoir rendu l'allocation chaude si personne ne s'en sert.

➡️ **Recommandé :** (b) quand l'allocation est trop petite, sinon (a) : attendre la fin d'une commande en cours coûte en général moins qu'un nouveau passage dans la file Slurm. La commande dit sur quoi elle attend.

**Réponse :**

---

## Q12 : `scancel` et jobs surveillés

1. **Le `cancel` posé sur `srun`** (ADR 0008, étape 4) n'a plus de raison d'être quand `srun` disparaît : l'allocation est partagée, et ce sont les baux qui la gouvernent. Le mécanisme `cancel` reste dans l'agent, pour d'autres usages.
2. **Le job surveillé** (`watch = N`) : un `sbatch` par commande, interrogé de loin, conçu pour les clusters où une connexion ne tient pas aussi longtemps que la file. Il n'a pas d'agent, et Ctrl-C l'annule.

➡️ **Recommandé :**
1. On retire le `cancel` de `srun` en même temps que `srun` ; on garde le mécanisme.
2. Le job surveillé reste tel quel, une exception assumée : son propriétaire, c'est Slurm lui-même, avec son `--time`.

**Réponse :**

---
