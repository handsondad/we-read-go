<script setup lang="ts">
import { computed, ref } from 'vue'
import { state, syncReading, readToday } from '../../store'
import { daysSince } from '../../core/model'
import { notifyError, openReading } from '../../platform'

const query = ref('')
const books = computed(() => state.data.books.filter((book) =>
  `${book.title} ${book.author}`.includes(query.value.trim())))
const labels = { want: '想读', reading: '在读', finished: '读完' }
const lastSync = computed(() => state.data.lastSyncAt
  ? new Date(state.data.lastSyncAt).toLocaleString() : '还没有同步')
async function sync() {
  try { await syncReading() } catch (error) { notifyError(error) }
}
function record(id: string) {
  try {
    readToday(id)
    uni.showToast({ title: '今天的阅读已记录', icon: 'none' })
  } catch (error) { notifyError(error) }
}
</script>

<template>
  <view class="page">
    <text class="eyebrow">BOOKS THAT WAIT FOR YOU</text>
    <text class="heading">下一页，随时都在。</text>
    <text class="intro">同步电子书与阅读进度，或在「想读」里手动加书。</text>
    <view class="card">
      <text class="small">上次成功同步：{{ lastSync }}</text>
      <text class="small">本机共保留 {{ state.data.books.length }} 本；可能包含旧书架条目，不代表远端书架总数。</text>
      <button class="primary" :loading="state.busy" :disabled="state.busy" @click="sync">直连微信读书同步</button>
      <text v-if="state.syncMessage" class="small sync-message" aria-live="polite">{{ state.syncMessage }}</text>
    </view>
    <input v-model="query" class="input" placeholder="搜索书名或作者" maxlength="80" />
    <view v-for="book in books" :key="book.id" class="card">
      <view class="row">
        <image v-if="book.cover" class="book-cover" :src="book.cover" mode="aspectFill" />
        <view v-else class="book-cover cover-placeholder">书</view>
        <view class="stack">
          <text class="title">{{ book.title }}</text>
          <text class="muted">{{ book.author || '作者暂未填写' }}</text>
          <text class="tag">{{ labels[book.status] }} · {{ book.source === 'weread' ? '微信读书' : '本地书目' }}</text>
          <text class="small">{{ book.progress === null ? '进度暂未知晓' : '读到 ' + book.progress + '%' }}</text>
        </view>
      </view>
      <text v-if="book.lastReadAt" class="small">
        上次阅读：{{ book.lastReadAt }}
        {{ (daysSince(book.lastReadAt) ?? 0) >= 7 && book.status !== 'finished' ? ' · 想回来时，从一页开始就好。' : '' }}
      </text>
      <button class="secondary" @click="openReading(book)">打开阅读</button>
      <button class="secondary" @click="record(book.id)">今天读过这本</button>
    </view>
    <view v-if="!books.length" class="empty">{{ query ? '没有找到这本书，换个关键词看看。' : '还没有书。可以连接微信读书，也可以从本地书单开始。' }}</view>
  </view>
</template>
