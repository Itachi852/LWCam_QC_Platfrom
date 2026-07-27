<script setup lang="ts">
import { useAppLocale } from '@/i18n'

const { elementLocale } = useAppLocale()
</script>

<template>
  <el-config-provider :locale="elementLocale">
    <RouterView />
  </el-config-provider>
</template>

