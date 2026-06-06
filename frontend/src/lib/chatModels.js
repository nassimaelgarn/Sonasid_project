/** Modèles chat — défauts UI (liste complète via GET /chat/models) */

export const DEFAULT_CHAT_MODEL_OPTIONS = [
  { id: 'kimi', label: 'Kimi K2.6', hint: 'Azure · recommandé', dot: 'bg-rose-500' },
  { id: 'trinity', label: 'Trinity', hint: 'OpenRouter · cloud', dot: 'bg-blue-500' },
  { id: 'flash', label: 'Flash', hint: 'OpenRouter · rapide', dot: 'bg-fuchsia-500' },
  { id: 'ollama', label: 'Llama3.1', hint: 'Local · Ollama', dot: 'bg-emerald-500' },
]

export const DEFAULT_CHAT_MODEL_ID = 'kimi'
