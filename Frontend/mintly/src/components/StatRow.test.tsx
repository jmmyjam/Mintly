import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import StatRow from './StatRow'
import { axe } from '../test/utils'

describe('StatRow', () => {
  it('renders its label and value', () => {
    render(<StatRow label="Rarity">Rare Holo</StatRow>)
    expect(screen.getByText('Rarity')).toBeInTheDocument()
    expect(screen.getByText('Rare Holo')).toBeInTheDocument()
  })

  it('has no accessibility violations', async () => {
    const { container } = render(<StatRow label="Set">Base</StatRow>)
    expect(await axe(container)).toHaveNoViolations()
  })
})
