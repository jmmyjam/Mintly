import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import GainLoss from './GainLoss'
import { axe } from '../test/utils'

describe('GainLoss', () => {
  it('renders a signed gain with the positive class', () => {
    const { container } = render(<GainLoss value={6.31} />)
    const span = container.firstChild as HTMLElement
    expect(span).toHaveTextContent('+$6.31')
    expect(span).toHaveClass('positive')
  })

  it('renders a loss with the negative class', () => {
    const { container } = render(<GainLoss value={-58.11} />)
    expect(container.firstChild).toHaveClass('negative')
    expect(container).toHaveTextContent('-$58.11')
  })

  it('treats exactly zero as non-negative', () => {
    const { container } = render(<GainLoss value={0} />)
    expect(container.firstChild).toHaveClass('positive')
    expect(container).toHaveTextContent('$0.00')
  })

  it('appends a percent, prefixing a + when positive', () => {
    const { container } = render(<GainLoss value={10} pct={12.5} />)
    expect(container).toHaveTextContent('+$10.00 (+12.5%)')
  })

  it('omits the percent when it is null', () => {
    const { container } = render(<GainLoss value={10} pct={null} />)
    expect(container).not.toHaveTextContent('%')
  })

  it('has no accessibility violations', async () => {
    const { container } = render(<GainLoss value={-5} pct={-3} />)
    expect(await axe(container)).toHaveNoViolations()
  })
})
