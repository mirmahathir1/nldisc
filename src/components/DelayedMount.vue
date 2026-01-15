<script setup>
import { computed, onBeforeUnmount, ref, watch } from 'vue'

const props = defineProps({
  // When true, we will eventually render the slot after the delay.
  active: { type: Boolean, default: false },
  // Milliseconds to wait before mounting slot.
  durationMs: { type: Number, default: 3000 },
  // Optional: change this value to retrigger the delay while active stays true.
  trigger: { type: [Number, String], default: 0 },
  // Cosmetic props for the progress bar.
  color: { type: String, default: 'primary' },
  height: { type: [Number, String], default: 6 },
})

const progress = ref(0)
const ready = ref(false)
let timer = null

const showProgress = computed(() => Boolean(props.active && !ready.value))

function reset() {
  ready.value = false
  progress.value = 0
  if (timer) clearInterval(timer)
  timer = null
}

function start() {
  reset()
  const startedAt = Date.now()
  const tickMs = 50

  timer = setInterval(() => {
    const dur = Math.max(0, Number(props.durationMs) || 0)
    if (dur <= 0) {
      progress.value = 100
      ready.value = true
      resetTimerOnly()
      return
    }
    const t = Math.min(1, (Date.now() - startedAt) / dur)
    progress.value = Math.round(t * 100)
    if (t >= 1) {
      ready.value = true
      resetTimerOnly()
    }
  }, tickMs)
}

function resetTimerOnly() {
  if (timer) clearInterval(timer)
  timer = null
}

watch(
  () => [props.active, props.trigger],
  ([active]) => {
    if (!active) {
      reset()
      return
    }
    start()
  },
  { immediate: true },
)

onBeforeUnmount(() => {
  reset()
})
</script>

<template>
  <div v-if="active">
    <v-progress-linear
      v-if="showProgress"
      class="my-2"
      :color="color"
      :model-value="progress"
      :height="height"
      rounded
    />
    <v-fade-transition v-else>
      <div>
        <slot />
      </div>
    </v-fade-transition>
  </div>
</template>

