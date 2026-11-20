<script setup lang="ts">
import { computed } from 'vue'
import { state } from '../../store'

const readingTime = computed(() => {
  const seconds = state.data.readingSeconds
  if (seconds === null) return '尚未同步'
  return `${Math.floor(seconds / 3600)} 小时 ${Math.floor(seconds % 3600 / 60)} 分`
})
const finished = computed(() => state.data.books.filter((book) => book.status === 'finished').length)
const entries = computed(() => [...state.data.entries].sort((a, b) => b.date.localeCompare(a.date)))
const room = computed(() => state.data.entries.length >= 20 ? '书架旁添了一盆小绿植'
  : state.data.entries.length >= 5 ? '阅读角里亮起了一盏灯' : '小书友在阅读角等你')
function bookTitle(id: string | null) {
  return state.data.books.find((book) => book.id === id)?.title ?? '给自己留了一点阅读时间'
}
</script>

<template>
  <view class="page">
    <text class="eyebrow">EVERY RETURN COUNTS</text>
    <text class="heading">每次回来，都算数。</text>
    <text class="intro">不比连续天数，只收集那些你和书相遇的时刻。</text>
    <view class="card">
      <text class="title">{{ room }}</text>
      <text class="body">在本机记录过 {{ state.data.entries.length }} 个阅读日</text>
      <text class="small">累计成长不会因漏读减少；阅读角在 5 / 20 个记录日迎来小变化。</text>
    </view>
    <view class="card">
      <text class="title">书与时间</text>
      <text class="body">本机书架中读完：{{ finished }} 本</text>
      <text class="body">微信读书累计阅读：{{ readingTime }}</text>
      <text class="small">时长来自上次官方同步，不是本机打卡推算。</text>
    </view>
    <view v-for="entry in entries" :key="entry.date" class="card">
      <text class="eyebrow">{{ entry.date }}</text>
      <text class="body">{{ bookTitle(entry.bookId) }}</text>
    </view>
    <view v-if="!entries.length" class="empty">足迹还没开始。读完几页，回来告诉小书友就好。</view>
  </view>
</template>
