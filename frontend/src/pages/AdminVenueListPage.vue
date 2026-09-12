<script setup lang="ts">
import {onMounted,ref} from 'vue'
import AdminNav from '../components/admin/AdminNav.vue'
import {adminApi,type AdminVenueSummary} from '../api/adminApi'
const venues=ref<AdminVenueSummary[]>([]),error=ref('')
onMounted(async()=>{try{venues.value=await adminApi.venues()}catch(e){error.value=String(e)}})
</script>
<template><main class="admin-page"><AdminNav/><div class="admin-actions"><h2>场馆座位方案</h2><RouterLink class="admin-button primary" to="/admin/venues/new">新建场馆</RouterLink></div><p v-if="error" role="alert" class="admin-alert">{{error}}</p><section class="admin-panel"><p v-if="!venues.length">暂无场馆，创建你的第一个座位方案。</p><table v-else class="admin-table"><thead><tr><th>场馆</th><th>城市</th><th>区域 / 座位</th><th>状态</th></tr></thead><tbody><tr v-for="v in venues" :key="v.id"><td><RouterLink :to="'/admin/venues/'+v.id">{{v.name}}</RouterLink></td><td>{{v.city}}</td><td>{{v.zoneCount}} 区 / {{v.totalSeats.toLocaleString()}} 席</td><td>{{v.frozen?'已冻结':'可编辑'}}</td></tr></tbody></table></section></main></template>
