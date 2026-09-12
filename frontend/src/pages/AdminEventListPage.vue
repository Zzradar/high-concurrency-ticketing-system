<script setup lang="ts">
import {onMounted,ref} from 'vue'
import AdminNav from '../components/admin/AdminNav.vue'
import {adminApi,type AdminEventSummary} from '../api/adminApi'
const events=ref<AdminEventSummary[]>([]),error=ref('')
onMounted(async()=>{try{events.value=await adminApi.events()}catch(e){error.value=String(e)}})
</script>
<template><main class="admin-page"><AdminNav/><div class="admin-actions"><h2>活动</h2><RouterLink class="admin-button primary" to="/admin/events/new">新建活动</RouterLink></div><p v-if="error" role="alert" class="admin-alert">{{error}}</p><section class="admin-panel"><table class="admin-table"><thead><tr><th>活动名称</th><th>场馆</th><th>场次</th><th>状态</th></tr></thead><tbody><tr v-for="e in events" :key="e.id"><td><RouterLink :to="'/admin/events/'+e.id">{{e.name}}</RouterLink></td><td>{{e.venueName}}</td><td>{{e.sessionCount}}</td><td><span class="admin-badge">{{e.status==='DRAFT'?'草稿':'已发布'}}</span></td></tr></tbody></table></section></main></template>
