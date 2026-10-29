<script setup lang="ts">
import { computed, ref } from 'vue'
import { state, addBook, updateBook, removeBook } from '../../store'
import type { Book, ReadingStatus } from '../../core/model'
import { notifyError } from '../../platform'

const title = ref('')
const author = ref('')
const status = ref<ReadingStatus>('want')
const editing = ref<string | null>(null)
const note = ref('')
const tab = ref<ReadingStatus>('want')
const labels = { want: '想读', reading: '在读', finished: '读完' }
const statuses: ReadingStatus[] = ['want', 'reading', 'finished']
const books = computed(() => state.data.books.filter((book) => book.status === tab.value))

function save() {
  try {
    if (editing.value) updateBook(editing.value, status.value, note.value)
    else addBook(title.value, author.value, status.value)
    tab.value = status.value
    clear()
    uni.showToast({ title: '已保存在本机', icon: 'none' })
  } catch (error) { notifyError(error) }
}
function edit(book: Book) {
  editing.value = book.id
  title.value = book.title
  author.value = book.author
  status.value = book.status
  note.value = book.note
  uni.pageScrollTo({ scrollTop: 0, duration: 200 })
}
function clear() {
  editing.value = null
  title.value = ''
  author.value = ''
  note.value = ''
  status.value = 'want'
}
function remove(book: Book) {
  uni.showModal({
    title: '从本机移除这本书？',
    content: '不影响微信读书。若仍在远端书架，下次同步时会重新导入。',
    success: ({ confirm }) => {
      if (!confirm) return
      try {
        removeBook(book.id)
        if (editing.value === book.id) clear()
      } catch (error) { notifyError(error) }
    }
  })
}
</script>

<template>
  <view class="page">
    <text class="eyebrow">A LITTLE LIST OF CURIOSITY</text>
    <text class="heading">留住一点好奇。</text>
    <text class="intro">收藏不是任务，想放下的时候也可以。</text>
    <view class="card">
      <text class="title">{{ editing ? '这本书的本地记录' : '放一本想读的书' }}</text>
      <input v-model="title" class="input" placeholder="书名（必填）" :disabled="!!editing" maxlength="80" />
      <input v-model="author" class="input" placeholder="作者（选填）" :disabled="!!editing" maxlength="80" />
      <view class="row">
        <button v-for="item in statuses" :key="item" size="mini" :class="status === item ? 'selected' : 'chip'" @click="status = item">{{ labels[item] }}</button>
      </view>
      <textarea v-if="editing" v-model="note" class="textarea" placeholder="留一句感想，不必写成读后感。" maxlength="2000" />
      <button class="primary" @click="save">{{ editing ? '保存本地状态与感想' : '加入本地书单' }}</button>
      <button v-if="editing" class="secondary" @click="clear">取消编辑</button>
    </view>
    <view class="row tabs">
      <button v-for="item in statuses" :key="item" size="mini" :class="tab === item ? 'selected' : 'chip'" @click="tab = item">{{ labels[item] }}</button>
    </view>
    <text class="small">微信读书书目的状态可能被下次真实同步更新；手写感想会保留。</text>
    <view v-for="book in books" :key="book.id" class="card">
      <text class="title">{{ book.title }}</text>
      <text class="muted">{{ book.author }}</text>
      <text v-if="book.note" class="body">{{ book.note }}</text>
      <button class="secondary" @click="edit(book)">状态与感想</button>
      <button class="danger" @click="remove(book)">从本机移除</button>
    </view>
    <view v-if="!books.length" class="empty">这一格暂时空着，也很好。</view>
  </view>
</template>

<style scoped>
.chip, .selected { margin: 8rpx 0; font-size: 25rpx; flex: 1; background: #f0e9dd; color: #8f8274; }
.selected { background: #836345; color: #fff; }
.tabs { margin-top: 34rpx; }
</style>
