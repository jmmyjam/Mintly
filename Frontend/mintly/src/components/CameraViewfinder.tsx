import { useEffect, useRef, useState } from 'react'
import styles from './CameraViewfinder.module.css'

interface Props {
  // Called with a canvas cropped to the card-outline frame (live camera) or the
  // whole photo (file fallback). The parent runs OCR on it.
  onCapture: (card: HTMLCanvasElement) => void
  // Disable capture while the parent is busy (e.g. reading a previous scan).
  busy?: boolean
}

function cameraErrorMessage(err: unknown): string {
  const name = err instanceof DOMException ? err.name : ''
  if (name === 'NotAllowedError' || name === 'SecurityError')
    return 'Camera access was blocked. Allow camera access in your browser, or choose a photo instead.'
  if (name === 'NotFoundError' || name === 'OverconstrainedError')
    return 'No camera was found. You can choose a photo instead.'
  return "Couldn't start the camera. You can choose a photo instead."
}

// Downscale a loaded image to a canvas (long edge ~1200px) for the file fallback.
function imageToCanvas(img: HTMLImageElement): HTMLCanvasElement {
  const scale = Math.min(1, 1200 / Math.max(img.width, img.height))
  const c = document.createElement('canvas')
  c.width = Math.max(1, Math.round(img.width * scale))
  c.height = Math.max(1, Math.round(img.height * scale))
  c.getContext('2d')!.drawImage(img, 0, 0, c.width, c.height)
  return c
}

export default function CameraViewfinder({ onCapture, busy }: Props) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const frameRef = useRef<HTMLDivElement>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [ready, setReady] = useState(false)

  useEffect(() => {
    let cancelled = false

    async function start() {
      if (!navigator.mediaDevices?.getUserMedia) {
        setError('This browser does not support camera capture. You can choose a photo instead.')
        return
      }
      try {
        const stream = await navigator.mediaDevices.getUserMedia({
          // Ask for a high-res stream so the card fills more pixels — a sharper
          // capture gives the embedding match more to work with.
          video: {
            facingMode: { ideal: 'environment' },
            width: { ideal: 1920 },
            height: { ideal: 1080 },
          },
          audio: false,
        })
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop())
          return
        }
        streamRef.current = stream
        const v = videoRef.current
        if (v) {
          v.srcObject = stream
          // iOS needs an explicit play() after srcObject; ignore autoplay rejection
          await v.play().catch(() => {})
          setReady(true)
        }
      } catch (err) {
        if (!cancelled) setError(cameraErrorMessage(err))
      }
    }

    start()
    return () => {
      cancelled = true
      streamRef.current?.getTracks().forEach((t) => t.stop())
      streamRef.current = null
    }
  }, [])

  // Crop the live frame to the on-screen card outline. We read the frame's real
  // bounding rect and map it back into the video's native pixels, accounting for
  // object-fit: cover — so what we crop matches what the user aligned.
  function capture() {
    const v = videoRef.current
    const f = frameRef.current
    if (!v || !f || !v.videoWidth || !v.videoHeight) return

    const vb = v.getBoundingClientRect()
    const fb = f.getBoundingClientRect()
    const vw = v.videoWidth
    const vh = v.videoHeight

    const scale = Math.max(vb.width / vw, vb.height / vh)
    const offsetX = (vw * scale - vb.width) / 2
    const offsetY = (vh * scale - vb.height) / 2

    let nx = (fb.left - vb.left + offsetX) / scale
    let ny = (fb.top - vb.top + offsetY) / scale
    let nw = fb.width / scale
    let nh = fb.height / scale

    nx = Math.max(0, Math.min(nx, vw))
    ny = Math.max(0, Math.min(ny, vh))
    nw = Math.min(nw, vw - nx)
    nh = Math.min(nh, vh - ny)

    const c = document.createElement('canvas')
    c.width = Math.max(1, Math.round(nw))
    c.height = Math.max(1, Math.round(nh))
    c.getContext('2d')!.drawImage(v, nx, ny, nw, nh, 0, 0, c.width, c.height)
    onCapture(c)
  }

  function onFile(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0]
    e.target.value = '' // allow re-selecting the same file
    if (!file) return
    const url = URL.createObjectURL(file)
    const img = new Image()
    img.onload = () => {
      onCapture(imageToCanvas(img))
      URL.revokeObjectURL(url)
    }
    img.onerror = () => {
      URL.revokeObjectURL(url)
      setError("That image couldn't be read. Try another photo.")
    }
    img.src = url
  }

  return (
    <div className={styles.wrap}>
      {error ? (
        <div className={styles.errorBox}>
          <p>{error}</p>
        </div>
      ) : (
        <div className={styles.viewport}>
          <video ref={videoRef} className={styles.video} playsInline muted autoPlay />
          <div className={styles.overlay} aria-hidden="true">
            <div ref={frameRef} className={styles.frame} />
          </div>
          <p className={styles.hint}>Line the card up inside the frame</p>
        </div>
      )}

      <div className={styles.controls}>
        {!error && (
          <button
            type="button"
            className="btn-primary btn-lg"
            onClick={capture}
            disabled={busy || !ready}
          >
            {busy ? 'Reading…' : 'Scan card'}
          </button>
        )}
        <label className={styles.fileLabel}>
          {error ? 'Choose a photo' : 'or choose a photo'}
          <input type="file" accept="image/*" capture="environment" onChange={onFile} disabled={busy} />
        </label>
      </div>
    </div>
  )
}
