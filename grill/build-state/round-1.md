# État des constructions d'errand : tour 1

> Laisse **Réponse** vide pour accepter la recommandation. `?` demande plus de détails.
> Écris autre chose (réponse, objection, commentaire) sous n'importe quelle question, puis Envoyer.

## Ce qui s'est passé avec manylinux.sif

**Cause probable : l'adoption, pas l'empreinte.** Dans `setup.ensure`, un environnement jamais vu dont l'artefact existe est « adopté » : rien n'est construit, et `_record` écrit quand même l'empreinte *voulue*, comme si elle avait été construite.

Les indices :

- `bef9ea009177c151` ( `env-lin_wheels.yaml`, 14/10 07:29 ) : je l'ai recalculée, c'est exactement le `.def` pinné du commit `ef3f4a2`, avec `--nv --bind /data` et le scratch `/data/tmp`.
- Le `.sif` date du 13/10, donc d'avant cet enregistrement. `_record` ne s'exécute qu'après un build réussi ou sur le chemin « rien à faire » : aucun build n'a pu produire ce fichier le 14 ( sauf copie conservant la date ).
- `lin_wheels` apparaît avec `errand-envs.py`, le 14/10. Avant, le même `.sif` était suivi sous le nom `manylinux` ( `env-manylinux.yaml`, 13/10, empreinte `c7e40dfd…` ). Nom nouveau, donc pas de record, donc adoption.

Non vérifié : je n'ai pas relu l'image sur lmo ( date et deffile viennent du constat de départ ), et rien ne trace directement la commande de 07:29. Le décalage se serait aussi corrigé tout seul : ta modification de `manylinux.def` de ce matin ( CCCL ) change l'empreinte en `b7e0ea58…`.

**Trois défauts distincts, donc :**

1. L'adoption enregistre une affirmation fausse ( « construit depuis ce `.def` » ) au lieu de « trouvé là, origine inconnue ».
2. Le record est rangé par nom d'environnement et sur le Mac, alors que l'artefact est sur lmo : renommer l'env, ou changer de checkout, fait tout oublier.
3. `probe` ne teste que l'existence.

---

## Q1 : Où vit le record d'une construction ?

| | A. Sur le Mac ( aujourd'hui ) | B. `.errand/` de la machine qui porte l'artefact | C. Fichier à côté de l'artefact |
|---|---|---|---|
| Fichiers visibles | aucun | aucun ( `.errand/` est déjà ignoré, et exclu du `--delete` de `push` ) | 1 par artefact, à côté du `.sif` |
| Renommer l'env | tout est oublié | survit si la clé est l'artefact | survit |
| Autre checkout / autre Mac | oublié | partagé | partagé |
| `errand envs` sur un env ssh | `unknown` | peut répondre ( lecture là-bas ) | peut répondre |
| `mv` du `.sif` à la main | sans objet | record perdu, donc adoption | suit si on déplace les deux |
| Uniforme entre couches | oui | oui | non : un prefix conda ou une image docker n'ont pas d'« à côté » simple |

Coût de B et C : la lecture du record se fait sur la machine distante, mais `_present` y fait déjà un `ssh` par couche ; les deux peuvent tenir dans le même appel.

➡️ **Recommandé :** B, avec une clé par artefact et non par env ( `.errand/build-manylinux.sif.yaml` ). Les `env-*.yaml` actuels du Mac sont abandonnés. Un `.sif` déplacé à la main est simplement ré-adopté.

**Réponse :**

Oui pour une clé par artefact. Attention à éviter le fouillis et la collision de noms de fichiers dans .errand

---

## Q2 : Quel rôle pour les dates de modification ?

Ce qu'elles valent ici :

- **Elles auraient attrapé ce cas** : `.def` du 14/10, plus récent que le `.sif` du 13/10. `rsync -a` conserve les dates, donc la comparaison a un sens sur lmo.
- **Faux positifs** : `git checkout`, `git pull`, un clone neuf ou un `touch` rendent le `.def` plus récent sans rien changer. Ici, ça coûte un build complet de manylinux pour rien.
- **Faux négatifs** : `flags`, `pip`, `scratch` ne sont pas des fichiers. Et une image copiée ( `relay`, `build_on` ) prend la date de la copie, pas celle du build.

Les options :

- **a. À la place de l'empreinte** : perd `flags` / `pip`, et reconstruit à chaque changement de branche.
- **b. En plus, partout** : stale si l'empreinte diffère *ou* si le `.def` est plus récent. Garde les faux positifs.
- **c. Seulement quand il n'y a pas de record**, c'est-à-dire à l'adoption : c'est le seul moment où l'empreinte ne sait rien, et donc le seul où une date apporte quelque chose.

Pour Apptainer il existe mieux qu'une date à ce moment-là : `apptainer inspect --deffile` rend le `.def` gravé dans l'image, ce qui permet une comparaison exacte avec la recette. C'est ainsi que le décalage a été vu. C'est propre à Apptainer ; les dates restent le repli générique.

➡️ **Recommandé :** c. L'empreinte reste la référence dès qu'un record existe. À l'adoption, la couche donne un indice : le deffile gravé pour Apptainer, la date sinon.

**Réponse :**

Pour moi, c'est un problème "universel" et pas spécifique à apptainer. Il faut donc qu'on propose une solution "universelles". Je ne suis pas opposé à l'utilisation de somme de contrôle lorsque le temps d'évaluation n'est pas trop important.

---

## Q3 : Que dit le record après une adoption ?

Aujourd'hui l'adoption écrit l'empreinte voulue, et c'est le défaut n°1. Proposition : le record dit `origin: adopted`, avec la date et l'empreinte vue à ce moment-là comme simple base de comparaison, et `errand envs` affiche `adopted` au lieu de `ok`. Un changement ultérieur de la déclaration reste une raison de reconstruire, comme aujourd'hui. Le principe de `upkeep.md` tient toujours : on ne casse rien à la première lecture.

➡️ **Recommandé :** oui, l'adoption est dite telle quelle dans le record et dans `errand envs`.

**Réponse :**

---

## Q4 : Construire à côté, puis renommer ?

Ton attente : ne pas supprimer l'existant tout de suite. Aujourd'hui, `apptainer build --force` écrit directement sur `manylinux.sif`. Je ne sais pas à quel moment apptainer retire l'ancien ( pas vérifié, et je ne vais pas tester sur lmo pendant le rebuild ) ; dans tous les cas errand ne devrait pas dépendre de ce détail.

Proposition : `apptainer build manylinux.sif.new …`, puis `mv` une fois tout réussi, comme `relay` le fait déjà avec `.part`. L'ancienne image reste entière et utilisable pendant le build et après un échec. `--force` ne sert plus que pour écraser un `.new` abandonné. Coût : deux images sur le disque pendant le build. Un `.new` raté est gardé jusqu'au build suivant, ou effacé tout de suite ( au choix ).

➡️ **Recommandé :** oui, et un `.new` raté est effacé tout de suite ( il ne sert à rien, et les logs disent ce qui s'est passé ).

**Réponse :**

Oui c'est top. Je ne sais pas si on peut le généraliser à tous les types d'artefacts, mais si on peut le faire, c'est top.

---

## Q5 : Si le build échoue, le run continue-t-il sur l'ancienne image ?

Aujourd'hui : `could not prepare lin_wheels`, le run s'arrête, et `--no-setup` permet déjà d'entrer dans l'existant.

- **a. Arrêter** comme aujourd'hui, mais en disant qu'une image existe, de quand elle date, et que `--no-setup` l'utilise.
- **b. Continuer sur l'ancienne avec un avertissement.** Pratique, mais c'est précisément comme ça qu'on publie des wheels avec le mauvais jax : un avertissement au milieu d'un long log ne se voit pas.

➡️ **Recommandé :** a. Utiliser l'ancienne image reste possible, mais c'est un choix explicite.

**Réponse :**

a

---

## Q6 : Retenter à chaque run, même si rien n'a changé depuis l'échec ?

Tu attends un nouvel essai à chaque fois, et c'est déjà le comportement ( le record n'est écrit qu'après un succès ). La question est le coût : un build qui échoue au bout de 30 minutes sur une erreur déterministe recommence à chaque `errand run`.

- **a. Toujours retenter** : simple, et ça couvre les échecs passagers ( réseau, disque plein, `/data/tmp` ).
- **b. Retenter seulement si la déclaration a changé** depuis l'échec, sinon arrêter tout de suite en montrant le log ; `errand setup` retente explicitement.

➡️ **Recommandé :** a, ce que tu demandais. Le mode b pourra venir plus tard si ça gêne vraiment, et il n'exige rien de plus que le record de Q7.

**Réponse :**

a

---

## Q7 : Que garde-t-on, et combien de fichiers ?

Ta réserve porte sur le poids et la pollution. Proposition bornée, sans historique :

Par artefact, deux fichiers au plus, dans `.errand/`, tous deux réécrits à chaque tentative :

```yaml
# .errand/build-manylinux.sif.yaml
built:                   # ce que l'image EST : ne change qu'après un succès
  fingerprint: b7e0ea580c31521e
  origin: built          # ou adopted
  date: 2026-11-04 10:12
  by: hugo.leclerc@mac   # d'où ça a été lancé
last_attempt:            # présent seulement si la dernière a échoué
  fingerprint: …
  date: …
  step: apptainer build …
  code: 255
```

```
.errand/build-manylinux.sif.log    # sortie de la dernière tentative, écrasée à chaque fois
```

Le nombre de fichiers ne croît donc pas avec le nombre de builds. `errand envs` peut afficher `stale ( last build failed, 2026-11-04 )`. Le log, lui, suppose de capturer la sortie en plus de l'afficher ( `tty = True` aujourd'hui ).

Alternatives : pas de log ( le yaml seul, mais on perd l'erreur une fois le terminal fermé ) ; un historique daté ( ce que tu craignais ).

➡️ **Recommandé :** le yaml et le dernier log, pas d'historique.

**Réponse :**

---
