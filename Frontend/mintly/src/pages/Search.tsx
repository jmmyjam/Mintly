import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { searchCards, addCard, getToken, getCardPrice, type Card } from '../api'

export default function Search() {
  const [query, setQuery] = useState('')
  const [cards, setCards] = useState<Card[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [adding, setAdding] = useState<string | null>(null)
  const [purchasePrice, setPurchasePrice] = useState('')
  const [quantity, setQuantity] = useState('1')
  const [addStatus, setAddStatus] = useState<{ id: string; msg: string; ok: boolean } | null>(null)
  const navigate = useNavigate()

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault()
    if (!query.trim()) return
    setLoading(true)
    setError('')
    setCards([])
    setAdding(null)
    try {
      const results = await searchCards(query)
      setCards(results)
      if (results.length === 0) setError('No cards found.')
    } catch {
      setError('Search failed. Make sure the server is running.')
    } finally {
      setLoading(false)
    }
  }

  async function handleAdd(card: Card) {
    if (!getToken()) {
      navigate('/login')
      return
    }
    try {
      await addCard(card.id, parseFloat(purchasePrice) || 0, parseInt(quantity) || 1)
      setAdding(null)
      setPurchasePrice('')
      setQuantity('1')
      setAddStatus({ id: card.id, msg: 'Added to portfolio!', ok: true })
      setTimeout(() => setAddStatus(null), 3000)
    } catch (err: unknown) {
      const msg = err instanceof Error ? err.message : 'Failed to add card'
      setAddStatus({ id: card.id, msg, ok: false })
      setTimeout(() => setAddStatus(null), 3000)
    }
  }

  return (
    <div className="page">
      <h1>Search Cards</h1>
      <form onSubmit={handleSearch} className="search-form">
        <input
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search by name (e.g. Charizard)"
          className="search-input"
        />
        <button type="submit" className="btn-primary" disabled={loading}>
          {loading ? 'Searching...' : 'Search'}
        </button>
      </form>

      {error && <p className="error">{error}</p>}

      <div className="card-grid">
        {cards.map(card => {
          const price = getCardPrice(card)
          const isAdding = adding === card.id
          const status = addStatus?.id === card.id ? addStatus : null

          return (
            <div key={card.id} className="card-item">
              <img src={card.images.small} alt={card.name} className="card-image" loading="lazy" />
              <div className="card-info">
                <p className="card-name">{card.name}</p>
                <p className="card-set">{card.set.name}</p>
                {price != null && <p className="card-price">${price.toFixed(2)}</p>}
              </div>

              {status && (
                <p className={status.ok ? 'success-msg' : 'error'}>{status.msg}</p>
              )}

              {!status && (isAdding ? (
                <div className="add-form">
                  <input
                    type="number"
                    placeholder="Purchase price ($)"
                    value={purchasePrice}
                    onChange={e => setPurchasePrice(e.target.value)}
                    className="mini-input"
                    min="0"
                    step="0.01"
                  />
                  <input
                    type="number"
                    placeholder="Qty"
                    value={quantity}
                    onChange={e => setQuantity(e.target.value)}
                    className="mini-input mini-qty"
                    min="1"
                  />
                  <div className="add-form-buttons">
                    <button className="btn-primary btn-sm" onClick={() => handleAdd(card)}>Add</button>
                    <button className="btn-outline btn-sm" onClick={() => { setAdding(null); setPurchasePrice(''); setQuantity('1') }}>Cancel</button>
                  </div>
                </div>
              ) : (
                <button className="btn-outline btn-sm" onClick={() => setAdding(card.id)}>
                  + Portfolio
                </button>
              ))}
            </div>
          )
        })}
      </div>
    </div>
  )
}
