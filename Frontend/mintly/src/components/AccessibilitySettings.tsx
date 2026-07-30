import { useAccessibility, type TextSize } from '../accessibility'
import styles from './AccessibilitySettings.module.css'

// An accessible on/off switch — role="switch" so assistive tech announces its
// state; the visible label is also the button's accessible name.
function SettingToggle({ label, description, checked, onChange }: {
  label: string
  description: string
  checked: boolean
  onChange: (next: boolean) => void
}) {
  return (
    <div className={styles.settingRow}>
      <div className={styles.settingText}>
        <span className={styles.settingLabel}>{label}</span>
        <span className={styles.settingDesc}>{description}</span>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        aria-label={label}
        className={`${styles.switch} ${checked ? styles.switchOn : ''}`}
        onClick={() => onChange(!checked)}
      >
        <span className={styles.switchKnob} />
      </button>
    </div>
  )
}

const TEXT_SIZES: { value: TextSize; label: string }[] = [
  { value: 'default', label: 'Default' },
  { value: 'large', label: 'Large' },
  { value: 'larger', label: 'Larger' },
]

// The device-local display preferences from accessibility.ts (reduce motion /
// high contrast / underline links / text size), rendered as a hairline row
// stack. Shared by the Profile page and the public Accessibility page so the
// controls are reachable without an account. Reads/writes the shared store
// directly: every change applies instantly and persists to localStorage.
export default function AccessibilitySettings() {
  const { settings, update } = useAccessibility()
  return (
    <div className={styles.settingStack}>
      <SettingToggle
        label="Reduce motion"
        description="Turn off animations, the typing placeholder, and the auto-hiding nav bar."
        checked={settings.reduceMotion}
        onChange={v => update({ reduceMotion: v })}
      />
      <SettingToggle
        label="High contrast"
        description="Brighter text and stronger borders for easier reading."
        checked={settings.highContrast}
        onChange={v => update({ highContrast: v })}
      />
      <SettingToggle
        label="Underline links"
        description="Always underline links, not just on hover."
        checked={settings.underlineLinks}
        onChange={v => update({ underlineLinks: v })}
      />

      <div className={styles.settingRow}>
        <div className={styles.settingText}>
          <span className={styles.settingLabel}>Text size</span>
          <span className={styles.settingDesc}>Scale everything up for easier reading.</span>
        </div>
        <div className={styles.segmented} role="radiogroup" aria-label="Text size">
          {TEXT_SIZES.map(s => (
            <button
              key={s.value}
              type="button"
              role="radio"
              aria-checked={settings.textSize === s.value}
              className={`${styles.segment} ${settings.textSize === s.value ? styles.segmentOn : ''}`}
              onClick={() => update({ textSize: s.value })}
            >
              {s.label}
            </button>
          ))}
        </div>
      </div>
    </div>
  )
}
