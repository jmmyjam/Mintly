import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { login, register } from '../api'

// Mirrors the backend rules in auth.py so users get instant feedback
function passwordError(password: string): string | null {
  if (password.length < 8) return 'Password must be at least 8 characters'
  if (!/[A-Za-z]/.test(password)) return 'Password must contain at least one letter'
  if (!/\d/.test(password)) return 'Password must contain at least one number'
  return null
}

export default function Login() {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()
  // e.g. "Your session expired — please log in again." when redirected here on a 401
  const notice = (location.state as { notice?: string } | null)?.notice

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
    if (mode === 'register') {
      const pwError = passwordError(password)
      if (pwError) {
        setError(pwError)
        return
      }
    }
    setLoading(true)
    try {
      if (mode === 'register') {
        await register(email, username, password)
      }
      await login(username, password)
      navigate('/portfolio')
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Something went wrong')
    } finally {
      setLoading(false)
    }
  }

  function switchMode(next: 'login' | 'register') {
    setMode(next)
    setError('')
    setEmail('')
    setUsername('')
    setPassword('')
  }

  return (
    <div className="page centered">
      <div className="auth-card">
        <div className="auth-tabs">
          <button className={`tab ${mode === 'login' ? 'active' : ''}`} onClick={() => switchMode('login')}>
            Login
          </button>
          <button className={`tab ${mode === 'register' ? 'active' : ''}`} onClick={() => switchMode('register')}>
            Register
          </button>
        </div>

        {notice && !error && <p className="form-hint">{notice}</p>}

        <form onSubmit={handleSubmit} className="auth-form">
          {mode === 'register' && (
            <input
              type="email"
              placeholder="Email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              required
              className="form-input"
            />
          )}
          <input
            type="text"
            placeholder="Username"
            value={username}
            onChange={e => setUsername(e.target.value)}
            required
            className="form-input"
          />
          <input
            type="password"
            placeholder="Password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            required
            className="form-input"
          />
          {mode === 'register' && (
            <p className="form-hint">At least 8 characters, with a letter and a number.</p>
          )}
          {error && <p className="error">{error}</p>}
          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? 'Please wait...' : mode === 'login' ? 'Login' : 'Create Account'}
          </button>
        </form>
      </div>
    </div>
  )
}
