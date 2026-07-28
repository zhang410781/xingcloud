import { computed, ref, watch } from 'vue'
import { storeToRefs } from 'pinia'
import { useBusinessContextStore } from '@/stores/businessContext'

const STORAGE_PREFIX = 'xing-cloud-feature-context:'

export function useFeatureBusinessContext(scope, { autoLoad = true } = {}) {
  const store = useBusinessContextStore()
  const { contexts, loading, loaded } = storeToRefs(store)
  const selectedContextId = ref('')
  const storageKey = `${STORAGE_PREFIX}${scope}`

  function preferredContextId(items = contexts.value) {
    const saved = window.localStorage.getItem(storageKey)
    if (saved && items.some(item => String(item.id) === String(saved))) return String(saved)
    const preferred = items.find(item => item.is_default) || items[0]
    return preferred ? String(preferred.id) : ''
  }

  function selectContext(value) {
    const id = String(value || '')
    selectedContextId.value = contexts.value.some(item => String(item.id) === id) ? id : ''
    if (selectedContextId.value) window.localStorage.setItem(storageKey, selectedContextId.value)
    else window.localStorage.removeItem(storageKey)
  }

  async function loadContexts(options = {}) {
    const items = await store.loadContexts(options)
    if (!selectedContextId.value || !items.some(item => String(item.id) === String(selectedContextId.value))) {
      selectContext(preferredContextId(items))
    }
    return items
  }

  const currentContext = computed(() => (
    contexts.value.find(item => String(item.id) === String(selectedContextId.value)) || null
  ))

  watch(contexts, (items) => {
    if (!items.some(item => String(item.id) === String(selectedContextId.value))) {
      selectContext(preferredContextId(items))
    }
  })

  watch(selectedContextId, (value) => {
    const id = String(value || '')
    if (id) window.localStorage.setItem(storageKey, id)
    else window.localStorage.removeItem(storageKey)
  })

  if (autoLoad) void loadContexts()

  return {
    contexts,
    loading,
    loaded,
    currentContextId: selectedContextId,
    currentContext,
    selectContext,
    loadContexts,
  }
}
