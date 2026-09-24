import '@mantine/core/styles.css'
import '@mantine/dropzone/styles.css'
import '@mantine/notifications/styles.css'

import { MantineProvider } from '@mantine/core'
import { Notifications } from '@mantine/notifications'
import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import App from './App'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <MantineProvider defaultColorScheme="light">
      <Notifications position="top-right" />
      <App />
    </MantineProvider>
  </StrictMode>,
)
