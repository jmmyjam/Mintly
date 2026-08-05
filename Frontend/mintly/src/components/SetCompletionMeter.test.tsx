import { describe, it, expect } from 'vitest'
import { render } from '@testing-library/react'
import SetCompletionMeter from './SetCompletionMeter'
import { axe } from '../test/utils'

describe('SetCompletionMeter', () => {
  it('renders the owned/total count', () => {
    const { container } = render(<SetCompletionMeter owned={45} total={102} />)
    expect(container).toHaveTextContent('45/102')
  })

  it('exposes progressbar semantics with an accessible name', () => {
    const { getByRole } = render(
      <SetCompletionMeter owned={45} total={102} label="45 of 102 owned in Base" />,
    )
    const bar = getByRole('progressbar')
    expect(bar).toHaveAttribute('aria-valuenow', '45')
    expect(bar).toHaveAttribute('aria-valuemin', '0')
    expect(bar).toHaveAttribute('aria-valuemax', '102')
    expect(bar).toHaveAccessibleName('45 of 102 owned in Base')
  })

  it('appends a percent only when showPercent is set', () => {
    const { rerender, container } = render(<SetCompletionMeter owned={51} total={102} />)
    expect(container).not.toHaveTextContent('%')
    rerender(<SetCompletionMeter owned={51} total={102} showPercent />)
    expect(container).toHaveTextContent('50%')
  })

  it('caps the fill at 100% and never divides by zero', () => {
    // owned above total (shouldn't happen, but must not overflow) and a zero total
    expect(() => render(<SetCompletionMeter owned={5} total={0} showPercent />)).not.toThrow()
    const { container } = render(<SetCompletionMeter owned={120} total={100} showPercent />)
    expect(container).toHaveTextContent('100%')
  })

  it('has no accessibility violations', async () => {
    const { container } = render(
      <SetCompletionMeter owned={3} total={102} label="3 of 102 owned in Base" showPercent />,
    )
    expect(await axe(container)).toHaveNoViolations()
  })
})
