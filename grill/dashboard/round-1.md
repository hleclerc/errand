# Le tableau de bord d'un run : tour 1

> Laisse **Réponse** vide pour accepter la recommandation. `?` pour plus de détails.
> Écris autre chose ( réponse, objection, commentaire ) sous n'importe quelle question, puis Envoyer.

Aujourd'hui, dans la page d'un run ( et à droite de la page principale quand un run est choisi ) : à gauche les faits et
la liste des sorties ( console en tête, puis les sorties explicites, puis « errand's files » ) ; à droite **une** chose à
la fois, la console par défaut, ou la sortie cliquée ( une image, un HTML dans une iframe, un `.sviz` par `errand.Static`,
un texte, un répertoire ).

La question : afficher d'office ce qui vaut d'être regardé, sans en faire un ParaView ( rien n'est calculé, la page agence
ce que le run déclare ).

---

## Q1 : Qu'est-ce qui est « à regarder » ?

Ce qui peut prendre la grande place sans qu'on clique :

- (a) **les vues déclarées par le run** ( `errand.view` ) qui se voient : un répertoire servi par `errand.Static`
  ( `foam.sviz` ), une page HTML, une image, un PDF, une vidéo ;
- (b) en plus, les fichiers riches du dossier du run **non déclarés** ( un `plot.png` écrit à la main ) ;
- (c) seulement les `errand.Static`.

(a) laisse le producteur décider sans configuration ( sdot déclare déjà ses stores et ses pages ), et ne promeut pas un
fichier écrit pour une autre raison. (b) montrerait n'importe quelle image intermédiaire.

➡️ **Recommandé :** (a). Les fichiers non déclarés restent dans la liste, à un clic.

**Réponse :**

---

## Q2 : La disposition quand il y a quelque chose à regarder

- **(a) Partage vertical** : en haut, en grand ( ~70 % ), la sortie à regarder ; en bas, une **bande console**
  ( ~30 % ) qui suit la fin de la sortie. La séparation se tire à la souris, et la page s'en souvient ( pour toutes les
  pages de runs, pas run par run ).
- (b) Côte à côte : la sortie à gauche, la console à droite ( les viewers aiment la largeur, la console les lignes
  longues : les deux y perdent ).
- (c) Pas de partage : la sortie prend tout le volet, la console à un clic ( ce qu'on perd : voir le run avancer en
  même temps que sa figure ).

Sans rien à regarder : la console prend tout le volet, comme aujourd'hui.

➡️ **Recommandé :** (a).

**Réponse :**

---

## Q3 : Plusieurs sorties à regarder

Un run déclare `foam.sviz` puis `foam.html`, ou trois figures :

- **(a) des onglets** au-dessus de la grande zone, un par sortie, celle montrée d'office choisie par une règle ( Q7, au
  tour suivant ) ; un clic sur un onglet ou dans la liste change ce qui est montré ;
- (b) une grille de toutes les sorties ( chaque viewer est une page entière : à quatre, illisible et lourd ) ;
- (c) seulement la plus récente, les autres dans la liste.

➡️ **Recommandé :** (a), le choix fait à la main gardé pour ce run tant que la page reste ouverte.

**Réponse :**

---

## Q4 : Où vit ce tableau de bord

- **(a) Partout où un run est montré** : la page d'un run ( `/job`, le lien du terminal ) et le volet de droite de la page
  principale quand on y choisit un run ;
- (b) seulement la page d'un run ( la page principale reste une liste avec un aperçu simple ).

➡️ **Recommandé :** (a) : c'est le même volet et le même code ; la page principale gagne la même chose sans détour.

**Réponse :**

---

## Q5 : Ce que le producteur peut dire

Faut-il, **dès maintenant**, un moyen pour un run de dire « montre celle-ci d'abord » ou « pas de partage » ?
Par exemple `errand.view( "foam.sviz", main = True )`, ou un ordre ( `rank = 0` ).

- **(a) Rien pour l'instant** : les règles par défaut ( Q1, Q3, Q7 ) ; on ajoute un mot quand un vrai cas le demande ;
- (b) `main = True` tout de suite.

➡️ **Recommandé :** (a).

**Réponse :**

---

## Q6 : Et la TUI ?

Un terminal ne montre ni iframe ni image. Dans `errand tui`, le détail d'un run garde la console ; une sortie à regarder
y a sa ligne ( `foam.sviz  331 frames` ), et une touche l'ouvre dans le navigateur, sur la page du run.

- **(a) TUI inchangée**, plus une touche ( `w` ) qui ouvre la page du run dans le navigateur, avec un code à usage unique ;
- (b) TUI inchangée, sans touche.

➡️ **Recommandé :** (a).

**Réponse :**

---
