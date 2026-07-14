import { useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'

// Real queries the smart search handles well (name + set name combos)
const EXAMPLES = [
  'charizard base',
  'umbreon evolving skies',
  'pikachu vmax',
  'gengar lost origin',
  'eevee prismatic evolutions',
]

const QUICK_SEARCHES = ['Charizard', 'Pikachu VMAX', 'Evolving Skies', 'Prismatic Evolutions']

// Typewriter effect for the placeholder: type an example, pause, erase, next.
// All state updates happen inside timeout callbacks (strict react-hooks rule).
function useTypingPlaceholder(examples: string[]) {
  const [text, setText] = useState('')
  const [index, setIndex] = useState(0)
  const [deleting, setDeleting] = useState(false)

  useEffect(() => {
    const full = examples[index]
    const delay = deleting ? 35 : text === full ? 2000 : 75
    const timer = setTimeout(() => {
      if (!deleting) {
        if (text === full) setDeleting(true)
        else setText(full.slice(0, text.length + 1))
      } else if (text === '') {
        setDeleting(false)
        setIndex((index + 1) % examples.length)
      } else {
        setText(full.slice(0, text.length - 1))
      }
    }, delay)
    return () => clearTimeout(timer)
  }, [text, deleting, index, examples])

  return text
}

// The home hero's search pill: submitting hands the query to the Search page
// via /search?q=, where it runs automatically.
export default function HeroSearch() {
  const navigate = useNavigate()
  const [value, setValue] = useState('')
  const placeholder = useTypingPlaceholder(EXAMPLES)

  function goSearch(query: string) {
    const q = query.trim()
    if (q) navigate(`/search?q=${encodeURIComponent(q)}`)
  }

  return (
    <div className="hero-search-block">
      <form
        className="hero-search"
        onSubmit={e => {
          e.preventDefault()
          goSearch(value)
        }}
      >
        <input
          className="hero-search-input"
          value={value}
          onChange={e => setValue(e.target.value)}
          placeholder={placeholder}
          aria-label="Search cards"
        />
        <button type="submit" className="btn-primary hero-search-btn">
          Search
        </button>
      </form>
      <div className="hero-chips">
        <span className="hero-chips-label">Try</span>
        {QUICK_SEARCHES.map(q => (
          <button key={q} className="chip" onClick={() => goSearch(q)}>
            {q}
          </button>
        ))}
      </div>
    </div>
  )
}
