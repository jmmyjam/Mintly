import { useCallback, useState } from 'react'
import styles from './CardImage.module.css'

interface CardImageProps {
  src?: string | null
  alt: string
  // 'tile' for the search/portfolio grids, 'detail' for the large card page image
  size?: 'tile' | 'detail'
  // the detail hero loads eagerly; grid tiles stay lazy
  eager?: boolean
}

// One card-artwork element for the whole site. Reserves the 5:7 card ratio so
// the layout never shifts, and keeps a muted placeholder frame behind the image
// so a slow, missing, or failed load shows a card-shaped box (or an "image
// unavailable" glyph) instead of a blank gap or a broken-image icon.
export default function CardImage({ src, alt, size = 'tile', eager = false }: CardImageProps) {
  const [failed, setFailed] = useState(false)

  // A cached image can finish (or fail) before React attaches onError, so also
  // check `complete` when the node mounts — otherwise a failed cached image
  // would never swap to the placeholder.
  const imgRef = useCallback((node: HTMLImageElement | null) => {
    if (node && node.complete && node.naturalWidth === 0) setFailed(true)
  }, [])

  const showImg = !!src && !failed

  return (
    <span
      className={`${styles.frame} ${size === 'detail' ? styles.detail : styles.tile}`}
      {...(showImg ? {} : { role: 'img', 'aria-label': alt })}
    >
      {showImg && (
        <img
          ref={imgRef}
          src={src}
          alt={alt}
          className={styles.img}
          loading={eager ? 'eager' : 'lazy'}
          decoding="async"
          onError={() => setFailed(true)}
        />
      )}
      {!showImg && (
        <svg className={styles.icon} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
          <rect x="3" y="4" width="18" height="16" rx="2" />
          <circle cx="8.5" cy="10" r="1.5" />
          <path d="M21 15l-5-5-9 9" />
        </svg>
      )}
    </span>
  )
}
