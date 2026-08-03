import { createApp } from 'vue'
import PrimeVue from 'primevue/config'
import Aura from '@primeuix/themes/aura'
import 'primeicons/primeicons.css'
import './style.css'
import './mobile.css'
import App from './App.vue'

createApp(App)
  .use(PrimeVue, {
    theme: {
      preset: Aura,
      options: { darkModeSelector: '.app-dark' },
    },
  })
  .mount('#app')

if ('serviceWorker' in navigator && import.meta.env.PROD) {
  window.addEventListener('load', () => navigator.serviceWorker.register('/sw.js'))
}
