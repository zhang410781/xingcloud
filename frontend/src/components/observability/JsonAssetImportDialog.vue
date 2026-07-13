<template>
  <el-dialog v-model="visible" title="导入 JSON" width="720px" destroy-on-close>
    <el-input
      v-model="jsonText"
      type="textarea"
      :rows="15"
      resize="none"
      spellcheck="false"
      placeholder='{"title":"Redis Overview","panels":[...]}'
    />
    <template #footer>
      <el-button @click="visible = false">取消</el-button>
      <el-button type="primary" @click="submit">导入</el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref } from 'vue'
import { ElMessage } from 'element-plus'

const visible = defineModel({ type: Boolean, default: false })
const emit = defineEmits(['submit'])
const jsonText = ref('')

function submit() {
  try {
    const payload = JSON.parse(jsonText.value)
    emit('submit', payload)
    jsonText.value = ''
    visible.value = false
  } catch {
    ElMessage.error('JSON 格式不正确')
  }
}
</script>
