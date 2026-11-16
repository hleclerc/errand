# Arrivées (ADR 0009) : tour 4

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris n'importe quoi d'autre (réponse, objection, commentaire) sous n'importe quelle question, puis appuie sur Envoyer.

## Q13 : y a-t-il des raisons de désactiver les agents ?

`ERRAND_AGENT=off` existe : une connexion ssh par commande, rien qui reste entre deux commandes. Les raisons que je vois :

1. **Déboguer** : savoir si un problème vient des agents ou du reste.
2. **Un nœud de login qui tue les process restés en arrière-plan.** Certains centres le font (un « reaper » des sessions terminées). Un agent de login y serait tué entre deux commandes. Mais l'agent suivant fait le ménage (ADR 0008), donc on perdrait seulement la mutualisation, pas la sûreté.
3. **Aucun Python sur la machine.** Le bootstrap en fabrique un s'il n'en trouve pas, donc ce n'est plus vraiment une raison.

Aucune de ces raisons n'est un usage normal. Mais garder un mode sans agent pour chaque layer (Slurm, VM, Windows) a un coût : deux chemins à maintenir, et des garanties (propriétaire, `status`, Ctrl-C) que le mode sans agent ne donne pas.

➡️ **Recommandé :** garder `ERRAND_AGENT=off` uniquement pour déboguer, documenté comme « sans garanties ». Pas de chemin dédié dans les layers pour ce mode : une layer qui a besoin d'un agent (Slurm, VM) refuse avec un message clair au lieu d'avoir un repli. Le `srun` direct et le cmd.exe direct pour Windows disparaissent donc aussi.

**Réponse :**

Je préfère un code plus simple et plus lisible. Donc on peut se passer de cette possibilité.

---

## Q14 : demander une allocation au seuil d'une file prioritaire

Ton exemple, c'est Jean Zay : `qos_gpu_*-dev` donne une haute priorité jusqu'à 2 h (et 10 jobs à la fois). Ton `errand-envs.py` choisit déjà la qos selon la durée demandée. L'idée : demander **l'allocation** au seuil (2 h, par exemple) même si une commande n'en prend que 20 min. L'allocation passe dans la file prioritaire, et les commandes suivantes y tournent à la suite (Q10, Q11), sans repasser par la file Slurm.

Proposition de forme : une option de `Slurm` qui dit ce qu'on demande à Slurm pour l'allocation, indépendamment des besoins de chaque commande :

```python
Slurm( ..., allocation = { "time": "2:00:00" } )        # ou "gpus": 4, "nodes": 1, ...
```

- Ce qui n'est pas dit dans `allocation` vient de la commande, comme aujourd'hui.
- La qos se calcule sur le temps de l'allocation, pas sur celui de la commande.
- Une commande qui ne tient pas dans le reste de l'allocation (temps restant, GPU) en demande une autre (Q11). Il existe déjà `alive.fits`, qui compare avec le temps restant (`squeue %L`).

Sur la politesse : ce qui serait impoli, c'est de garder des ressources sans s'en servir. Avec le `keep_alive` (1 min par défaut), l'allocation est rendue dès qu'elle ne sert plus, même avant le seuil. Le vrai coût est ailleurs : sur un centre comme Jean Zay, les heures sont décomptées sur ce qui est **utilisé** (de l'allocation au relâchement), pas sur ce qui est demandé. Demander 2 h et rendre au bout de 25 min ne coûte que 25 min.

➡️ **Recommandé :** oui, une option `allocation = { … }` sur `Slurm`, qui fixe la taille de l'allocation partagée (avec la qos calculée sur elle) ; les commandes y passent tant qu'elles tiennent dans ce qui reste, et l'allocation est rendue après `keep_alive` sans usage.

**Réponse :**

---
