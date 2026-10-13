import { AppShell, Button, Container, Group, Modal, Text, Title, Stack, LoadingOverlay, Box, Divider } from '@mantine/core'
import { useState } from 'react'
import { UploadedDocuments } from './components/UploadedDocuments'
import { QuotationHistory } from './components/QuotationHistory'
import { IconBuildingStore } from '@tabler/icons-react'

import { SuppliersPanel } from './components/SuppliersPanel'
import { UploadPane } from './components/UploadPane'
import { WorkspaceView } from './components/WorkspaceView'
import { useWorkspace } from './store'
import { useUi } from './ui'
import { useCloud } from './projects'
import { CloudStatus } from './components/CloudStatus'
import { Projects } from './components/Projects'

export default function App() {
  const [projectsOpen, setProjectsOpen] = useState(false)
  const busy = useCloud((s) => s.busy)
  const projectId = useWorkspace((s) => s.projectId)
  const [documentsOpen, setDocumentsOpen] = useState(false)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [workspaceKey, setWorkspaceKey] = useState(0)
  const hasDocuments = useWorkspace((s) => s.documents.length > 0 || s.cloud.revision > 0)
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
              <Button variant="light" size="xs" onClick={() => setProjectsOpen(true)}>Объекты</Button>
              <Button variant="light" size="xs" onClick={() => setDocumentsOpen(true)}>Документы</Button>
              <Button variant="light" size="xs" onClick={() => setHistoryOpen(true)}>История КП</Button>
              <Button variant="default" size="xs" leftSection={<IconBuildingStore size={16} />} onClick={openSuppliers}>
                Поставщики
              </Button>
            </Group>
          </Group>
        </Container>
      </AppShell.Header>
      <AppShell.Main>
        <Container fluid px="md">
          <CloudStatus />
          <Box pos="relative" mih={160}>
            <LoadingOverlay visible={busy} />
            {!busy && (hasDocuments ? <WorkspaceView key={`${projectId}-${workspaceKey}`} /> : <Stack gap="xl">
              <Projects onOpened={() => setWorkspaceKey((n) => n + 1)} />
              <Divider label="Загрузить спецификацию для нового объекта" />
              <UploadPane onParsed={addDocument} />
            </Stack>)}
          </Box>
        </Container>
      </AppShell.Main>
      <Modal opened={projectsOpen} onClose={() => setProjectsOpen(false)} title="Рабочие объекты" size="90%" transitionProps={{ duration: 0 }}>
        {projectsOpen && <Projects onOpened={() => { setWorkspaceKey((n) => n + 1); setProjectsOpen(false) }} />}
      </Modal>
      <Modal opened={documentsOpen} onClose={() => setDocumentsOpen(false)} title="Загруженные документы" size="90%" transitionProps={{ duration: 0 }}>
        {documentsOpen && <UploadedDocuments onOpened={() => { setWorkspaceKey((n) => n + 1); setDocumentsOpen(false) }} />}
      </Modal>
      <Modal opened={historyOpen} onClose={() => setHistoryOpen(false)} title="История коммерческих предложений" size="90%" transitionProps={{ duration: 0 }}>
        {historyOpen && <QuotationHistory onOpened={() => { setWorkspaceKey((n) => n + 1); setHistoryOpen(false) }} />}
      </Modal>
      <Modal opened={suppliersOpen} onClose={closeSuppliers} title="Поставщики и их цены" size="90%" transitionProps={{ duration: 0 }}>
        <SuppliersPanel />
      </Modal>
    </AppShell>
  )
}
