<script setup lang="ts">
import { ref } from 'vue'
import { state, connect, disconnect, syncReading, setReminder, exportBackup, restoreBackup } from '../../store'
import { notifyError } from '../../platform'

const key = ref('')
const backup = ref('')
const backupVisible = ref(false)

async function saveAndSync() {
  try {
    connect(key.value)
    key.value = ''
    await syncReading()
    uni.showModal({
      title: '同步完成', content: state.syncMessage, showCancel: false
    })
  } catch (error) { notifyError(error) }
}
function forget() {
  try { disconnect(); key.value = '' } catch (error) { notifyError(error) }
}
function reminder(enabled: boolean, time: string) {
  try { setReminder(enabled, time) } catch (error) { notifyError(error) }
}
function showBackup() {
  try {
    backup.value = exportBackup()
    backupVisible.value = true
  } catch (error) { notifyError(error) }
}
function copyBackup() {
  uni.setClipboardData({
    data: backup.value,
    fail: () => notifyError(new Error('无法复制，请手动选择备份文本。'))
  })
}
function restore() {
  uni.showModal({
    title: '用备份替换本机阅读数据？',
    content: '将覆盖本机书单、足迹和提醒设置；先保存当前备份。API Key 不在备份中。',
    success: ({ confirm }) => {
      if (!confirm) return
      try {
        restoreBackup(backup.value)
        backupVisible.value = false
        backup.value = ''
        uni.showToast({ title: '已恢复本地备份', icon: 'none' })
      } catch (error) { notifyError(error) }
    }
  })
}
</script>

<template>
  <view class="page">
    <text class="eyebrow">PRIVATE BY DEFAULT</text>
    <text class="heading">一个住在本机的伙伴。</text>
    <text class="intro">没有我们的账号和服务器，不上传到社区，不接入大模型。</text>
    <view v-if="state.storageError" class="card">
      <text class="body error">{{ state.storageError }}</text>
      <text class="small">请先保留原始本地存储。可用有效备份显式恢复；应用不会自动清空损坏的数据。</text>
    </view>
    <view class="card">
      <text class="title">连接微信读书</text>
      <text class="tag">{{ state.connected ? '本次会话已设置 Key' : '未设置 Key，可离线使用' }}</text>
      <text class="small">到 weread.qq.com/r/weread-skills 登录获取自己的 API Key。它与微信小程序 AppID 无关。</text>
      <input v-model="key" class="input" password placeholder="wrk- 开头的官方 API Key" maxlength="500" :disabled="state.busy" />
      <text class="small">当前版本只在内存保留 Key，重新启动需再输入。未验证设备安全存储前，不落盘、不进备份。</text>
      <button class="primary" :loading="state.busy" :disabled="state.busy" @click="saveAndSync">设置 Key 并同步</button>
      <button v-if="state.connected" class="secondary" :disabled="state.busy" @click="forget">从内存清除 Key</button>
      <text v-if="state.syncMessage" class="small sync-message" aria-live="polite">{{ state.syncMessage }}</text>
      <text class="small">只向微信读书官方网关发起查询。H5 直连可能被浏览器跨域策略阻止，不使用第三方代理绕过。</text>
    </view>
    <view class="card">
      <text class="title">温柔的应用内提醒</text>
      <view class="row">
        <text class="body">打开应用时提醒我</text>
        <switch :checked="state.data.reminder.enabled" color="#836345"
          @change="reminder(!state.data.reminder.enabled, state.data.reminder.time)" />
      </view>
      <picker mode="time" :value="state.data.reminder.time"
        @change="reminder(state.data.reminder.enabled, $event.detail.value)">
        <view class="input">轻轻提醒的时间：{{ state.data.reminder.time }}</view>
      </picker>
      <text class="small">目前只在应用前台或重新打开时检查，每天最多一次，今日已记录则不提醒。关闭 App 后不会通知；原生系统通知仍待接入和真机验证。</text>
    </view>
    <view class="card">
      <text class="title">数据只在这台设备</text>
      <text class="small">卸载/清理应用数据会丢失记录。备份包含书名与阅读日期，请当作个人数据妥善保管；图片封面会从原始地址加载。</text>
      <button class="secondary" @click="showBackup">生成不含 Key 的本地备份</button>
      <button class="secondary" @click="backupVisible = true">粘贴备份恢复</button>
      <view v-if="backupVisible">
        <textarea v-model="backup" class="textarea" placeholder="备份 JSON，可选择复制或粘贴恢复" maxlength="-1" />
        <button class="secondary" :disabled="!backup" @click="copyBackup">复制当前备份文本</button>
        <button class="danger" :disabled="!backup || state.busy" @click="restore">校验并恢复这份备份</button>
      </view>
    </view>
    <text class="small">0.1 · 本地优先验证版。旧版小程序和 Python 服务保留，但本应用不依赖它们。</text>
  </view>
</template>
