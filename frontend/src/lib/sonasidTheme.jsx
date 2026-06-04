import plant2 from '../assets/steel-plant-2.jpg'
import brandLogo from '../assets/sonasid-logo.png'

export const SONASID_ORANGE = '#E86132'
export const SONASID_GREY = '#333336'

export const sonasidButtonClass =
  'bg-gradient-to-r from-amber-500 via-orange-500 to-rose-500 shadow-[0_12px_28px_-18px_rgba(249,115,22,0.85)] hover:from-amber-400 hover:via-orange-400 hover:to-rose-400 focus:ring-orange-500/25'

/** Logo Sonasid — encadré blanc simple (comme au début). */
export function SonasidBrandLogo({ compact = false }) {
  return (
    <div
      className={
        compact
          ? 'flex h-10 w-40 items-center justify-center rounded-xl border border-slate-200/80 bg-white/90 px-3 shadow-sm dark:border-slate-700/55 dark:bg-slate-900/40'
          : 'flex h-12 w-44 items-center justify-center rounded-xl border border-slate-200/80 bg-white/95 px-3 shadow-sm dark:border-slate-700/55 dark:bg-slate-900/40'
      }
    >
      <img
        src={brandLogo}
        alt="Sonasid"
        className={compact ? 'h-8 w-auto object-contain' : 'h-9 w-auto object-contain'}
      />
    </div>
  )
}

/** Fond photo usine */
export function SteelPlantBackground({ variant = 'default' }) {
  const opacityClass =
    variant === 'login' ? 'opacity-[0.56] dark:opacity-[0.36]' : 'opacity-[0.52] dark:opacity-[0.32]'
  return (
    <div className="pointer-events-none absolute inset-0">
      <div
        className={`absolute inset-0 ${opacityClass}`}
        style={{
          backgroundImage: `url(${plant2})`,
          backgroundSize: 'cover',
          backgroundPosition: 'center',
          filter: 'grayscale(0.05) saturate(1.12) contrast(1.10)',
        }}
      />
      {variant === 'login' ? <div className="absolute inset-0 backdrop-blur-[0.25px]" /> : null}
      <div className="absolute inset-0 bg-gradient-to-b from-white/6 via-white/10 to-white/14 dark:from-slate-950/28 dark:via-slate-950/34 dark:to-slate-950/42" />
      <div className="absolute inset-0 bg-[radial-gradient(ellipse_at_top,rgba(244,63,94,0.10),transparent_55%)] dark:bg-[radial-gradient(ellipse_at_top,rgba(244,63,94,0.10),transparent_55%)]" />
    </div>
  )
}
