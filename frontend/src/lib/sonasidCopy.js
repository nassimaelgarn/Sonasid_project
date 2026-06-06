/** Textes UI Sonasid — indicateurs port / navires / arrivages. */

export const SONASID_TAGLINE = 'Assistant décisionnel — port & arrivages'

export function buildSonasidWelcomeText(actorName) {
  const name = String(actorName || '').trim()
  const first = name.split(/\s+/)[0] || ''
  const greet = first
    ? `Bonjour ${first}, bienvenue dans l'assistant IA Sonasid.`
    : "Bonjour, bienvenue dans l'assistant IA Sonasid."
  const y = String(new Date().getFullYear())
  return `${greet}\n\nJe serai ravi de t'aider. Ex. : résumé KPI ${y}, top fournisseurs, arrivages par mois.`
}

/** Banque de questions testables — tirage aléatoire à l'accueil. */
export const SONASID_EXAMPLE_QUESTIONS = [
  'tonnage importé en 2025',
  'nombre des arrivages en 2025',
  'arrivages par mois en 2025',
  'top fournisseurs par arrivages en 2025',
  'tonnage importé par qualité en 2025',
  'tonnage transféré par qualité en 2025',
  'liste des navires en déchargement',
  'nombre de navires actifs',
  'tonnage déchargé en déchargement',
  'tonnage restant à décharger',
  'un petit récap sur 2025',
  'situation au port cette année',
  'structure de la table NAVIRE',
  'champs table QUALITE',
  'noms des tables et leurs relations',
  'cite le nombre des tables',
  'liste des qualités',
  'tonnage commandé par qualité en 2025',
  'tonnage transféré par qualité navire id 79 en 2025',
  'les arrivages ont augmenté ou pas ?',
  "qu'est-ce qui est arrivé en janvier 2025 ?",
  'valeur des marchandises importées en 2025',
  'nombre de navires actifs par mois en 2025',
  'tonnage déchargé par mois en 2025',
  'structure table FLOTTE',
  'structure de la table ARRIVAGE',
]

export function pickRandomSonasidExamples(count = 4) {
  const n = Math.max(1, Math.min(count, SONASID_EXAMPLE_QUESTIONS.length))
  const pool = [...SONASID_EXAMPLE_QUESTIONS]
  for (let i = pool.length - 1; i > 0; i -= 1) {
    const j = Math.floor(Math.random() * (i + 1))
    ;[pool[i], pool[j]] = [pool[j], pool[i]]
  }
  return pool.slice(0, n)
}

export const SONASID_WELCOME_HINT =
  'Arrivages · tonnage · fournisseurs · qualité · navires · schéma BDD'

export const SONASID_CHAT_PLACEHOLDER =
  'Votre question… (ex. tonnage importé en 2025)'
export const SONASID_CHAT_SUBTITLE =
  'Port & arrivages — analyses et KPI'
export const SONASID_LOGIN_SUBTITLE = 'Connectez-vous pour accéder à l’assistant Sonasid.'
