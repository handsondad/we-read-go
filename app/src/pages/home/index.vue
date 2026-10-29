<script setup lang="ts">
import { state, suggestion, todayDone, readToday } from '../../store'
import { notifyError, openReading } from '../../platform'

function record() {
  try { readToday(suggestion.value.book?.id ?? null) } catch (error) { notifyError(error) }
}
</script>

<template>
  <view class="page">
    <text class="eyebrow">YOUR QUIET READING CORNER</text>
    <text class="heading">慢慢读，我陪你。</text>
    <text class="intro">这里没有排行榜，也没有欠下的进度。</text>
    <view v-if="state.storageError" class="card">
      <text class="body error">{{ state.storageError }}</text>
      <text class="small">为保护已有数据，暂不写入。请到设置页查看恢复说明。</text>
    </view>
    <view class="card companion">
      <view class="pet-scene">
        <view class="pet-ear left"></view><view class="pet-ear right"></view>
        <view class="pet-face"><text class="pet-eyes">• ᴥ •</text></view>
        <view class="pet-book">小书友</view>
      </view>
      <text class="body greeting">{{ suggestion.message }}</text>
      <text class="small">{{ todayDone ? '每一次回来，都算数。' : '五分钟也好，一页也好。' }}</text>
      <button class="primary" @click="openReading(suggestion.book)">去微信读书，读几页</button>
    </view>
    <view v-if="suggestion.book" class="card">
      <text class="eyebrow">今天的小建议</text>
      <text class="title book-name">《{{ suggestion.book.title }}》</text>
      <text class="muted">{{ suggestion.book.author || '作者暂未填写' }}</text>
      <text class="small">{{ suggestion.reason }}</text>
      <text class="small">阅读进度：{{ suggestion.book.progress === null ? '暂未知晓' : suggestion.book.progress + '%' }}</text>
    </view>
    <view v-else class="card empty">书架还是空的。<br />去「想读」收藏一本心动的书，就可以开始。</view>
    <button class="secondary" :disabled="todayDone || !!state.storageError" @click="record">
      {{ todayDone ? '今天已记录，休息也很好' : '我今天读过了' }}
    </button>
    <text class="small">这是本机阅读记录，不会改动微信读书进度。没有读也不用补。</text>
    <text class="small">{{ state.data.lastSyncAt ? '书架来自上次同步，离线也能看。' : '还未同步微信读书，可以先用本地书单。' }}</text>
  </view>
</template>

<style scoped>
.companion { background: linear-gradient(145deg, #fff5e3, #f8ead2); text-align: center; padding-top: 40rpx; }
.pet-scene { position: relative; width: 210rpx; height: 190rpx; margin: 8rpx auto 28rpx; }
.pet-face { position: absolute; width: 156rpx; height: 128rpx; top: 28rpx; left: 27rpx; background: #d7ad79; border-radius: 45% 45% 48% 48%; display: flex; align-items: center; justify-content: center; }
.pet-ear { position: absolute; width: 60rpx; height: 70rpx; background: #d7ad79; top: 6rpx; border-radius: 8rpx 55rpx 4rpx 10rpx; }
.left { left: 26rpx; transform: rotate(-15deg); }
.right { right: 26rpx; transform: rotate(65deg); }
.pet-eyes { font-size: 41rpx; color: #5f4230; }
.pet-book { position: absolute; bottom: 3rpx; width: 190rpx; left: 10rpx; background: #7d8f78; border-radius: 6rpx 6rpx 16rpx 16rpx; color: #fffdf9; font-size: 25rpx; padding: 18rpx 0; border-bottom: 6rpx solid #e8dfc7; }
.greeting { font-size: 32rpx; }
.book-name { margin-top: 20rpx; }
</style>
