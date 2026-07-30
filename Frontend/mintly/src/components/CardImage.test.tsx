import { describe, it, expect } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import CardImage from './CardImage'
import { axe } from '../test/utils'

describe('CardImage', () => {
  it('renders the artwork with its alt text when a src is given', () => {
    render(<CardImage src="https://img.example/card.png" alt="Charizard" />)
    const img = screen.getByRole('img', { name: 'Charizard' })
    expect(img.tagName).toBe('IMG')
    expect(img).toHaveAttribute('src', 'https://img.example/card.png')
  })

  it('lazy-loads by default and eager-loads only when asked', () => {
    const { rerender } = render(<CardImage src="x" alt="c" />)
    expect(screen.getByRole('img')).toHaveAttribute('loading', 'lazy')
    rerender(<CardImage src="x" alt="c" eager />)
    expect(screen.getByRole('img')).toHaveAttribute('loading', 'eager')
  })

  it('shows a labeled placeholder (role=img) when there is no src', () => {
    render(<CardImage src={null} alt="Missing card" />)
    const placeholder = screen.getByRole('img', { name: 'Missing card' })
    expect(placeholder.tagName).toBe('SPAN')
    // the decorative fallback glyph is hidden from assistive tech
    expect(placeholder.querySelector('svg')).toHaveAttribute('aria-hidden', 'true')
  })

  it('falls back to the placeholder when the image fails to load', () => {
    render(<CardImage src="broken.png" alt="Broken card" />)
    fireEvent.error(screen.getByRole('img', { name: 'Broken card' }))
    const placeholder = screen.getByRole('img', { name: 'Broken card' })
    expect(placeholder.tagName).toBe('SPAN')
  })

  it('has no accessibility violations with an image', async () => {
    const { container } = render(<CardImage src="x" alt="Pikachu" />)
    expect(await axe(container)).toHaveNoViolations()
  })

  it('has no accessibility violations in the placeholder state', async () => {
    const { container } = render(<CardImage src={null} alt="Pikachu" />)
    expect(await axe(container)).toHaveNoViolations()
  })
})
