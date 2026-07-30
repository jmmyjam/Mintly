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

// The three new-password rules, in the order the strength meter fills left to
// right (length, then a letter, then a number) — matches the register form.
function passwordRules(password: string): [boolean, boolean, boolean] {
  return [password.length >= 8, /[A-Za-z]/.test(password), /\d/.test(password)]
}

// created_at arrives as naive UTC (no zone suffix) — anchor it with Z so it
// reads as UTC, not local time (same fix as Portfolio's parseUTCDate)
function memberSince(iso: string): string {
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  return d.toLocaleDateString('en-US', { month: 'long', year: 'numeric' })
}

// Two-letter monogram for the avatar: first letters of the first two words when
// the username has any, otherwise the first two characters of a single token.
function initials(name: string): string {
  const parts = name.trim().split(/\s+/).filter(Boolean)
  if (parts.length >= 2) return (parts[0][0] + parts[1][0]).toUpperCase()
  return name.trim().slice(0, 2).toUpperCase()
}

type Status = { ok: boolean; text: string } | null

// An accessible on/off switch — role="switch" so it announces its state. Rows
// live inside the accessibility hairline stack, so each carries the panel fill.
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

// A password input with an inline Show/Hide toggle. The border + focus ring live
// on the wrapper so the toggle sits inside the same 14px-radius control (same
// pattern as the Login page).
function PasswordField({ label, value, onChange, autoComplete, describedBy }: {
  label: string
  value: string
  onChange: (next: string) => void
  autoComplete: string
  describedBy?: string
}) {
  const [show, setShow] = useState(false)
  return (
    <label className={styles.field}>
      <span className={styles.fieldLabel}>{label}</span>
      <span className={styles.pwField}>
        <input
          className={styles.pwInput}
          type={show ? 'text' : 'password'}
          value={value}
          onChange={e => onChange(e.target.value)}
          autoComplete={autoComplete}
          aria-describedby={describedBy}
          required
        />
        <button
          type="button"
          className={styles.showToggle}
          onClick={() => setShow(v => !v)}
          aria-pressed={show}
          aria-label={show ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
        >
          {show ? 'Hide' : 'Show'}
        </button>
      </span>
    </label>
  )
}

const TEXT_SIZES: { value: TextSize; label: string }[] = [
  { value: 'default', label: 'Default' },
  { value: 'large', label: 'Large' },
  { value: 'larger', label: 'Larger' },
]

// Rail sections — ids match the panel ids the anchor links jump to and the
// IntersectionObserver watches.
const SECTIONS = [
  { id: 'account', label: 'Account details' },
  { id: 'password', label: 'Password' },
  { id: 'accessibility', label: 'Accessibility' },
  { id: 'delete', label: 'Delete account' },
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

  // Which rail item is highlighted (driven by scroll position)
  const [activeSection, setActiveSection] = useState('account')

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

  // Highlight the rail item for whichever panel is in the upper band of the
  // viewport. Runs once the panels exist (after load), off a narrow rootMargin
  // detection line so exactly one section is "active" as you scroll.
  useEffect(() => {
    if (loading || loadError || !getToken()) return
    const els = SECTIONS
      .map(s => document.getElementById(s.id))
      .filter((el): el is HTMLElement => el !== null)
    if (!els.length) return
    const observer = new IntersectionObserver(
      entries => {
        const visible = entries.filter(e => e.isIntersecting)
        if (!visible.length) return
        const topmost = visible.reduce((a, b) =>
          a.boundingClientRect.top < b.boundingClientRect.top ? a : b)
        setActiveSection(topmost.target.id)
      },
      { rootMargin: '-25% 0px -65% 0px', threshold: 0 },
    )
    els.forEach(el => observer.observe(el))
    return () => observer.disconnect()
  }, [loading, loadError])

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

  // New-password strength (only meaningful while the field has content)
  const newPwRules = passwordRules(newPw)
  const newPwPassed = newPwRules.filter(Boolean).length
  const strengthComplete = newPwPassed === 3
  const strengthText = !newPwRules[0]
    ? '8 characters minimum'
    : !newPwRules[1]
      ? 'Add a letter'
      : !newPwRules[2]
        ? 'Add a number'
        : 'Strong password'

  const pwDisabled = savingPw || !currentPw || !newPw || !confirmPw

  return (
    <div className="page">
      {/* ----- Identity header ----- */}
      <header className={styles.identity}>
        <div className={styles.identityMain}>
          <span className={styles.avatar} aria-hidden="true">
            {profile ? initials(profile.username) : ''}
          </span>
          <div className={styles.identityText}>
            <h1 className={styles.username}>{profile?.username}</h1>
            {profile && (
              <p className={styles.meta}>Member since {memberSince(profile.created_at)}</p>
            )}
          </div>
        </div>
        <div className={styles.identityActions}>
          {profile?.is_admin && (
            <Link to="/admin" className={styles.headerPill}>Admin</Link>
          )}
          <button type="button" className={styles.headerPill} onClick={handleLogout}>
            Log out
          </button>
        </div>
      </header>

      <div className={styles.layout}>
        {/* ----- Section rail ----- */}
        <nav className={styles.rail} aria-label="Profile sections">
          {SECTIONS.map(s => (
            <a
              key={s.id}
              href={`#${s.id}`}
              className={`${styles.railItem} ${activeSection === s.id ? styles.railItemActive : ''}`}
              aria-current={activeSection === s.id ? 'true' : undefined}
              onClick={() => setActiveSection(s.id)}
            >
              {s.label}
            </a>
          ))}
        </nav>

        {/* ----- Panels ----- */}
        <div className={styles.panels}>
          {/* Account details */}
          <section id="account" className={styles.panel}>
            <h2 className={styles.panelTitle}>Account details</h2>
            <form className={styles.accountForm} onSubmit={saveInfo}>
              <div className={styles.accountGrid}>
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
              </div>
              <div className={styles.actions}>
                <button type="submit" className={styles.submitPill} disabled={savingInfo || !infoChanged}>
                  {savingInfo ? 'Saving…' : 'Save changes'}
                </button>
                {infoStatus ? (
                  <StatusMessage ok={infoStatus.ok}>{infoStatus.text}</StatusMessage>
                ) : (
                  !infoChanged && !savingInfo && <span className={styles.actionHint}>No changes yet</span>
                )}
              </div>
            </form>
          </section>

          {/* Password */}
          <section id="password" className={styles.panel}>
            <h2 className={styles.panelTitle}>Password</h2>
            <form className={styles.pwForm} onSubmit={savePassword}>
              <PasswordField
                label="Current password"
                value={currentPw}
                onChange={setCurrentPw}
                autoComplete="current-password"
              />
              <PasswordField
                label="New password"
                value={newPw}
                onChange={setNewPw}
                autoComplete="new-password"
                describedBy="pw-strength-desc"
              />
              <div className={styles.strength}>
                <span className={styles.strengthBars} aria-hidden="true">
                  {[0, 1, 2].map(i => (
                    <span
                      key={i}
                      className={`${styles.strengthBar} ${i < newPwPassed ? styles.strengthBarOn : ''}`}
                    />
                  ))}
                </span>
                <span
                  id="pw-strength-desc"
                  className={`${styles.strengthText} ${strengthComplete ? styles.strengthTextDone : ''}`}
                >
                  {strengthText}
                </span>
              </div>
              <PasswordField
                label="Confirm new password"
                value={confirmPw}
                onChange={setConfirmPw}
                autoComplete="new-password"
              />
              <div className={styles.actions}>
                <button type="submit" className={styles.submitPill} disabled={pwDisabled}>
                  {savingPw ? 'Updating…' : 'Update password'}
                </button>
                {pwStatus && <StatusMessage ok={pwStatus.ok}>{pwStatus.text}</StatusMessage>}
              </div>
            </form>
          </section>

          {/* Accessibility */}
          <section id="accessibility" className={styles.panel}>
            <h2 className={styles.panelTitle}>Accessibility</h2>
            <p className={styles.panelHint}>Saved on this device. Changes apply immediately.</p>

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
          </section>

          {/* Delete account */}
          <DeleteAccount />
        </div>
      </div>
    </div>
  )
}
