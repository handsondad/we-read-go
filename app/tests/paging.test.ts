import { describe, expect, it } from 'vitest'
import { ref } from 'vue'
import { usePaged } from '../src/paging'

describe('paged lists', () => {
  it('shows one page at a time, follows the source, and resets', () => {
    const items = ref(Array.from({ length: 7 }, (_, index) => index))
    const { visible, remaining, more, reset } = usePaged(() => items.value, 3)
    expect(visible.value).toEqual([0, 1, 2])
    expect(remaining.value).toBe(4)
    more()
    more()
    expect(visible.value).toHaveLength(7)
    expect(remaining.value).toBe(0)
    more()
    items.value = [...items.value, 7, 8, 9]
    // Reaching the end must not pre-load pages that did not exist yet.
    expect(visible.value).toHaveLength(9)
    expect(remaining.value).toBe(1)
    reset()
    expect(visible.value).toEqual([0, 1, 2])
    items.value = [5]
    expect(visible.value).toEqual([5])
    expect(remaining.value).toBe(0)
  })
})
