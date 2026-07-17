import { computed, ref } from 'vue'
import { defineStore } from 'pinia'

import { getAIOpsBusinessContextOptions } from '@/api/modules/aiops'

const STORAGE_KEY = 'xing-cloud-business-context-id'

function listOf(response) {
  if (Array.isArray(response)) return response
  return response?.results || []
}

export const useBusinessContextStore = defineStore('business-context', () => {
  const contexts = ref([])
  const currentContextId = ref('')
  const loading = ref(false)
  const loaded = ref(false)

  const currentContext = computed(() => (
    contexts.value.find(item => String(item.id) === String(currentContextId.value)) || null
  ))

  function preferredContextId(items) {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (saved && items.some(item => String(item.id) === saved)) return saved
    const preferred = items.find(item => item.is_default) || items[0]
    return preferred ? String(preferred.id) : ''
  }

  function selectContext(value) {
    const id = String(value || '')
    currentContextId.value = contexts.value.some(item => String(item.id) === id) ? id : ''
    if (currentContextId.value) window.localStorage.setItem(STORAGE_KEY, currentContextId.value)
    else window.localStorage.removeItem(STORAGE_KEY)
  }

  async function loadContexts({ force = false } = {}) {
    if (loaded.value && !force) return contexts.value
    loading.value = true
    try {
      const response = await getAIOpsBusinessContextOptions()
      contexts.value = listOf(response).filter(item => item.is_enabled !== false)
      const selected = contexts.value.some(item => String(item.id) === String(currentContextId.value))
        ? String(currentContextId.value)
        : preferredContextId(contexts.value)
      selectContext(selected)
      loaded.value = true
      return contexts.value
    } finally {
      loading.value = false
    }
  }

  function reset() {
    contexts.value = []
    currentContextId.value = ''
    loaded.value = false
  }

  return {
    contexts,
    currentContextId,
    currentContext,
    loading,
    loaded,
    loadContexts,
    selectContext,
    reset,
  }
})
