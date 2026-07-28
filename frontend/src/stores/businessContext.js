import { ref } from 'vue'
import { defineStore } from 'pinia'

import { getAIOpsBusinessContextOptions } from '@/api/modules/aiops'

function listOf(response) {
  if (Array.isArray(response)) return response
  return response?.results || []
}

export const useBusinessContextStore = defineStore('business-context', () => {
  const contexts = ref([])
  const loading = ref(false)
  const loaded = ref(false)

  async function loadContexts({ force = false } = {}) {
    if (loaded.value && !force) return contexts.value
    loading.value = true
    try {
      const response = await getAIOpsBusinessContextOptions()
      contexts.value = listOf(response).filter(item => item.is_enabled !== false)
      loaded.value = true
      return contexts.value
    } finally {
      loading.value = false
    }
  }

  function reset() {
    contexts.value = []
    loaded.value = false
  }

  return {
    contexts,
    loading,
    loaded,
    loadContexts,
    reset,
  }
})
