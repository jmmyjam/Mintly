import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import DayChange from './DayChange'
import { axe } from '../test/utils'

describe('DayChange', () => {
  it('shows an up arrow, amount, percent, and a "since" title for a gain', () => {
    const { container } = render(
      <DayChange change={{ amount: 1.25, percent: 3.2, since: '2026-07-20' }} />,
    )
    const span = container.firstChild as HTMLElement
    expect(span).toHaveClass('day-change-positive')
    expect(span).toHaveTextContent('▲+$1.25 (+3.2%)')
    expect(span).toHaveAttribute('title', 'Change since Jul 20')
  })

  it('shows a down arrow and the negative class for a drop (magnitude only, arrow carries direction)', () => {
    const { container } = render(
      <DayChange change={{ amount: -0.5, percent: -2.5, since: '2026-07-20' }} />,
    )
    const span = container.firstChild as HTMLElement
    expect(span).toHaveClass('day-change-negative')
    expect(span).toHaveTextContent('▼$0.50 (-2.5%)')
  })

  it('renders a flat dash when the price did not move', () => {
    const { container } = render(
      <DayChange change={{ amount: 0, percent: 0, since: '2026-07-20' }} />,
    )
    expect(container.firstChild).toHaveClass('day-change-flat')
    expect(container).toHaveTextContent('–$0.00')
  })

  it('omits the percent when it is null', () => {
    const { container } = render(
      <DayChange change={{ amount: 1, percent: null, since: '2026-07-20' }} />,
    )
    expect(container).not.toHaveTextContent('%')
  })

  it('appends "today" when the today flag is set', () => {
    const { container } = render(
      <DayChange change={{ amount: 1, percent: 2, since: '2026-07-20' }} today />,
    )
    expect(container).toHaveTextContent('today')
  })

  it('has no accessibility violations', async () => {
    const { container } = render(
      <DayChange change={{ amount: -0.5, percent: -2.5, since: '2026-07-20' }} />,
    )
    expect(await axe(container)).toHaveNoViolations()
  })
})
