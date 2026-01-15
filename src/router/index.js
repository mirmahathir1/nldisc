import { createRouter, createWebHashHistory } from 'vue-router'

import OfflineStage from '../pages/OfflineStage.vue'
import OnlineStage from '../pages/OnlineStage.vue'

export default createRouter({
  history: createWebHashHistory(),
  routes: [
    { path: '/', name: 'offline', component: OfflineStage },
    { path: '/online', name: 'online', component: OnlineStage },
    { path: '/:pathMatch(.*)*', redirect: '/' },
  ],
})

