/** Textes UI Sonasid — indicateurs port / navires / arrivages. */

export const SONASID_TAGLINE = 'Assistant décisionnel — port & arrivages'

export function buildSonasidWelcomeText(actorName) {
  const name = String(actorName || '').trim()
  const first = name.split(/\s+/)[0] || ''
  const greet = first ? `Bonjour ${first}.` : 'Bonjour.'
  const y = String(new Date().getFullYear())
  return (
    `${greet}\n\n` +
    `Je suis l’assistant **port & arrivages** Sonasid. Posez vos questions en langage naturel — ` +
    `arrivages, tonnages, fournisseurs, qualités, navires, déchargements — sur la période de votre choix (ex. ${y}).\n\n` +
    `Je génère et exécute les analyses à partir de la base ; vous recevez une synthèse claire, sans requête SQL affichée.\n\n` +
    `Pour démarrer : « résumé des KPI ${y} », « top fournisseurs en ${y} », « analyse arrivages ${y} tous les axes ».`
  )
}

export const SONASID_WELCOME_HINT =
  'Arrivages · tonnage · fournisseurs · qualité · navires · déchargement'

export const SONASID_CHAT_PLACEHOLDER =
  'Votre question (ex. tonnage importé par fournisseur en 2025…)'
export const SONASID_CHAT_SUBTITLE =
  'Analyses port & arrivages — questions ouvertes, réponses chiffrées'
export const SONASID_LOGIN_SUBTITLE = 'Connectez-vous pour accéder à l’assistant Sonasid.'
