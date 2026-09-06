<script setup lang="ts">
import { RouterLink } from 'vue-router'
import { authState } from '../auth/authState'
import { routeNames } from '../navigation'
</script>

<template>
  <main class="page-shell page-state-page">
    <section class="page-state" aria-labelledby="not-found-title">
      <p class="eyebrow">404 · NOT FOUND</p>
      <h1 id="not-found-title">页面不存在</h1>
      <p>这个地址没有对应的票务页面，请检查链接或返回活动列表。</p>
      <div class="page-state__actions">
        <RouterLink class="primary-button" :to="{ name: routeNames.events }">返回活动</RouterLink>
        <RouterLink v-if="authState.currentUser.value" class="secondary-button" :to="{ name: routeNames.orders }">我的订单</RouterLink>
      </div>
    </section>
  </main>
</template>
