import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import StatusMessage from './StatusMessage'
import { axe } from '../test/utils'

describe('StatusMessage', () => {
  it('uses the success class when ok', () => {
    const { container } = render(<StatusMessage ok>Added to your portfolio</StatusMessage>)
    const msg = container.firstChild as HTMLElement
    expect(msg).toHaveClass('success-msg')
    expect(screen.getByText('Added to your portfolio')).toBeInTheDocument()
  })

  it('uses the error class when not ok', () => {
    const { container } = render(<StatusMessage ok={false}>Something went wrong</StatusMessage>)
    expect(container.firstChild).toHaveClass('error')
  })

  it('has no accessibility violations', async () => {
    const { container } = render(<StatusMessage ok>Saved</StatusMessage>)
    expect(await axe(container)).toHaveNoViolations()
  })
})
