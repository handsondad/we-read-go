import { computed, ref } from 'vue'

export const PAGE_SIZE = 30

/** 长列表分批渲染：先显示一页，触底或点按钮后再追加，避免一次创建几百张卡片和封面。 */
export function usePaged<T>(source: () => readonly T[], size = PAGE_SIZE) {
  const limit = ref(size)
  const visible = computed(() => source().slice(0, limit.value))
  const remaining = computed(() => Math.max(0, source().length - limit.value))
  const more = () => { if (remaining.value > 0) limit.value += size }
  const reset = () => { limit.value = size }
  return { visible, remaining, more, reset }
}
