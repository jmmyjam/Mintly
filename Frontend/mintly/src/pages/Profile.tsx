import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import {
  getMe, updateProfile, changePassword, getToken, clearToken,
  CONNECTION_ERROR, errorMessage, SessionExpiredError, type UserProfile,
} from '../api'
import { useAccessibility, type TextSize } from '../accessibility'
import { useSessionRedirect } from '../hooks'
import DeleteAccount from '../components/DeleteAccount'
import PageMessage from '../components/PageMessage'
import StatusMessage from '../components/StatusMessage'
import styles from './Profile.module.css'

// Mirrors the backend rules in auth.py so the user gets instant feedback
function passwordError(password: string): string | null {
  if (password.length < 8) return 'Password must be at least 8 characters'
  if (!/[A-Za-z]/.test(password)) return 'Password must contain at least one letter'
  if (!/\d/.test(password)) return 'Password must contain at least one number'
  return null
}

// created_at arrives as naive UTC (no zone suffix) — anchor it with Z so it
// reads as UTC, not local time (same fix as Portfolio's parseUTCDate)
function memberSince(iso: string): string {
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  return d.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
}

type Status = { ok: boolean; text: string } | null

// An accessible on/off switch — role="switch" so it announces its state
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

export default function Profile() {
  const navigate = useNavigate()
  const redirectToLogin = useSessionRedirect()
  const { settings, update } = useAccessibility()

  const [profile, setProfile] = useState<UserProfile | null>(null)
  const [loading, setLoading] = useState(() => !!getToken())
  const [loadError, setLoadError] = useState('')

  // Account-details form
  const [username, setUsername] = useState('')
  const [email, setEmail] = useState('')
  const [savingInfo, setSavingInfo] = useState(false)
  const [infoStatus, setInfoStatus] = useState<Status>(null)

  // Change-password form
  const [currentPw, setCurrentPw] = useState('')
  const [newPw, setNewPw] = useState('')
  const [confirmPw, setConfirmPw] = useState('')
  const [savingPw, setSavingPw] = useState(false)
  const [pwStatus, setPwStatus] = useState<Status>(null)

  useEffect(() => {
    if (!getToken()) return
    getMe()
      .then(p => {
        setProfile(p)
        setUsername(p.username)
        setEmail(p.email)
        setLoading(false)
      })
      .catch(err => {
        if (err instanceof SessionExpiredError) {
          redirectToLogin()
          return
        }
        setLoadError(
          err instanceof TypeError
            ? CONNECTION_ERROR
            : "We couldn't load your profile right now. Please try again in a moment.",
        )
        setLoading(false)
      })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const infoChanged =
    !!profile && (username.trim() !== profile.username || email.trim() !== profile.email)

  async function saveInfo(e: React.FormEvent) {
    e.preventDefault()
    if (!profile || savingInfo || !infoChanged) return
    if (!username.trim()) { flashInfo(false, "Username can't be empty"); return }
    if (!email.includes('@')) { flashInfo(false, 'Enter a valid email address'); return }
    setSavingInfo(true)
    setInfoStatus(null)
    try {
      const updates: { username?: string; email?: string } = {}
      if (username.trim() !== profile.username) updates.username = username.trim()
      if (email.trim() !== profile.email) updates.email = email.trim()
      const updated = await updateProfile(updates)
      setProfile(updated)
      setUsername(updated.username)
      setEmail(updated.email)
      flashInfo(true, 'Profile updated.')
    } catch (err) {
      if (err instanceof SessionExpiredError) { redirectToLogin(); return }
      flashInfo(false, errorMessage(err, "We couldn't save your changes. Please try again."))
    } finally {
      setSavingInfo(false)
    }
  }

  function flashInfo(ok: boolean, text: string) {
    setInfoStatus({ ok, text })
    setTimeout(() => setInfoStatus(null), 4000)
  }

  async function savePassword(e: React.FormEvent) {
    e.preventDefault()
    if (savingPw) return
    const err = passwordError(newPw)
    if (err) { flashPw(false, err); return }
    if (newPw !== confirmPw) { flashPw(false, 'New passwords do not match'); return }
    setSavingPw(true)
    setPwStatus(null)
    try {
      await changePassword(currentPw, newPw)
      setCurrentPw(''); setNewPw(''); setConfirmPw('')
      flashPw(true, 'Password updated.')
    } catch (err2) {
      if (err2 instanceof SessionExpiredError) { redirectToLogin(); return }
      flashPw(false, errorMessage(err2, "We couldn't change your password. Please try again."))
    } finally {
      setSavingPw(false)
    }
  }

  function flashPw(ok: boolean, text: string) {
    setPwStatus({ ok, text })
    setTimeout(() => setPwStatus(null), 4000)
  }

  // Logout now lives here (moved off the nav bar), matching the Navbar's old flow
  function handleLogout() {
    clearToken()
    navigate('/login', { state: { notice: "You've been logged out successfully." } })
  }

  if (!getToken()) {
    return (
      <PageMessage action={{ to: '/login', label: 'Login', className: 'btn-primary btn-lg' }}>
        <h2>Log in to view your profile</h2>
        <p>Manage your account details and display preferences.</p>
      </PageMessage>
    )
  }

  if (loading) return <PageMessage><p>Loading profile...</p></PageMessage>
  if (loadError) return <PageMessage><p className="error">{loadError}</p></PageMessage>

  return (
    <div className="page">
      <div className={styles.pageHeader}>
        <h1>Profile</h1>
        <div className={styles.headerActions}>
          {profile?.is_admin && (
            <Link to="/admin" className="btn-outline btn-sm">Admin</Link>
          )}
          <button className="btn-outline btn-sm" onClick={handleLogout}>Log out</button>
        </div>
      </div>

      {/* ----- Account details ----- */}
      <section className={styles.card}>
        <h2 className={styles.cardTitle}>Account details</h2>
        {profile && (
          <p className={styles.memberSince}>Member since {memberSince(profile.created_at)}</p>
        )}
        <form className={styles.form} onSubmit={saveInfo}>
          <label className={styles.field}>
            <span className={styles.fieldLabel}>Username</span>
            <input
              className={styles.input}
              value={username}
              onChange={e => setUsername(e.target.value)}
              autoComplete="username"
            />
          </label>
          <label className={styles.field}>
            <span className={styles.fieldLabel}>Email</span>
            <input
              className={styles.input}
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              autoComplete="email"
            />
          </label>
          <div className={styles.formActions}>
            <button type="submit" className="btn-primary btn-sm" disabled={savingInfo || !infoChanged}>
              {savingInfo ? 'Saving…' : 'Save changes'}
            </button>
            {infoStatus && <StatusMessage ok={infoStatus.ok}>{infoStatus.text}</StatusMessage>}
          </div>
        </form>
      </section>

      {/* ----- Password ----- */}
      <section className={styles.card}>
        <h2 className={styles.cardTitle}>Password</h2>
        <p className={styles.cardHint}>At least 8 characters, with a letter and a number.</p>
        <form className={styles.form} onSubmit={savePassword}>
          <label className={styles.field}>
            <span className={styles.fieldLabel}>Current password</span>
            <input
              className={styles.input}
              type="password"
              value={currentPw}
              onChange={e => setCurrentPw(e.target.value)}
              autoComplete="current-password"
              required
            />
          </label>
          <label className={styles.field}>
            <span className={styles.fieldLabel}>New password</span>
            <input
              className={styles.input}
              type="password"
              value={newPw}
              onChange={e => setNewPw(e.target.value)}
              autoComplete="new-password"
              required
            />
          </label>
          <label className={styles.field}>
            <span className={styles.fieldLabel}>Confirm new password</span>
            <input
              className={styles.input}
              type="password"
              value={confirmPw}
              onChange={e => setConfirmPw(e.target.value)}
              autoComplete="new-password"
              required
            />
          </label>
          <div className={styles.formActions}>
            <button
              type="submit"
              className="btn-primary btn-sm"
              disabled={savingPw || !currentPw || !newPw || !confirmPw}
            >
              {savingPw ? 'Updating…' : 'Update password'}
            </button>
            {pwStatus && <StatusMessage ok={pwStatus.ok}>{pwStatus.text}</StatusMessage>}
          </div>
        </form>
      </section>

      {/* ----- Accessibility ----- */}
      <section className={styles.card}>
        <h2 className={styles.cardTitle}>Accessibility</h2>
        <p className={styles.cardHint}>Saved on this device. Changes apply immediately.</p>

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
      </section>

      <DeleteAccount />
    </div>
  )
}
