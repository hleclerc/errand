# Arrivées (ADR 0009) : décisions

- **Périmètre** : toutes les attentes partagent le vocabulaire et sont visibles dans `status` ; la règle complète (annulation, bail, départ à vide) ne s'applique qu'à ce qui consomme des ressources durablement, c'est-à-dire Slurm et la VM. Les démarrages courts (bridge, zygote) gardent leur échéance.
- **Propriétaire provisoire** : l'agent du process qui attend, sur la machine de ce process. L'annulation est déposée dans sa fiche (`ERRAND_PROC_DIR/cancel`, ex-`on_stop`), avec ce qui est attendu et depuis quand.
- **Arrivée orpheline** : un bail en fichier (`wanted`, touché toutes les 30 s), lu par l'agent qui arrive ; s'il a plus de 60 s, l'agent part tout de suite. Sans fichier lisible (pas de système de fichiers partagé), on s'en tient au délai d'inactivité.
- **Échéances** : aucune par défaut pour les files d'attente (Slurm, queue errand, place pour la VM) ; chaque arrivée enregistre `since` et apparaît dans `status`. Une option `wait =` n'est ajoutée que si le besoin se présente.
- **Partage** (Q5, réponse de Hugo) : tout est partagé. Une allocation et son agent sont partagés ; ce sont les process qu'on y lance qui sont exclusifs par défaut. (Conséquences au tour 3.)
- **Passation** : pas de retrait explicite ; une annulation reste armée tant que son process vit et n'est lancée qu'à la fin d'un stop.
- **VM** : déjà conforme (keeper propriétaire, `use.lock` comme bail, `keep`) ; en plus, une VM jamais utilisée dont plus personne ne tient `use.lock` à la fin du boot s'arrête tout de suite.
- **Affichage** : un fichier `waiting` dans la fiche du process qui attend (`what`, `since`, `for`, `job`), lu par `table` et affiché par `status`.
- **Plus de `srun` sans agent** (Q9) : toute commande Slurm passe par une allocation avec agent (`keep_alive = 0` : une allocation pour la commande, rendue à sa fin). Le `srun` direct ne reste que comme repli sans agents (question suivante : faut-il garder ce mode).
- **Exclusif par défaut** (Q10) : une commande réserve toute l'allocation dans la queue du nœud ; avec des besoins déclarés, une part seulement. Hugo ajoute la granularité de Slurm : demander une allocation au seuil d'une file prioritaire et y faire passer plusieurs calculs (tour 4).
- **Allocation occupée** (Q11) : nouvelle allocation si elle est trop petite, sinon attente dans la queue du nœud, en disant sur quoi on attend.
- **`scancel` et jobs surveillés** (Q12) : le `cancel` de `srun` part avec `srun`, le mécanisme reste ; le job surveillé (`watch`) reste une exception assumée, possédé par Slurm et son `--time`.
- **Plus de mode sans agent** (Q13, Hugo : « un code plus simple et plus lisible ») : `ERRAND_AGENT=off` disparaît, avec tous ses replis (`srun` direct, cmd.exe direct pour Windows, ssh par commande). Restent `hub` et `direct`.
- **Allocation au seuil** (Q14) : `Slurm( allocation = { … } )` fixe la taille de l'allocation partagée (la qos se calcule sur elle) ; les commandes y passent tant qu'elles tiennent dans ce qui reste ; elle est rendue après `keep_alive` sans usage.
