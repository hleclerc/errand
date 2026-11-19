# Le tableau de bord d'un run : décisions

## Tour 1 ( 2026-11-19 )

- **À regarder**: les vues déclarées par le run ( `errand.view` ) qui se voient : un `errand.Static`, une page HTML, une image, un PDF, une vidéo. Les fichiers riches non déclarés restent dans la liste, à un clic.
- **Disposition**: partage vertical, en haut la sortie à regarder ( ~70 % ), en bas une bande console ( ~30 % ) qui suit la fin ; séparation tirée à la souris, retenue pour toutes les pages de runs. Rien à regarder : la console prend tout, comme aujourd'hui.
- **Plusieurs**: des onglets au-dessus de la grande zone ; celle montrée d'office par une règle ( tour 2 ) ; le choix à la main gardé pour ce run tant que la page reste ouverte.
- **Où**: partout où un run est montré, la page d'un run ( `/job` ) et le volet de droite de la page principale.
- **Producteur**: rien pour l'instant ( pas de `main = True` ) ; on ajoute un mot quand un vrai cas le demande.
- **TUI**: inchangée, plus une touche `w` qui ouvre la page du run dans le navigateur ( code à usage unique ).

## Tour 2 ( 2026-11-19 )

- **D'office**: une vue `errand.Static` ( un viewer vivant ) passe avant une vue fichier ; entre vues de même sorte, la plus récente ( `foam.sviz` reste quand `foam.html` arrive à la fin ).
- **Bande console**: suit la fin ( sauf si l'on remonte ), repliable sur une ligne ( sa dernière ) ; état retenu pour toutes les pages de runs.
- **Clic dans la liste**: une sortie à regarder devient l'onglet montré ; un texte ou un fichier prend aussi la grande zone, la bande console reste ; un clic sur « console » la met en grand, sans partage, jusqu'au prochain choix d'une sortie à regarder.
- **Pas prête**: la console reste en grand ; le partage apparaît dès que la vue est prête ( un store : sa première frame ici et son serveur qui répond ).
