import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import PriceBasisLabel from './PriceBasisLabel'

describe('PriceBasisLabel', () => {
  it('says nothing for a normal TCGplayer price', () => {
    // Labelling the default path everywhere would be noise, not information
    const { container } = render(<PriceBasisLabel basis={{ kind: 'market' }} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('marks a slab median as an estimate', () => {
    render(<PriceBasisLabel basis={{ kind: 'ebay', sales: 12 }} />)
    expect(screen.getByText(/eBay est\./)).toBeInTheDocument()
  })

  it('names the comp count in detail mode, so a thin estimate reads as thin', () => {
    render(<PriceBasisLabel basis={{ kind: 'ebay', sales: 3 }} detail />)
    expect(screen.getByText(/eBay est\. from 3 recent sales/)).toBeInTheDocument()
  })

  it('singularises a one-sale estimate', () => {
    render(<PriceBasisLabel basis={{ kind: 'ebay', sales: 1 }} detail />)
    expect(screen.getByText(/1 recent sale$/)).toBeInTheDocument()
  })

  it('omits a zero comp count rather than claiming "0 recent sales"', () => {
    render(<PriceBasisLabel basis={{ kind: 'ebay', sales: 0 }} detail />)
    expect(screen.getByText('eBay est.')).toBeInTheDocument()
  })

  it('flags an at-cost holding', () => {
    render(<PriceBasisLabel basis={{ kind: 'cost' }} />)
    expect(screen.getByText('at cost')).toBeInTheDocument()
  })

  it('explains at-cost in detail mode', () => {
    render(<PriceBasisLabel basis={{ kind: 'cost' }} detail />)
    expect(screen.getByText(/No recent graded sales to price this from/)).toBeInTheDocument()
  })

  it('resolves its CSS-module classes', () => {
    // A mis-keyed styles.x is silently undefined and renders unstyled
    const { rerender } = render(<PriceBasisLabel basis={{ kind: 'ebay', sales: 4 }} />)
    expect(screen.getByText(/eBay est\./).className).toBeTruthy()
    rerender(<PriceBasisLabel basis={{ kind: 'cost' }} />)
    expect(screen.getByText('at cost').className).toBeTruthy()
  })
})
