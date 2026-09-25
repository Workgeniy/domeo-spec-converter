import { AppShell, Button, Container, Group, Modal, Text, Title } from '@mantine/core'
import { IconBuildingStore } from '@tabler/icons-react'

import { SuppliersPanel } from './components/SuppliersPanel'
import { UploadPane } from './components/UploadPane'
import { WorkspaceView } from './components/WorkspaceView'
import { useWorkspace } from './store'
import { useUi } from './ui'

export default function App() {
  const hasDocuments = useWorkspace((s) => s.documents.length > 0)
  const addDocument = useWorkspace((s) => s.addDocument)
  const suppliersOpen = useUi((s) => s.suppliersOpen)
  const openSuppliers = useUi((s) => s.openSuppliers)
  const closeSuppliers = useUi((s) => s.closeSuppliers)

  return (
    <AppShell header={{ height: 56 }} padding="md">
      <AppShell.Header>
        <Container fluid h="100%" px="md">
          <Group h="100%" justify="space-between">
            <Title order={4}>Спецификация → КП</Title>
            <Group gap="md">
              <Text size="sm" c="dimmed" visibleFrom="md">
                Разбор тома ТХ, свод позиций, цены, выгрузка в Excel по форме приложения к договору
              </Text>
              <Button variant="default" size="xs" leftSection={<IconBuildingStore size={16} />} onClick={openSuppliers}>
                Поставщики
              </Button>
            </Group>
          </Group>
        </Container>
      </AppShell.Header>
      <AppShell.Main>
        <Container fluid px="md">{hasDocuments ? <WorkspaceView /> : <UploadPane onParsed={addDocument} />}</Container>
      </AppShell.Main>
      <Modal opened={suppliersOpen} onClose={closeSuppliers} title="Поставщики и их цены" size="90%" transitionProps={{ duration: 0 }}>
        <SuppliersPanel />
      </Modal>
    </AppShell>
  )
}
