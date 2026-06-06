/** Modèles chat — défauts UI (liste complète via GET /chat/models) */

export const DEFAULT_CHAT_MODEL_OPTIONS = [
  { id: 'grok', label: 'Grok 4.3', hint: 'Azure · entreprise', dot: 'bg-rose-500' },
  { id: 'kimi', label: 'Kimi K2.6', hint: 'Azure · recommandé', dot: 'bg-sky-500' },
  { id: 'deepseek', label: 'DeepSeek V4 Pro', hint: 'Azure · analyse', dot: 'bg-violet-500' },
  { id: 'trinity', label: 'Trinity', hint: 'OpenRouter · cloud', dot: 'bg-blue-500' },
  { id: 'flash', label: 'Flash', hint: 'OpenRouter · rapide', dot: 'bg-fuchsia-500' },
  { id: 'ollama', label: 'Llama3.1', hint: 'Local · Ollama', dot: 'bg-emerald-500' },
]

export const DEFAULT_CHAT_MODEL_ID = 'kimi'

export async function fetchChatModelOptions(baseUrl) {
  try {
    const res = await fetch(`${baseUrl}/chat/models`, { credentials: 'include' })
    if (!res.ok) return DEFAULT_CHAT_MODEL_OPTIONS
    const data = await res.json()
    const models = Array.isArray(data?.models) ? data.models : []
    if (!models.length) return DEFAULT_CHAT_MODEL_OPTIONS
    return models.map((m) => ({
      id: String(m.id || ''),
      label: String(m.label || m.id || ''),
      hint: String(m.hint || ''),
      dot: String(m.dot || 'bg-blue-500'),
    }))
  } catch {
    return DEFAULT_CHAT_MODEL_OPTIONS
  }
}

export async function fetchDefaultChatModelId(baseUrl) {
  try {
    const res = await fetch(`${baseUrl}/chat/models`, { credentials: 'include' })
    if (!res.ok) return DEFAULT_CHAT_MODEL_ID
    const data = await res.json()
    const d = String(data?.default || '').trim()
    return d || DEFAULT_CHAT_MODEL_ID
  } catch {
    return DEFAULT_CHAT_MODEL_ID
  }
}

export function normalizeStoredModelId(id) {
  const v = String(id || '').trim()
  if (v === 'mistral') return 'flash'
  return v || DEFAULT_CHAT_MODEL_ID
}
