/** Textes UI Sonasid — indicateurs port / navires / arrivages. */

export const SONASID_TAGLINE = 'Assistant décisionnel — port & arrivages'

export function buildSonasidWelcomeText(actorName) {
  const name = String(actorName || '').trim()
  const first = name.split(/\s+/)[0] || ''
  const greet = first ? `Bonjour ${first}.` : 'Bonjour.'
  const y = String(new Date().getFullYear())
  return (
    `${greet} Posez votre question sur les arrivages, tonnages, fournisseurs, qualités ou navires.\n\n` +
    `Exemples : résumé KPI ${y} · top fournisseurs ${y} · arrivages par mois ${y}.`
  )
}

export const SONASID_WELCOME_HINT =
  'Arrivages · tonnage · fournisseurs · qualité · navires'

export const SONASID_CHAT_PLACEHOLDER =
  'Votre question… (ex. tonnage importé en 2025)'
export const SONASID_CHAT_SUBTITLE =
  'Port & arrivages — analyses et KPI'
export const SONASID_LOGIN_SUBTITLE = 'Connectez-vous pour accéder à l’assistant Sonasid.'
