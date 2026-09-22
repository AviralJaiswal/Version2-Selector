import React, { useEffect, useMemo, useRef, useState } from 'react'

const COLORS = ['#e31b23', '#ff7178', '#ffb703', '#7257ed', '#38c78a', '#2f9bff', '#ff5fa2', '#ffd166']
const SHAPES = ['rect', 'circle', 'strip']

function buildParticles(seed, count) {
  return Array.from({ length: count }, (_, index) => {
    const n = index + seed * 17
    const shape = SHAPES[n % SHAPES.length]
    const base = 7 + ((n * 13) % 7)
    return {
      id: `${seed}-${index}`,
      left: `${(n * 37) % 100}%`,
      drift: `${-180 + ((n * 53) % 360)}px`,
      delay: `${(index % 16) * 55}ms`,
      duration: `${2400 + ((n * 79) % 1600)}ms`,
      width: shape === 'strip' ? Math.max(3, base - 4) : base,
      height: shape === 'strip' ? base + 6 : base,
      spin: `${420 + ((n * 91) % 760)}deg`,
      color: COLORS[n % COLORS.length],
      shape
    }
  })
}

/**
 * Full-screen confetti celebration.
 *
 * Fires whenever `show` flips to truthy, or whenever `trigger` changes to a new
 * non-zero value (use the counter form when the same event can happen more than
 * once in a session, e.g. repeated plan upgrades/downgrades).
 */
export function CelebrationBurst({ show = false, trigger = 0, particleCount = 90, duration = 4600 }) {
  const [burst, setBurst] = useState(null)
  const seedRef = useRef(0)

  useEffect(() => {
    if (!show && !trigger) return
    seedRef.current += 1
    const seed = seedRef.current
    setBurst({ seed, particles: buildParticles(seed, particleCount) })
    const timer = window.setTimeout(() => setBurst(null), duration)
    return () => window.clearTimeout(timer)
  }, [show, trigger, particleCount, duration])

  if (!burst) return null

  return (
    <div className="celebration-burst celebration-burst--fullscreen" key={burst.seed} aria-hidden="true">
      {burst.particles.map((particle) => (
        <i
          key={particle.id}
          className={`confetti-piece confetti-${particle.shape}`}
          style={{
            left: particle.left,
            width: `${particle.width}px`,
            height: `${particle.height}px`,
            background: particle.color,
            animationDelay: particle.delay,
            animationDuration: particle.duration,
            '--drift': particle.drift,
            '--spin': particle.spin
          }}
        />
      ))}
    </div>
  )
}
