/** Textes UI Sonasid — indicateurs port / navires / arrivages. */

export const SONASID_TAGLINE = 'Assistant décisionnel — port & arrivages'

export function buildSonasidWelcomeText(actorName) {
  const name = String(actorName || '').trim()
  const greet = name ? `Bonjour ${name}.` : 'Bonjour.'
  const y = String(new Date().getFullYear())
  return (
    `${greet} Posez votre question en langage naturel.\n\n` +
    `Exemples (formules Sonasid) :\n` +
    `- nombre des arrivages\n` +
    `- nombre d'arrivages fournisseur id 1\n` +
    `- valeur des marchandises importées en ${y}\n` +
    `- tonnage importé en ${y}\n` +
    `- arrivages par qualité en ${y}\n` +
    `- tonnage importé par qualité en ${y}\n` +
    `- tonnage importé par qualité par mois en ${y}\n` +
    `- tonnage importé fournisseur id 40 en ${y}\n` +
    `- liste des qualités\n` +
    `- tonnage commandé par qualité en ${y}\n` +
    `- tonnage par qualité fournisseur id 40 en ${y}\n` +
    `- tonnage transféré par qualité en ${y}\n` +
    `- tonnage transféré par qualité détail en ${y}\n` +
    `- tonnage transféré par qualité navire id 1\n` +
    `- nombre de navires actifs\n` +
    `- nombre de navires actifs par mois en ${y}\n` +
    `- nombre de navires actifs par mois en 2025 (si accès RBAC)\n` +
    `- nombre de navires en déchargement\n` +
    `- liste des navires en déchargement\n` +
    `- tonnage déchargé en déchargement · tonnage restant à décharger\n` +
    `- taux de déchargement · tonnage déchargé par mois en ${y}\n\n` +
    `Vous pouvez aussi dire **bonjour** ou poser des questions générales (logistique, maritime…).\n` +
    `Les courbes s'affichent pour « par mois » ou après un total (ex. arrivages).\n` +
    `Optionnel : ajoutez une année (${y}) pour filtrer sur une période.`
  )
}

export const SONASID_WELCOME_HINT =
  'Ex. arrivages · déchargement · fournisseur · tonnage · qualité · transfert · navires'

export const SONASID_CHAT_PLACEHOLDER =
  'Écris ton message… (ex: tonnage importé fournisseur id 1)'
export const SONASID_CHAT_SUBTITLE =
  'Arrivages, fournisseurs, tonnage, qualité, navires — ou dis bonjour.'
export const SONASID_LOGIN_SUBTITLE = 'Connecte-toi pour accéder à l’assistant Sonasid.'
