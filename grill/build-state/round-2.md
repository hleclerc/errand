# État des constructions d'errand : tour 2

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris autre chose (réponse, objection, commentaire) sous n'importe quelle question, puis Envoyer.

Décisions du tour 1 : [decisions.md](decisions.md).

## À savoir d'abord : le `.bak` a disparu de lmo

`manylinux.sif.2026-10-13.bak` n'est plus dans `/data/Projects-rsync/sdot-ffi` ( vérifié en lecture seule ; il ne reste que le `.sif` de ce matin 09:51 ). Cause probable, non prouvée : `push` lance `rsync --delete` et n'exclut que `*.sif`. Un fichier `*.sif.bak`, absent du Mac, est donc effacé au push suivant. J'ai prévenu la session qui reconstruit, au cas où elle l'aurait retiré elle-même.

Ça touche la conception : **tout fichier distant dont le nom ne finit pas par `.sif` est à la merci du prochain push**. C'est le cas d'un `manylinux.sif.new` ( décidé au tour 1 ) et du `.part` de `relay`.

---

## Q8 : Comment nommer ce qui est construit à côté ?

Une autre session peut pousser pendant un build de 30 minutes : un `manylinux.sif.new` serait effacé en plein travail.

- **a.** `manylinux.new.sif` : le nom garde le suffixe, déjà exclu. Marche pour les images, sans toucher à `push`.
- **b.** Le fichier en cours va dans `.errand/builds/`, exclu lui aussi. Risque : il faut que ce soit le même disque pour que le `mv` reste un renommage, et `.errand` peut être configuré ailleurs.
- **c.** Ajouter `*.sif.*` aux exclusions de `push`. Plus large, et protégerait aussi un `.bak` fait à la main.

➡️ **Recommandé :** a pour le build, et c en plus, parce que perdre 4 Go sans prévenir à cause d'un nom de fichier n'est jamais ce qu'on veut. `relay` passe aussi à `.part.sif` ou équivalent.

**Réponse :**

Je vois deux solutions:
* ou bien on rapatrie tout les artefact pour que le rsync fonctionne tel quel
* ou bien on gère proprement les fichiers à ne pas rsync-er en se basant sur le contenu des layers (avec le nom exact des fichiers, i.e. pas de suppositions sur les extensions ou ce genre de chose)

Il faut dire que le .sif ne doit pas être rsync-é systématiquement

---

## Q9 : Une détection universelle, sur deux côtés ?

Ta remarque du tour 1 : pas de solution propre à Apptainer. Proposition : le record décrit les **deux bouts** de la construction, pour toutes les couches.

- **Côté entrées** : l'empreinte actuelle. Les recettes sont petites et lues sur le Mac, la somme de contrôle coûte des millisecondes : on la garde partout, sans filtre par date.
- **Côté artefact** : un **tampon**, relevé juste après le build et comparé ensuite. C'est ce qui manque aujourd'hui : rien ne dit que l'artefact présent est bien celui que le record décrit.

Une somme de contrôle de l'artefact lui-même est trop chère : 4 Go de `.sif` à chaque run, et aucun sens pour un prefix conda. Le tampon est donc une observation bon marché, une par type d'artefact :

| Couche | Tampon | Coût |
|---|---|---|
| Apptainer | taille + date du fichier | `stat` |
| Docker / Podman | id de l'image ( `image inspect` ), qui **est** une somme de contrôle | déjà appelé par `probe` |
| Micromamba / Conda | date + taille de `conda-meta/history`, modifié à chaque installation | `stat` |
| Venv / Uv | date de `pyvenv.cfg` + du dossier `site-packages` | `stat` |
| Windows | rien à faire : l'image est déjà nommée par son empreinte | aucun |

La règle est alors la même partout :

| Situation | Verdict |
|---|---|
| pas de record | adoption |
| tampon différent | le record ne décrit plus cet artefact : il est annulé, retour à l'adoption |
| tampon identique, empreinte différente | stale, on reconstruit |
| les deux identiques | ok |

Ça couvre un `.sif` remis à la main, un `pip install` fait dans l'env, une copie depuis une autre machine. Le tampon voyage dans le même `ssh` que `probe`.

Le `apptainer inspect --deffile` du tour 1 disparaît : plus rien de spécifique.

➡️ **Recommandé :** oui, empreinte des entrées + tampon de l'artefact, avec cette règle unique.

**Réponse :**

---

## Q10 : À l'adoption, que faire si l'artefact semble plus vieux que ses entrées ?

C'est là que ta comparaison de dates sert : sans record, c'est la seule information disponible, et elle marche pour toutes les couches ( date de la recette la plus récente contre date de l'artefact ). Elle aurait attrapé `manylinux.sif`. Faux positif possible, mais seulement sur une vraie adoption : un `git pull` avant la toute première rencontre, et une fois pour tous les artefacts à la migration.

- **a. Avertir seulement** : statut `adopted ( older than scripts/manylinux.def )`. Rien n'est cassé, mais un avertissement noyé dans un log, c'est ce qu'on a refusé en Q5.
- **b. Reconstruire ce qui se construit à côté, avertir pour le reste.** Sans risque pour une image ( l'ancienne reste jusqu'au succès ). Pour Micromamba, la `danger` de `upkeep.md` tient toujours : pas de reconstruction sur une simple date.
- **c. Tout traiter comme stale.** Contredit le principe de l'adoption pour les envs conda.

➡️ **Recommandé :** b. Le coût d'un faux positif est un build de trop, une fois ; celui d'un faux négatif, des wheels publiées avec le mauvais jax.

**Réponse :**

---

## Q11 : Le build à côté, pour quelles couches ?

Tu demandais si ça se généralise. Ce que j'ai lu dans `layers.py` :

| Artefact | À côté ? | Pourquoi |
|---|---|---|
| Apptainer | oui | fichier, `mv` atomique |
| Docker / Podman | déjà le cas | le tag ne bouge qu'à la fin d'un `build -t` réussi |
| Windows | déjà le cas | nommée par empreinte, une nouvelle image ne touche pas l'ancienne |
| Micromamba / Conda | **non** | prefix non relogeable : chemins écrits en dur dans les scripts et les shebangs, un `mv` le casse. Et `build` installe dans l'existant |
| Venv / Uv | **non** | même défaut : un venv déplacé garde ses anciens chemins |

Pour les envs, le cas à traiter est un `install` qui échoue à moitié : l'env reste dans un état intermédiaire. Reconstruire à côté sous un autre nom puis basculer demanderait de changer le nom vu par `wrap`, soit une autre conception. Je propose de ne pas y aller : le yaml marque `last_attempt` en échec, `errand envs` affiche `stale ( last build failed )`, et le run s'arrête comme en Q5.

➡️ **Recommandé :** à côté pour Apptainer ( Docker et Windows l'ont déjà ), en place pour les envs, avec un échec visible dans le record.

**Réponse :**

---

## Q12 : Garder l'image précédente après un succès ?

Tu demandais de garder l'existant pendant un échec. Mais il y a un cas de plus : le build **réussit** et l'image est mauvaise. Une recette non pinnée n'est pas reproductible, donc l'ancienne image ne se refabrique pas toujours. C'est exactement pourquoi un `.bak` avait été fait à la main ce matin.

- **a. Non** : le renommage remplace l'ancienne, un seul fichier. Pas de surcoût.
- **b. Oui, une seule** : `manylinux.prev.sif`, écrasée au build suivant. Coûte une image de disque par artefact ( 4,3 Go ici ), et un fichier de plus, sans croissance. Le suffixe la protège du `--delete`.
- **c. Seulement sur demande** : `errand setup --keep-previous`.

➡️ **Recommandé :** b. Une seule, toujours, parce qu'on ne pense à demander une sauvegarde qu'après coup. Si le disque te gêne, c.

**Réponse :**

---

## Q13 : Où ranger les fichiers dans `.errand/` ?

Ta réserve : fouillis et collisions. La collision existe vraiment : `describe()` ne garde que le nom du fichier, donc `a/cuda.sif` et `b/cuda.sif` donnent la même clé.

Proposition : un seul sous-dossier, un nom lisible, et un court hash de l'identité complète ( couche + chemin ou nom complet ) :

```
.errand/builds/
    apptainer-manylinux.sif-3fa9c1d2.yaml
    apptainer-manylinux.sif-3fa9c1d2.log
    micromamba-mac_wheels-81b07e44.yaml
```

Un fichier par artefact plutôt qu'un `builds.yaml` commun : deux environnements construits en parallèle n'écrivent pas le même fichier. `.errand/` racine reste propre, et les `env-*.yaml` s'en vont.

➡️ **Recommandé :** ce layout.

**Réponse :**

---
