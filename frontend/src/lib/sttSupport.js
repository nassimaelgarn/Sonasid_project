/** Browser speech-to-text capability probe (Web Speech + optional server fallback). */

function isSafariUa() {
  if (typeof navigator === 'undefined') return false
  const ua = navigator.userAgent || ''
  return /safari/i.test(ua) && !/chrome|chromium|crios|android/i.test(ua)
}

function isFirefoxUa() {
  if (typeof navigator === 'undefined') return false
  return /firefox/i.test(uaSafe())
}

function uaSafe() {
  return typeof navigator !== 'undefined' ? navigator.userAgent || '' : ''
}

export function detectSttCapabilities() {
  if (typeof window === 'undefined') {
    return { available: false, reason: 'ssr', message: '', preferWebSpeech: false, isSafari: false }
  }

  const secure = Boolean(window.isSecureContext)
  const hasWebSpeech = Boolean(window.SpeechRecognition || window.webkitSpeechRecognition)
  const hasMedia = Boolean(navigator.mediaDevices?.getUserMedia)
  const isSafari = isSafariUa()
  const isFirefox = isFirefoxUa()

  if (!secure) {
    return {
      available: false,
      reason: 'insecure',
      preferWebSpeech: false,
      isSafari,
      message:
        'Le micro nécessite HTTPS (connexion sécurisée). L’URL actuelle est en HTTP — activez SSL sur le serveur ou testez en local (localhost).',
    }
  }

  if (isFirefox && !hasMedia) {
    return {
      available: false,
      reason: 'firefox',
      preferWebSpeech: false,
      isSafari: false,
      message: 'Firefox ne prend pas en charge la dictée vocale. Utilisez Chrome, Edge ou Safari.',
    }
  }

  if (!hasWebSpeech && !hasMedia) {
    return {
      available: false,
      reason: 'no-api',
      preferWebSpeech: false,
      isSafari,
      message: 'Dictée vocale non supportée sur ce navigateur.',
    }
  }

  // Firefox: no Web Speech API — server transcription via MediaRecorder.
  const preferWebSpeech = hasWebSpeech && !isFirefox

  return {
    available: true,
    reason: preferWebSpeech ? 'webspeech' : 'recorder',
    preferWebSpeech,
    isSafari,
    message: '',
  }
}

/** Prime mic permission (helps Safari / Chrome before Web Speech). */
export async function primeMicrophoneAccess() {
  if (!navigator.mediaDevices?.getUserMedia) return { ok: true }
  try {
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true })
    stream.getTracks().forEach((t) => {
      try {
        t.stop()
      } catch {
        /* noop */
      }
    })
    return { ok: true }
  } catch (e) {
    const name = String(e?.name || '')
    if (name === 'NotAllowedError' || name === 'PermissionDeniedError') {
      return { ok: false, message: 'Autorisation micro refusée. Autorisez le micro dans les réglages du navigateur.' }
    }
    if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
      return { ok: false, message: 'Aucun micro détecté sur cet appareil.' }
    }
    return { ok: false, message: name ? `Micro indisponible (${name}).` : 'Micro indisponible.' }
  }
}

export function pickRecorderMimeType() {
  if (typeof MediaRecorder === 'undefined') return ''
  const candidates = ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus']
  for (const t of candidates) {
    try {
      if (MediaRecorder.isTypeSupported(t)) return t
    } catch {
      /* noop */
    }
  }
  return ''
}

export function recorderFormatFromMime(mime) {
  const m = String(mime || '').toLowerCase()
  if (m.includes('webm')) return 'webm'
  if (m.includes('ogg')) return 'ogg'
  if (m.includes('mp4') || m.includes('m4a')) return 'm4a'
  if (m.includes('wav')) return 'wav'
  return 'webm'
}
