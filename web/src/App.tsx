import { AppShell, Container, Group, Text, Title } from '@mantine/core'
import { useState } from 'react'

import type { ParsedDocument } from './api'
import { ResultView } from './components/ResultView'
import { UploadPane } from './components/UploadPane'

export default function App() {
  const [doc, setDoc] = useState<ParsedDocument | null>(null)

  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        <Container size="xl" h="100%">
          <Group h="100%" justify="space-between">
            <Title order={4}>Спецификация → Excel</Title>
            <Text size="sm" c="dimmed">
              Этап 1: разбор PDF раздела ТХ и выгрузка в форму КП
            </Text>
          </Group>
        </Container>
      </AppShell.Header>
      <AppShell.Main>
        <Container size="xl">
          {doc ? <ResultView doc={doc} onReset={() => setDoc(null)} /> : <UploadPane onParsed={setDoc} />}
        </Container>
      </AppShell.Main>
    </AppShell>
  )
}
