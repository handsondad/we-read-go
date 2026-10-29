<script setup lang="ts">
import { onHide, onShow } from '@dcloudio/uni-app'
import { pause, resume } from './store'

onShow(resume)
onHide(pause)
</script>

<style>
page {
  background: #faf6ef;
  color: #473b30;
  font-family: -apple-system, "PingFang SC", sans-serif;
}
.page { max-width: 760px; margin: auto; padding: 32rpx 28rpx 64rpx; box-sizing: border-box; }
.eyebrow { color: #9a8064; font-size: 23rpx; letter-spacing: 3rpx; }
.heading { display: block; font-size: 44rpx; font-weight: 650; margin: 12rpx 0 16rpx; }
.intro, .muted { display: block; color: #8f8274; line-height: 1.7; font-size: 25rpx; }
.card { background: #fffdf9; border: 1rpx solid #eee6d9; padding: 30rpx; border-radius: 26rpx; margin: 24rpx 0; }
.title { display: block; font-size: 31rpx; font-weight: 600; margin-bottom: 12rpx; }
.body { display: block; font-size: 29rpx; line-height: 1.8; }
.small { display: block; font-size: 23rpx; line-height: 1.6; margin-top: 12rpx; color: #8f8274; }
.error { color: #a54337; }
.row { display: flex; align-items: center; justify-content: space-between; gap: 16rpx; }
.stack { flex: 1; min-width: 0; }
.primary, .secondary, .danger { font-size: 27rpx; margin: 20rpx 0 0; border-radius: 16rpx; }
.primary { color: #fffdf9; background: #836345; }
.secondary { color: #70573f; background: #f0e9dd; }
.danger { color: #a54337; background: #f8ece8; }
button::after { border: none; }
button[disabled] { opacity: .6; }
.input, .textarea { display: block; background: #f6f1e8; border: 1rpx solid #ebe2d5; border-radius: 12rpx; padding: 22rpx; font-size: 27rpx; margin: 16rpx 0; box-sizing: border-box; width: 100%; }
.textarea { height: 190rpx; }
.empty { text-align: center; padding: 50rpx 20rpx; color: #9b8c7c; font-size: 27rpx; line-height: 1.8; }
.tag { display: inline-block; font-size: 21rpx; color: #8b7051; background: #f4eddf; padding: 6rpx 14rpx; border-radius: 20rpx; }
.book-cover { width: 100rpx; height: 140rpx; border-radius: 8rpx; flex-shrink: 0; background: #f4eddf; }
.cover-placeholder { display: flex; align-items: center; justify-content: center; font-size: 44rpx; }
.sync-message { white-space: pre-wrap; }
/* #ifdef H5 */
.uni-tabbar__label { font-weight: 500; letter-spacing: 1px; }
/* #endif */
</style>
