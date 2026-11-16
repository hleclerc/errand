# Refonte de la doc errand : décisions

- **Public** : qui écrit du code de calcul (recherche, HPC, ML) et le fait tourner sur portable, serveurs du labo, cluster national, parfois Windows ; pas DevOps, pas un nouveau lanceur de tests.
- **Page d'accueil** : (1) déclarer un endroit et y lancer une commande ; (2) tout ce qu'il démarre est suivi et arrêté ; (3) ce qu'on a en plus. Cartes refaites, pas de carte tests.
- **Tests** : une section du guide après les ressources, absente de l'accueil et du quickstart sauf une ligne. Les runners seront rediscutés à part.
- **Entrées d'errand** : une page *Writing entries* courte, encadré « being reworked », tutoriel 4 retiré ou fondu dedans.
- **Parties du guide** : Start · Places · Running · (ressources) · Test suites and entries · Project · Reference.
- **Tutoriels** : garder 1 et 3, 2 devient une page de la partie tests, 4 fondu dans *Writing entries*, ajouter un tutoriel cluster + VM Windows + status.
- **Ton** : sobre et percutant, titres descriptifs. Le fil rouge : faire comprendre l'intérêt face à « je fais ça à la main, je ne veux pas perdre le contrôle ».
- **README** : court, ≈ 60 lignes, lien vers le site.
- **Accroche** : *Run it there as if it were here.* + « Same command, same output in your terminal, Ctrl-C included, whether "there" is a container, a server over ssh, a Slurm allocation or a Windows VM. errand sets the place up, syncs the files both ways, and cleans up after itself. » ; *Stop babysitting your runs* en sous-titre de section. Pas de « own » en accroche.
- **Contrôle** : avant / après sur l'accueil ; « You stay in control » (court sur l'accueil, complet dans *What errand is*) ; « What you stop doing » dans *What errand is*.
- **Scénarios** : a (cluster + conteneur, résultats rapatriés), c (`errand status`), b (laptop fermé, `attach`). Pas de « 1 s sans la file » (filouterie) ; le keep-alive peut être mis en avant comme démarrage plus rapide, sans chiffre.
- **Partie ressources** : *Nothing left behind*, page d'entrée *What is running*.
- **Runners et tags** : réduire la supposition du runner à une phrase ; tags d'env dans une page avancée en fin de Places, hors quickstart. Fond des runners rediscuté plus tard, à part.
- **Sommaire** : round 3 accepté tel quel (2026-11-15).
