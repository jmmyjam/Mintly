import { useEffect, useState } from 'react'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from 'recharts'
import {
  deleteAdminFeedback, getAdminFeedback, getAdminStats, getToken, CONNECTION_ERROR,
  NotAdminError, SessionExpiredError, type AdminFeedback, type AdminStats,
} from '../api'
import StatusMessage from '../components/StatusMessage'
import NotFoundMessage from '../components/NotFoundMessage'
import PageMessage from '../components/PageMessage'
import styles from './Admin.module.css'

// Timestamps arrive as naive UTC (no zone suffix) — anchor with Z so they read
// as UTC, not local time (same fix as Portfolio's parseUTCDate)
function formatDateTime(iso: string): string {
  const d = new Date(iso.endsWith('Z') ? iso : iso + 'Z')
  return d.toLocaleString('en-US', {
    month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit',
  })
}

function formatDay(date: string): string {
  return new Date(date + 'T00:00:00').toLocaleDateString('en-US', {
    month: 'short', day: 'numeric',
  })
}

function formatBytes(bytes: number): string {
  if (bytes >= 1e9) return `${(bytes / 1e9).toFixed(2)} GB`
  if (bytes >= 1e6) return `${(bytes / 1e6).toFixed(1)} MB`
  if (bytes >= 1e3) return `${Math.round(bytes / 1e3)} KB`
  return `${bytes} B`
}

function num(n: number): string {
  return n.toLocaleString('en-US')
}

function StatTile({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className={styles.tile}>
      <span className={styles.tileLabel}>{label}</span>
      <span className={styles.tileValue}>{value}</span>
      {sub && <span className={styles.tileSub}>{sub}</span>}
    </div>
  )
}

// Messages from the public /feedback form, newest first. Loaded on its own so
// a feedback hiccup can't take down the stats above it. Delete is a two-step
// inline confirm (no native dialogs), for clearing spam that got through.
function FeedbackInbox() {
  const [items, setItems] = useState<AdminFeedback[] | null>(null)
  const [loadError, setLoadError] = useState('')
  const [confirmId, setConfirmId] = useState<number | null>(null)
  const [deleteError, setDeleteError] = useState('')

  useEffect(() => {
    getAdminFeedback()
      .then(setItems)
      .catch(() => setLoadError("We couldn't load feedback."))
  }, [])

  async function remove(id: number) {
    try {
      await deleteAdminFeedback(id)
      setItems(prev => (prev ?? []).filter(f => f.id !== id))
      setConfirmId(null)
    } catch (err) {
      setDeleteError(err instanceof Error ? err.message : 'Delete failed.')
      setTimeout(() => setDeleteError(''), 4000)
    }
  }

  return (
    <section className={styles.section}>
      <h2 className={styles.sectionTitle}>Feedback</h2>
      {deleteError && <StatusMessage ok={false}>{deleteError}</StatusMessage>}
      {loadError ? (
        <p className="error">{loadError}</p>
      ) : items === null ? (
        <p className="prices-note">Loading…</p>
      ) : items.length === 0 ? (
        <p className="prices-note">No feedback yet.</p>
      ) : (
        <ul className={styles.feedbackList}>
          {items.map(f => (
            <li key={f.id} className={styles.feedbackItem}>
              <div className={styles.feedbackMeta}>
                <span>{formatDateTime(f.created_at)}</span>
                {f.page && <span>on {f.page}</span>}
                {f.email && <a href={`mailto:${f.email}`}>{f.email}</a>}
                <span className={styles.feedbackActions}>
                  {confirmId === f.id ? (
                    <>
                      <button className="btn-outline btn-sm" onClick={() => remove(f.id)}>
                        Confirm delete
                      </button>
                      <button className="btn-outline btn-sm" onClick={() => setConfirmId(null)}>
                        Cancel
                      </button>
                    </>
                  ) : (
                    <button className="btn-outline btn-sm" onClick={() => setConfirmId(f.id)}>
                      Delete
                    </button>
                  )}
                </span>
              </div>
              <p className={styles.feedbackMessage}>{f.message}</p>
            </li>
          ))}
        </ul>
      )}
    </section>
  )
}

// Private site dashboard (route /admin). The backend 404s the stats call for
// any account not on its ADMIN_EMAILS list, and this page renders the shared
// 404 view for logged-out, expired-session, and non-admin visitors alike —
// deliberately NOT the usual login prompt / session redirect, which would
// reveal there's an authed page here. To a non-admin, /admin IS /taco.
export default function Admin() {
  const [stats, setStats] = useState<AdminStats | null>(null)
  const [loading, setLoading] = useState(() => !!getToken())
  const [refreshing, setRefreshing] = useState(false)
  const [notFound, setNotFound] = useState(false)
  const [error, setError] = useState('')

  function load() {
    getAdminStats()
      .then(s => {
        setStats(s)
        setError('')
      })
      .catch(err => {
        if (err instanceof SessionExpiredError || err instanceof NotAdminError) {
          setNotFound(true)
          return
        }
        setError(
          err instanceof TypeError
            ? CONNECTION_ERROR
            : "We couldn't load the site stats. Please try again in a moment.",
        )
      })
      .finally(() => {
        setLoading(false)
        setRefreshing(false)
      })
  }

  useEffect(() => {
    if (!getToken()) return
    load()
  }, [])

  function refresh() {
    if (refreshing) return
    setRefreshing(true)
    load()
  }

  if (!getToken() || notFound) return <NotFoundMessage />
  // Generic wording: a non-admin sees this for a beat before the 404 lands,
  // and "site stats" would name the very page we're hiding
  if (loading) return <PageMessage><p>Loading…</p></PageMessage>
  if (error || !stats) {
    return <PageMessage><p className="error">{error || 'Something went wrong.'}</p></PageMessage>
  }

  const pctWithPortfolio = stats.users.total > 0
    ? `${Math.round((stats.users.with_portfolio / stats.users.total) * 100)}% of accounts`
    : undefined

  return (
    <div className="page">
      <div className={styles.pageHeader}>
        <div>
          <h1>Admin</h1>
          <p className={styles.generatedAt}>
            Site stats · updated {formatDateTime(stats.generated_at)}
          </p>
        </div>
        <button className="btn-outline btn-sm" onClick={refresh} disabled={refreshing}>
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Users</h2>
        <div className={styles.tileGrid}>
          <StatTile label="Total users" value={num(stats.users.total)} />
          <StatTile label="New (7 days)" value={num(stats.users.new_7d)} />
          <StatTile label="New (30 days)" value={num(stats.users.new_30d)} />
          <StatTile
            label="With a portfolio"
            value={num(stats.users.with_portfolio)}
            sub={pctWithPortfolio}
          />
        </div>
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Signups over the last 30 days</h2>
        <div className={styles.chartCard}>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={stats.signups_by_day} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
              <CartesianGrid stroke="var(--border)" strokeDasharray="3 3" vertical={false} />
              <XAxis
                dataKey="date"
                tickFormatter={formatDay}
                stroke="var(--text)"
                fontSize={12}
                tickLine={false}
                axisLine={false}
                minTickGap={28}
              />
              <YAxis
                allowDecimals={false}
                stroke="var(--text)"
                fontSize={12}
                tickLine={false}
                axisLine={false}
                width={32}
              />
              <Tooltip
                formatter={value => [String(value), 'Signups']}
                labelFormatter={label => formatDay(String(label))}
                contentStyle={{ background: 'var(--bg-card)', border: '1px solid var(--border)', borderRadius: 8 }}
                labelStyle={{ color: 'var(--text)' }}
                itemStyle={{ color: 'var(--text)' }}
                cursor={{ fill: 'rgba(255, 255, 255, 0.06)' }}
              />
              <Bar
                dataKey="count"
                fill="var(--accent)"
                radius={[4, 4, 0, 0]}
                maxBarSize={18}
                isAnimationActive={false}
              />
            </BarChart>
          </ResponsiveContainer>
        </div>
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Portfolios</h2>
        <div className={styles.tileGrid}>
          <StatTile label="Portfolios" value={num(stats.portfolio.portfolios)} sub="named collections" />
          <StatTile label="Lots" value={num(stats.portfolio.lots)} sub="one row per purchase" />
          <StatTile label="Distinct cards held" value={num(stats.portfolio.distinct_cards)} />
          <StatTile label="Total cards held" value={num(stats.portfolio.total_quantity)} sub="sum of quantities" />
        </div>
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Data health</h2>
        <div className={styles.tileGrid}>
          <StatTile label="Catalog cards" value={num(stats.catalog.cards)} />
          <StatTile
            label="Last full crawl"
            value={stats.catalog.last_full_sync ? formatDateTime(stats.catalog.last_full_sync) : '—'}
            sub={stats.catalog.last_full_sync ? undefined : 'catalog not synced'}
          />
          <StatTile label="Stale prices" value={num(stats.catalog.stale_prices)} sub="older than 6h" />
          <StatTile label="Price snapshots" value={num(stats.snapshots.rows)} sub="rows in the DB" />
          <StatTile label="Snapshots today" value={num(stats.snapshots.today)} sub="cards priced so far" />
          <StatTile
            label="Database size"
            value={stats.db_size_bytes != null ? formatBytes(stats.db_size_bytes) : '—'}
          />
        </div>
      </section>

      <section className={styles.section}>
        <h2 className={styles.sectionTitle}>Recent signups</h2>
        {stats.recent_users.length === 0 ? (
          <p className="prices-note">No accounts yet.</p>
        ) : (
          <div className={styles.tableWrap}>
            <table className={styles.table}>
              <thead>
                <tr>
                  <th>Username</th>
                  <th>Email</th>
                  <th>Joined</th>
                  <th className={styles.numCol}>Lots</th>
                </tr>
              </thead>
              <tbody>
                {stats.recent_users.map(u => (
                  <tr key={u.id}>
                    <td>{u.username}</td>
                    <td className={styles.mutedCell}>{u.email}</td>
                    <td className={styles.mutedCell}>{formatDateTime(u.created_at)}</td>
                    <td className={styles.numCol}>{num(u.lots)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      <FeedbackInbox />
    </div>
  )
}
