import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { login, register } from '../api'

export default function Login() {
  const [mode, setMode] = useState<'login' | 'register'>('login')
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError('')
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
          {error && <p className="error">{error}</p>}
          <button type="submit" className="btn-primary" disabled={loading}>
            {loading ? 'Please wait...' : mode === 'login' ? 'Login' : 'Create Account'}
          </button>
        </form>
      </div>
    </div>
  )
}
