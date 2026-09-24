import { AppShell, Container, Group, Text, Title } from '@mantine/core'

import { useWorkspace } from './store'
import { UploadPane } from './components/UploadPane'
import { WorkspaceView } from './components/WorkspaceView'

export default function App() {
  const hasDocuments = useWorkspace((s) => s.documents.length > 0)
  const addDocument = useWorkspace((s) => s.addDocument)

  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        <Container fluid h="100%" px="md">
          <Group h="100%" justify="space-between">
            <Title order={4}>Спецификация → КП</Title>
            <Text size="sm" c="dimmed" visibleFrom="md">
              Разбор тома ТХ, свод позиций, цены, выгрузка в Excel по форме приложения к договору
            </Text>
          </Group>
        </Container>
      </AppShell.Header>
      <AppShell.Main>
        <Container fluid px="md">{hasDocuments ? <WorkspaceView /> : <UploadPane onParsed={addDocument} />}</Container>
      </AppShell.Main>
    </AppShell>
  )
}
