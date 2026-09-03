<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ticketApi, TicketApiError } from '../api/ticketApi'
import type { OrderStatus, TicketOrder } from '../types'
import { formatCny } from '../utils/money'

const router = useRouter()
const orders = ref<TicketOrder[]>([])
const status = ref<OrderStatus | ''>('')
const loading = ref(false)
const error = ref('')

async function load() {
  loading.value = true
  error.value = ''
  try {
    orders.value = await ticketApi.getOrders({ status: status.value || undefined, limit: 20 })
  } catch (cause) {
    error.value = cause instanceof TicketApiError ? cause.message : '订单加载失败。'
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <main class="page-shell">
    <section class="page-intro"><div><p class="eyebrow">MY ORDERS</p><h1>我的订单</h1><p>服务器保存的订单可在任意已登录客户端恢复。</p></div></section>
    <div class="section-heading"><select v-model="status" @change="load"><option value="">全部状态</option><option value="PENDING_PAYMENT">待支付</option><option value="PAID">已支付</option><option value="CANCELLED">已取消</option><option value="EXPIRED">已过期</option></select><span>最多显示 20 条</span></div>
    <p v-if="error" class="message-banner message-banner--error">{{ error }}</p>
    <p v-if="loading">正在加载订单…</p><p v-else-if="!orders.length">暂无订单</p>
    <section v-else class="session-list">
      <button v-for="order in orders" :key="order.id" class="session-card" type="button" @click="router.push(`/orders/${order.id}`)">
        <strong>{{ order.id }}</strong><span>{{ order.status }} · {{ formatCny(order.totalAmount) }}</span><small>{{ new Date(order.createdAt).toLocaleString('zh-CN') }}</small>
      </button>
    </section>
  </main>
</template>
