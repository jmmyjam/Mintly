import { describe, it, expect } from 'vitest'
import { isGraded, gradeOptions, conditionLabel, holdingKey, conditionKey, RAW_CONDITIONS } from './grading'

describe('isGraded', () => {
  it('is false for unset and Raw, true for graders', () => {
    expect(isGraded(null)).toBe(false)
    expect(isGraded(undefined)).toBe(false)
    expect(isGraded('Raw')).toBe(false)
    expect(isGraded('PSA')).toBe(true)
    expect(isGraded('Other')).toBe(true)
  })
})

describe('gradeOptions', () => {
  it('returns the raw ladder for Raw and grader lists otherwise', () => {
    expect(gradeOptions('Raw')).toEqual(RAW_CONDITIONS)
    expect(gradeOptions('PSA')).toContain('10')
    expect(gradeOptions('Other')).toEqual([])
  })
})

describe('conditionLabel', () => {
  it('formats each case', () => {
    expect(conditionLabel(null, null)).toBe('')
    expect(conditionLabel('Raw', 'Near Mint')).toBe('Near Mint')
    expect(conditionLabel('Raw', null)).toBe('Raw')
    expect(conditionLabel('PSA', '10')).toBe('PSA 10')
    expect(conditionLabel('PSA', null)).toBe('PSA')
  })
})

describe('holdingKey / conditionKey', () => {
  it('separates lots by card + grading + grade', () => {
    expect(holdingKey('base1-4', 'PSA', '10')).toBe('base1-4|PSA|10')
    expect(holdingKey('base1-4', null, null)).toBe('base1-4||')
    // a raw NM and a PSA 10 of the same card are different holdings
    expect(holdingKey('base1-4', 'Raw', 'Near Mint')).not.toBe(holdingKey('base1-4', 'PSA', '10'))
  })

  it('conditionKey is the URL/param half, empty for unset', () => {
    expect(conditionKey(null, null)).toBe('')
    expect(conditionKey('PSA', '10')).toBe('PSA|10')
    expect(conditionKey('Raw', 'Near Mint')).toBe('Raw|Near Mint')
  })
})
