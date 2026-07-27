<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, reactive, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import AppShell from '@/components/AppShell.vue'
import ImagePreviewViewer from '@/components/ImagePreviewViewer.vue'
import { qcApi } from '@/api'
import { usePreviewImage } from '@/composables/usePreviewImage'
import { translateValue } from '@/i18n'
import type { CropRect, EditableFolderMetadata, MetadataQcImage, MetadataQcTask, MetadataTemplateField } from '@/types'

const { t } = useI18n()
type QcScope = 'pending' | 'mine' | 'completed'

const route = useRoute()
const router = useRouter()
const active = ref<QcScope>('pending')
const loading = ref(false)
const detailLoading = ref(false)
const actionLoading = ref(false)
const metadataSaving = ref(false)
const luminanceLoading = ref(false)
const draftSaving = ref(false)
const draftDiscarding = ref(false)
const tasks = ref<MetadataQcTask[]>([])
const scopeTotals = reactive<Record<'pending' | 'mine' | 'completed', number | null>>({
  pending: null,
  mine: null,
  completed: null,
})
const current = ref<MetadataQcTask | null>(null)
const claimedTask = ref<MetadataQcTask | null>(null)
const image = ref<MetadataQcImage | null>(null)
const viewerVisible = ref(false)
const rejectDialogVisible = ref(false)
const metadataDialogVisible = ref(false)
const cropDialogVisible = ref(false)
const cropLoading = ref(false)
const cropImageEl = ref<HTMLImageElement | null>(null)
const replaceInputEl = ref<HTMLInputElement | null>(null)
const insertInputEl = ref<HTMLInputElement | null>(null)
const cropDragging = ref(false)
const cropStart = ref({ x: 0, y: 0 })
const cropSelection = reactive({ x: 0, y: 0, width: 0, height: 0 })
const showMoreImageTools = ref(false)
const rejectedImageIds = ref<number[]>([])
const rejectReasons = reactive<Record<number, string>>({})
const selectedImageIds = ref<number[]>([])
const separationMode = ref(false)
const metadataForm = reactive<EditableFolderMetadata>({})
const { previewSrc, previewLoading, previewError } = usePreviewImage(image)

const isReviewRoute = computed(() => route.name === 'qc-review')
const isWorkbenchRoute = computed(() => route.name === 'qc-my-tasks' || route.name === 'qc-review')
const isStandaloneQcRoute = computed(() => isWorkbenchRoute.value || route.name === 'qc-completed')
const showListChrome = computed(() => !isStandaloneQcRoute.value)

const currentImageIndex = computed(() => {
  if (!current.value || !image.value) return 0
  return current.value.images.findIndex((item) => item.id === image.value?.id) + 1
})

const currentRejectReason = computed({
  get() {
    if (!image.value) return ''
    return rejectReasons[image.value.id] || ''
  },
  set(value: string) {
    if (!image.value) return
    const imageId = image.value.id
    if (value.trim() && !rejectedImageIds.value.includes(imageId)) {
      rejectedImageIds.value = [...rejectedImageIds.value, imageId]
    } else if (!value.trim()) {
      rejectedImageIds.value = rejectedImageIds.value.filter((id) => id !== imageId)
    }
    rejectReasons[imageId] = value
  },
})

const metadataGroups = computed(() => {
  const metadata = current.value?.metadata
  if (!metadata) return []
  return [
    {
      title: t('qc.fields.folderName'),
      fields: [
        [t('qc.fields.projectName'), metadata.projectName],
        [t('qc.fields.boxDetails'), metadata.boxName],
        [t('qc.fields.folderName'), metadata.folderName],
        [t('qc.fields.folderSeq'), metadata.folderSeq],
      ],
    },
    {
      title: t('qc.fields.title'),
      fields: [
        [t('qc.fields.title'), metadata.title],
        [t('qc.fields.volume'), metadata.volume],
        [t('qc.fields.archivalRefNo'), metadata.archivalRefNo],
        [t('qc.fields.coverTag'), metadata.coverTag],
        [t('qc.fields.imageTags'), metadata.imageTags],
        [t('qc.fields.startDate'), metadata.startDate],
        [t('qc.fields.endDate'), metadata.endDate],
      ],
    },
    {
      title: t('qc.fields.deviceId'),
      fields: [
        [t('qc.fields.deviceId'), metadata.deviceId],
        [t('qc.fields.scanningOpr'), metadata.captureOperatorName || metadata.captureOperatorId],
        [t('qc.fields.recordType'), metadata.recordType],
        [t('qc.fields.place'), metadata.place],
        [t('qc.fields.language'), metadata.language],
        [t('qc.fields.recordCustodian'), metadata.recordCustodian],
        [t('qc.fields.digitizingEntity'), metadata.digitizingEntity],
      ],
    },
  ]
})

const summaryItems = computed(() => [
  { label: t('qc.pending'), value: scopeTotals.pending ?? (active.value === 'pending' ? tasks.value.length : '-') },
  { label: t('qc.mine'), value: scopeTotals.mine ?? (active.value === 'mine' ? tasks.value.length : '-') },
  { label: t('qc.completed'), value: scopeTotals.completed ?? (active.value === 'completed' ? tasks.value.length : '-') },
])

const cropSelectionStyle = computed(() => ({
  left: `${Math.min(cropSelection.x, cropSelection.x + cropSelection.width)}px`,
  top: `${Math.min(cropSelection.y, cropSelection.y + cropSelection.height)}px`,
  width: `${Math.abs(cropSelection.width)}px`,
  height: `${Math.abs(cropSelection.height)}px`,
}))

const hasCropSelection = computed(() => Math.abs(cropSelection.width) >= 8 && Math.abs(cropSelection.height) >= 8)

const batchableImageIds = computed(() => current.value?.images.filter((item) => item.available).map((item) => item.id) || [])
const selectedBatchIds = computed(() => selectedImageIds.value.filter((id) => batchableImageIds.value.includes(id)))
const batchSelectionLabel = computed(() => `${selectedBatchIds.value.length} / ${batchableImageIds.value.length}`)
const separationMarkerIds = computed(() => current.value?.images.filter((item) => item.separationStart).map((item) => item.id) || [])

const requiredMetadataKeys: Array<keyof EditableFolderMetadata> = [
  'coverTag',
  'title',
  'volume',
  'startDate',
  'endDate',
  'archivalRefNo',
]

function fallbackRequiredField(key: keyof EditableFolderMetadata): MetadataTemplateField {
  const fieldLabelKeys: Partial<Record<keyof EditableFolderMetadata, string>> = {
    coverTag: 'coverTag',
    title: 'title',
    volume: 'volume',
    startDate: 'startDate',
    endDate: 'endDate',
    archivalRefNo: 'archivalRefNo',
  }
  return {
    key,
    label: t(`qc.fields.${fieldLabelKeys[key] || key}`),
    input: 'text',
    mandatory: true,
    exported: true,
    options: [],
  }
}

const editableTemplateFields = computed<MetadataTemplateField[]>(() =>
  requiredMetadataKeys.map((key) => {
    const templateField = current.value?.metadataTemplate.fields.find((field) => field.key === key)
    return templateField ? { ...templateField, mandatory: true } : fallbackRequiredField(key)
  }),
)

const metadataPayloadKeys: Array<keyof EditableFolderMetadata> = [
  'coverTag',
  'imageTags',
  'title',
  'volume',
  'startDate',
  'endDate',
  'archivalRefNo',
  'recordType',
  'place',
  'language',
  'recordCustodian',
  'captureOperatorId',
  'captureOperatorName',
  'digitizingEntity',
]

const metadataDirty = computed(() => {
  const metadata = current.value?.metadata
  if (!metadata) return false
  return metadataPayloadKeys.some((key) => normalizeMetadataValue(metadataForm[key]) !== normalizeMetadataValue(metadata[key]))
})

function applyTaskUpdate(task: MetadataQcTask, selectedImageId?: number | null) {
  const visibleImages = task.images.filter((item) => item.draftState !== 'deleted')
  const visibleTask = { ...task, images: visibleImages, imageCount: visibleImages.length }
  current.value = visibleTask
  claimedTask.value = visibleTask.status === 'reviewing' ? visibleTask : claimedTask.value
  const nextImageId = selectedImageId ?? image.value?.id
  image.value = visibleTask.images.find((item) => item.id === nextImageId) || visibleTask.images[0] || null
  selectedImageIds.value = selectedImageIds.value.filter((id) => visibleTask.images.some((item) => item.id === id))
  const listIndex = tasks.value.findIndex((item) => item.id === visibleTask.id)
  if (listIndex >= 0) tasks.value[listIndex] = visibleTask
}

function optionValue(field: MetadataTemplateField, option: string) {
  if ((field.key === 'startDate' || field.key === 'endDate') && /^\d{4}$/.test(option)) {
    return `${option}-01-01T00:00:00Z`
  }
  return option
}

function displayOption(option: string) {
  return option
}

function normalizeMetadataValue(value: unknown) {
  return value === null || value === undefined ? '' : String(value)
}

function titleRecordType(title: string | null | undefined) {
  if (!title || !current.value) return null
  return current.value.metadataTemplate.titleRecordTypeMap[title] || null
}

function syncDerivedMetadataFields() {
  if (!current.value) return
  for (const field of current.value.metadataTemplate.fields) {
    if (field.input === 'fixed') {
      ;(metadataForm as Record<string, string | null | undefined>)[field.key] = field.value ?? null
    }
  }
  metadataForm.recordType = titleRecordType(metadataForm.title) ?? null
}

function hasMetadataValue(value: unknown) {
  return value !== null && value !== undefined && String(value).trim() !== ''
}

function requiredMissingFromMetadata(metadata: Record<string, unknown>) {
  return editableTemplateFields.value.filter((field) => !hasMetadataValue(metadata[field.key]))
}

function requiredMissingFromForm() {
  return requiredMissingFromMetadata(metadataForm as unknown as Record<string, unknown>)
}

function validateCurrentBeforeApprove() {
  const task = current.value
  if (!task) return false
  const missing = requiredMissingFromMetadata(task.metadata as unknown as Record<string, unknown>)
  if (missing.length) {
    ElMessage.warning(`${t('qc.requiredMissing')}: ${missing.map((field) => field.label).join(', ')}`)
    return false
  }
  return true
}

async function loadScopeTotals() {
  const scopes: QcScope[] = ['pending', 'mine', 'completed']
  const results = await Promise.allSettled(
    scopes.map((scope) => qcApi.tasks({ scope, page: 1, size: 1 })),
  )
  results.forEach((result, index) => {
    if (result.status === 'fulfilled') {
      scopeTotals[scopes[index]] = result.value.data.data.total
    }
  })
}

function scopeFromRouteName(): QcScope {
  if (route.name === 'qc-my-tasks' || route.name === 'qc-review') return 'mine'
  if (route.name === 'qc-completed') return 'completed'
  return 'pending'
}

function reviewTaskId() {
  const id = Number(route.params.id)
  return Number.isFinite(id) ? id : null
}

function syncActiveFromRoute() {
  active.value = scopeFromRouteName()
}

function clearCurrentTask() {
  current.value = null
  claimedTask.value = null
  image.value = null
  selectedImageIds.value = []
}

async function releaseCurrent() {
  const task = claimedTask.value
  if (task?.status !== 'reviewing') return
  try {
    await qcApi.release(task.id)
  } catch {
    // The task may already be completed or released.
  }
  claimedTask.value = null
}

async function load() {
  loading.value = true
  try {
    if (isReviewRoute.value) {
      const taskId = reviewTaskId()
      if (!taskId) {
        clearCurrentTask()
        return
      }
      const { data } = await qcApi.detail(taskId)
      current.value = data.data
      claimedTask.value = data.data.status === 'reviewing' ? data.data : null
      image.value = data.data.images[0] || null
      selectedImageIds.value = []
      return
    }
    const { data } = await qcApi.tasks({ scope: active.value, page: 1, size: 100 })
    tasks.value = data.data.records
    scopeTotals[active.value] = data.data.total
    if (active.value === 'mine') {
      const mine = data.data.records[0]
      if (mine) {
        const detail = await qcApi.detail(mine.id)
        current.value = detail.data.data
        claimedTask.value = detail.data.data
        image.value = detail.data.data.images[0] || null
        selectedImageIds.value = []
      } else {
        current.value = null
        claimedTask.value = null
        image.value = null
        selectedImageIds.value = []
      }
    } else {
      clearCurrentTask()
    }
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

async function refreshPage() {
  await Promise.all([load(), loadScopeTotals()])
}

async function open(task: MetadataQcTask) {
  if (task.status === 'pending' && claimedTask.value && claimedTask.value.id !== task.id) {
    ElMessage.warning(t('qc.finishCurrentFirst'))
    return
  }
  detailLoading.value = true
  try {
    const response = task.status === 'pending' ? await qcApi.claim(task.id) : await qcApi.detail(task.id)
    current.value = response.data.data
    if (response.data.data.status === 'reviewing') claimedTask.value = response.data.data
    image.value = response.data.data.images[0] || null
    selectedImageIds.value = []
    if (task.status === 'pending') await router.push({ name: 'qc-review', params: { id: response.data.data.id } })
  } catch (error) {
    ElMessage.error((error as Error).message)
    await load()
  } finally {
    detailLoading.value = false
  }
}

async function claimNext() {
  detailLoading.value = true
  try {
    const { data } = await qcApi.claimNext()
    current.value = data.data
    claimedTask.value = data.data
    image.value = data.data.images[0] || null
    selectedImageIds.value = []
    active.value = 'mine'
    await router.push({ name: 'qc-review', params: { id: data.data.id } })
    return true
  } catch (error) {
    ElMessage.error((error as Error).message)
    return false
  } finally {
    detailLoading.value = false
  }
}

async function loadMineKeepingCurrent(task: MetadataQcTask) {
  const { data } = await qcApi.tasks({ scope: 'mine', page: 1, size: 100 })
  tasks.value = data.data.records
  scopeTotals.mine = data.data.total
  current.value = task
  claimedTask.value = task
  image.value = task.images[0] || null
  selectedImageIds.value = []
}

async function promptNextTaskOrClose() {
  try {
    await ElMessageBox.confirm(t('qc.nextTaskPrompt'), t('qc.title'), {
      type: 'success',
      confirmButtonText: t('qc.claimNext'),
      cancelButtonText: t('common.close'),
      distinguishCancelAndClose: false,
    })
    const claimed = await claimNext()
    if (!claimed) await router.push('/qc/my-tasks')
  } catch {
    await router.push('/qc/my-tasks')
  }
}

async function approve() {
  if (current.value?.status !== 'reviewing') return
  if (!validateCurrentBeforeApprove()) return
  await ElMessageBox.confirm(
    current.value.hasDraft ? t('qc.approveWithDraftConfirm') : t('qc.approveConfirm'),
    t('qc.title'),
    { type: 'info' },
  )
  actionLoading.value = true
  try {
    await qcApi.approve(current.value.id, current.value.sourceHash)
    ElMessage.success(t('qc.passed'))
    claimedTask.value = null
    await promptNextTaskOrClose()
  } catch (error) {
    await handleVersionOrActionError(error)
  } finally {
    actionLoading.value = false
  }
}

async function openRejectDialog() {
  if (current.value?.hasDraft) {
    try {
      await ElMessageBox.confirm(t('qc.discardDraftConfirm'), t('qc.title'), { type: 'warning' })
    } catch {
      return
    }
  }
  const imageIds = Object.keys(rejectReasons)
    .map(Number)
    .filter((imageId) => (rejectReasons[imageId] || '').trim())
  if (image.value && !imageIds.includes(image.value.id)) {
    imageIds.push(image.value.id)
  }
  rejectedImageIds.value = imageIds
  syncRejectReasons(imageIds)
  rejectDialogVisible.value = true
}

async function submitReject() {
  if (current.value?.status !== 'reviewing') return
  if (!rejectedImageIds.value.length) {
    ElMessage.warning(t('qc.rejectImagesRequired'))
    return
  }
  const rejectedImages = rejectedImageIds.value.map((imageId) => ({
    imageId,
    rejectReason: (rejectReasons[imageId] || '').trim(),
  }))
  const missingReason = rejectedImages.find((item) => !item.rejectReason)
  if (missingReason) {
    ElMessage.warning(t('qc.rejectReasonRequired'))
    return
  }
  actionLoading.value = true
  try {
    await qcApi.reject(
      current.value.id,
      current.value.sourceHash,
      rejectedImages,
    )
    rejectDialogVisible.value = false
    ElMessage.success(t('qc.rejected'))
    claimedTask.value = null
    await promptNextTaskOrClose()
  } catch (error) {
    rejectDialogVisible.value = false
    await handleVersionOrActionError(error)
  } finally {
    actionLoading.value = false
  }
}

function fillMetadataFormFromCurrent() {
  if (!current.value) return
  const metadata = current.value.metadata
  Object.assign(metadataForm, {
    coverTag: metadata.coverTag ?? null,
    imageTags: metadata.imageTags ?? null,
    title: metadata.title ?? null,
    volume: metadata.volume ?? null,
    startDate: metadata.startDate ?? null,
    endDate: metadata.endDate ?? null,
    archivalRefNo: metadata.archivalRefNo ?? null,
    recordType: metadata.recordType ?? null,
    place: metadata.place ?? null,
    language: metadata.language ?? null,
    recordCustodian: metadata.recordCustodian ?? null,
    captureOperatorId: metadata.captureOperatorId ?? null,
    captureOperatorName: metadata.captureOperatorName ?? null,
    digitizingEntity: metadata.digitizingEntity ?? null,
  })
  syncDerivedMetadataFields()
}

function openMetadataEditor() {
  fillMetadataFormFromCurrent()
  metadataDialogVisible.value = true
}

async function saveMetadata() {
  if (current.value?.status !== 'reviewing') return
  syncDerivedMetadataFields()
  const missing = requiredMissingFromForm()
  if (missing.length) {
    ElMessage.warning(`${t('qc.requiredMissing')}: ${missing.map((field) => field.label).join(', ')}`)
  }
  metadataSaving.value = true
  try {
    const selectedImageId = image.value?.id
    const metadataPayload: EditableFolderMetadata = {
      coverTag: metadataForm.coverTag ?? null,
      imageTags: metadataForm.imageTags ?? null,
      title: metadataForm.title ?? null,
      volume: metadataForm.volume ?? null,
      startDate: metadataForm.startDate ?? null,
      endDate: metadataForm.endDate ?? null,
      archivalRefNo: metadataForm.archivalRefNo ?? null,
      recordType: metadataForm.recordType ?? null,
      place: metadataForm.place ?? null,
      language: metadataForm.language ?? null,
      recordCustodian: metadataForm.recordCustodian ?? null,
      captureOperatorId: metadataForm.captureOperatorId ?? null,
      captureOperatorName: metadataForm.captureOperatorName ?? null,
      digitizingEntity: metadataForm.digitizingEntity ?? null,
    }
    const { data } = await qcApi.updateMetadata(
      current.value.id,
      current.value.sourceHash,
      metadataPayload,
    )
    current.value = data.data
    claimedTask.value = data.data
    const listIndex = tasks.value.findIndex((task) => task.id === data.data.id)
    if (listIndex >= 0) tasks.value[listIndex] = data.data
    image.value = data.data.images.find((item) => item.id === selectedImageId) || data.data.images[0] || null
    metadataDialogVisible.value = false
    ElMessage.success(t('qc.metadataSaved'))
  } catch (error) {
    metadataDialogVisible.value = false
    await handleVersionOrActionError(error)
  } finally {
    metadataSaving.value = false
  }
}

async function handleVersionOrActionError(error: unknown) {
  ElMessage.error((error as Error).message)
  clearCurrentTask()
  if (isReviewRoute.value) await router.push('/qc/my-tasks')
  else await load()
}

function openViewer() {
  if (previewSrc.value) viewerVisible.value = true
}

function resetCropSelection() {
  cropSelection.x = 0
  cropSelection.y = 0
  cropSelection.width = 0
  cropSelection.height = 0
}

function openCropDialog() {
  if (current.value?.status !== 'reviewing' || !image.value?.available || !previewSrc.value) return
  resetCropSelection()
  cropDialogVisible.value = true
}

function clampCropPoint(event: PointerEvent) {
  const element = cropImageEl.value
  if (!element) return { x: 0, y: 0 }
  const rect = element.getBoundingClientRect()
  return {
    x: Math.min(rect.width, Math.max(0, event.clientX - rect.left)),
    y: Math.min(rect.height, Math.max(0, event.clientY - rect.top)),
  }
}

function startCrop(event: PointerEvent) {
  event.preventDefault()
  const point = clampCropPoint(event)
  cropDragging.value = true
  cropStart.value = point
  cropSelection.x = point.x
  cropSelection.y = point.y
  cropSelection.width = 0
  cropSelection.height = 0
  window.addEventListener('pointermove', updateCrop)
  window.addEventListener('pointerup', stopCrop)
}

function updateCrop(event: PointerEvent) {
  if (!cropDragging.value) return
  const point = clampCropPoint(event)
  cropSelection.width = point.x - cropStart.value.x
  cropSelection.height = point.y - cropStart.value.y
}

function stopCrop() {
  cropDragging.value = false
  window.removeEventListener('pointermove', updateCrop)
  window.removeEventListener('pointerup', stopCrop)
}

function cropRectInNaturalPixels(): CropRect | null {
  const element = cropImageEl.value
  if (!element || !hasCropSelection.value) return null
  const rect = element.getBoundingClientRect()
  const left = Math.min(cropSelection.x, cropSelection.x + cropSelection.width)
  const top = Math.min(cropSelection.y, cropSelection.y + cropSelection.height)
  const width = Math.abs(cropSelection.width)
  const height = Math.abs(cropSelection.height)
  const scaleX = element.naturalWidth / rect.width
  const scaleY = element.naturalHeight / rect.height
  const x = Math.max(0, Math.min(element.naturalWidth - 1, Math.round(left * scaleX)))
  const y = Math.max(0, Math.min(element.naturalHeight - 1, Math.round(top * scaleY)))
  return {
    x,
    y,
    width: Math.max(1, Math.min(element.naturalWidth - x, Math.round(width * scaleX))),
    height: Math.max(1, Math.min(element.naturalHeight - y, Math.round(height * scaleY))),
    previewWidth: element.naturalWidth,
    previewHeight: element.naturalHeight,
  }
}

async function submitCrop() {
  if (current.value?.status !== 'reviewing' || !image.value) return
  const rect = cropRectInNaturalPixels()
  if (!rect) {
    ElMessage.warning(t('qc.cropAreaRequired'))
    return
  }
  cropLoading.value = true
  try {
    const selectedImageId = image.value.id
    const { data } = await qcApi.cropImage(
      current.value.id,
      selectedImageId,
      current.value.sourceHash,
      rect,
    )
    current.value = data.data
    claimedTask.value = data.data
    const listIndex = tasks.value.findIndex((task) => task.id === data.data.id)
    if (listIndex >= 0) tasks.value[listIndex] = data.data
    image.value = data.data.images.find((item) => item.id === selectedImageId) || data.data.images[0] || null
    cropDialogVisible.value = false
    ElMessage.success(t('qc.cropSaved'))
  } catch (error) {
    cropDialogVisible.value = false
    await handleVersionOrActionError(error)
  } finally {
    cropLoading.value = false
  }
}

function toggleImageSelection(imageId: number, checked: boolean) {
  if (!batchableImageIds.value.includes(imageId)) return
  if (checked && !selectedImageIds.value.includes(imageId)) {
    selectedImageIds.value = [...selectedImageIds.value, imageId]
  } else if (!checked) {
    selectedImageIds.value = selectedImageIds.value.filter((id) => id !== imageId)
  }
}

function selectAllBatchImages() {
  selectedImageIds.value = [...batchableImageIds.value]
}

function clearBatchSelection() {
  selectedImageIds.value = []
}

function syncRejectReasons(ids: number[]) {
  const nextIds = new Set(ids)
  Object.keys(rejectReasons).forEach((key) => {
    const imageId = Number(key)
    if (!nextIds.has(imageId)) delete rejectReasons[imageId]
  })
  ids.forEach((imageId) => {
    if (!(imageId in rejectReasons)) rejectReasons[imageId] = ''
  })
}

async function applyLuminanceToCurrent() {
  if (current.value?.status !== 'reviewing' || !image.value?.available) return
  luminanceLoading.value = true
  try {
    const selectedImageId = image.value.id
    const { data } = await qcApi.luminanceImage(current.value.id, selectedImageId, current.value.sourceHash)
    applyTaskUpdate(data.data, selectedImageId)
    ElMessage.success(t('qc.luminanceDone'))
  } catch (error) {
    await handleVersionOrActionError(error)
  } finally {
    luminanceLoading.value = false
  }
}

async function applyLuminanceBatch() {
  if (current.value?.status !== 'reviewing') return
  if (!selectedBatchIds.value.length) {
    ElMessage.warning(t('qc.selectBatchImages'))
    return
  }
  luminanceLoading.value = true
  try {
    const selectedImageId = image.value?.id
    const { data } = await qcApi.luminanceBatch(current.value.id, current.value.sourceHash, selectedBatchIds.value)
    applyTaskUpdate(data.data, selectedImageId)
    ElMessage.success(t('qc.batchLuminanceDone'))
  } catch (error) {
    await handleVersionOrActionError(error)
  } finally {
    luminanceLoading.value = false
  }
}

function isTifFile(file: File) {
  return /\.(tif|tiff)$/i.test(file.name)
}

function triggerReplaceUpload() {
  if (current.value?.status !== 'reviewing' || !image.value) return
  replaceInputEl.value?.click()
}

function triggerInsertUpload() {
  if (current.value?.status !== 'reviewing' || !image.value) return
  insertInputEl.value?.click()
}

async function handleReplaceUpload(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file || current.value?.status !== 'reviewing' || !image.value) return
  if (!isTifFile(file)) {
    ElMessage.warning(t('qc.tifOnly'))
    return
  }
  actionLoading.value = true
  try {
    const selectedImageId = image.value.id
    const { data } = await qcApi.replaceImage(current.value.id, selectedImageId, current.value.sourceHash, file)
    applyTaskUpdate(data.data, selectedImageId)
    ElMessage.success(t('qc.replaceDone'))
  } catch (error) {
    await handleVersionOrActionError(error)
  } finally {
    actionLoading.value = false
  }
}

async function handleInsertUpload(event: Event) {
  const target = event.target as HTMLInputElement
  const file = target.files?.[0]
  target.value = ''
  if (!file || current.value?.status !== 'reviewing' || !image.value) return
  if (!isTifFile(file)) {
    ElMessage.warning(t('qc.tifOnly'))
    return
  }
  actionLoading.value = true
  try {
    const selectedImageId = image.value.id
    const { data } = await qcApi.insertBeforeImage(current.value.id, selectedImageId, current.value.sourceHash, file)
    applyTaskUpdate(data.data, selectedImageId)
    ElMessage.success(t('qc.insertDone'))
  } catch (error) {
    await handleVersionOrActionError(error)
  } finally {
    actionLoading.value = false
  }
}

async function runImageAction(
  action: () => Promise<{ data: { data: MetadataQcTask } }>,
  selectedImageId = image.value?.id,
  successKey = 'qc.draftUnsaved',
) {
  if (current.value?.status !== 'reviewing') return
  actionLoading.value = true
  try {
    const { data } = await action()
    applyTaskUpdate(data.data, selectedImageId)
    ElMessage.success(t(successKey))
  } catch (error) {
    await handleVersionOrActionError(error)
  } finally {
    actionLoading.value = false
  }
}

async function deleteCurrentImage() {
  if (!current.value || !image.value) return
  try {
    await ElMessageBox.confirm(t('qc.deleteConfirm'), t('qc.title'), { type: 'warning' })
  } catch {
    return
  }
  const selectedImageId = image.value.id
  await runImageAction(async () => {
    const response = await qcApi.deleteImage(current.value!.id, selectedImageId, current.value!.sourceHash)
    const images = response.data.data.images.filter((item) => item.id !== selectedImageId && item.draftState !== 'deleted')
    response.data.data = { ...response.data.data, images, imageCount: images.length }
    return response
  }, null, 'qc.deleteDone')
}

async function rotateCurrent(degrees: number) {
  if (!current.value || !image.value) return
  const selectedImageId = image.value.id
  await runImageAction(
    () => qcApi.rotateImage(current.value!.id, selectedImageId, current.value!.sourceHash, degrees),
    selectedImageId,
    'qc.rotateDone',
  )
}

async function rotateSelectedBatch(degrees: number) {
  if (!current.value) return
  if (!selectedBatchIds.value.length) {
    ElMessage.warning(t('qc.selectBatchImages'))
    return
  }
  const selectedImageId = image.value?.id
  await runImageAction(
    () => qcApi.rotateBatch(current.value!.id, current.value!.sourceHash, selectedBatchIds.value, degrees),
    selectedImageId,
    'qc.rotateDone',
  )
}

async function deskewCurrent(degrees: number) {
  if (!current.value || !image.value) return
  const selectedImageId = image.value.id
  await runImageAction(
    () => qcApi.deskewImage(current.value!.id, selectedImageId, current.value!.sourceHash, degrees),
    selectedImageId,
    'qc.deskewDone',
  )
}

async function restoreCurrentImage() {
  if (!current.value || !image.value) return
  const selectedImageId = image.value.id
  await runImageAction(
    () => qcApi.restoreOriginal(current.value!.id, selectedImageId, current.value!.sourceHash),
    selectedImageId,
    'qc.restoreDone',
  )
}

async function undoDraftAction() {
  if (!current.value) return
  await runImageAction(() => qcApi.undoDraft(current.value!.id), image.value?.id, 'qc.undoDone')
}

async function redoDraftAction() {
  if (!current.value) return
  await runImageAction(() => qcApi.redoDraft(current.value!.id), image.value?.id, 'qc.redoDone')
}

async function moveCurrentImage(offset: -1 | 1) {
  if (!current.value || !image.value) return
  const ids = current.value.images.map((item) => item.id)
  const index = ids.indexOf(image.value.id)
  const nextIndex = index + offset
  if (index < 0 || nextIndex < 0 || nextIndex >= ids.length) return
  const nextIds = [...ids]
  const [moved] = nextIds.splice(index, 1)
  nextIds.splice(nextIndex, 0, moved)
  const selectedImageId = image.value.id
  await runImageAction(
    () => qcApi.reorderImages(current.value!.id, current.value!.sourceHash, nextIds),
    selectedImageId,
    'qc.reorderDone',
  )
}

async function toggleSeparationMarker(imageId: number) {
  if (!current.value || current.value.status !== 'reviewing') return
  const currentMarkers = new Set(separationMarkerIds.value)
  if (currentMarkers.has(imageId)) currentMarkers.delete(imageId)
  else currentMarkers.add(imageId)
  const firstId = current.value.images[0]?.id
  if (currentMarkers.size > 0 && firstId) currentMarkers.add(firstId)
  await runImageAction(
    () => qcApi.updateSeparationMarkers(current.value!.id, current.value!.sourceHash, [...currentMarkers]),
    image.value?.id,
    'qc.separationDone',
  )
}

async function saveDraft() {
  if (current.value?.status !== 'reviewing' || !current.value.hasDraft) return
  draftSaving.value = true
  try {
    const selectedImageId = image.value?.id
    const { data } = await qcApi.saveDraft(current.value.id, current.value.sourceHash)
    applyTaskUpdate(data.data, selectedImageId)
    ElMessage.success(t('qc.draftSaved'))
  } catch (error) {
    await handleVersionOrActionError(error)
  } finally {
    draftSaving.value = false
  }
}

async function discardDraft() {
  if (current.value?.status !== 'reviewing' || !current.value.hasDraft) return
  try {
    await ElMessageBox.confirm(t('qc.discardDraftConfirm'), t('qc.title'), { type: 'warning' })
  } catch {
    return
  }
  draftDiscarding.value = true
  try {
    const selectedImageId = image.value?.id
    const { data } = await qcApi.discardDraft(current.value.id)
    applyTaskUpdate(data.data, selectedImageId)
    ElMessage.success(t('qc.draftDiscarded'))
  } catch (error) {
    await handleVersionOrActionError(error)
  } finally {
    draftDiscarding.value = false
  }
}

async function closeCurrentTask() {
  if (current.value?.status !== 'reviewing') return
  if (current.value.hasDraft) {
    try {
      await ElMessageBox.confirm(t('qc.discardDraftConfirm'), t('qc.title'), { type: 'warning' })
    } catch {
      return
    }
  }
  actionLoading.value = true
  try {
    await qcApi.release(current.value.id)
    claimedTask.value = null
    current.value = null
    image.value = null
    selectedImageIds.value = []
    await router.push('/qc/tasks')
  } catch (error) {
    await handleVersionOrActionError(error)
  } finally {
    actionLoading.value = false
  }
}

async function returnToQcTasks() {
  clearCurrentTask()
  await router.push('/qc/tasks')
}

function displayValue(value: unknown) {
  return value === null || value === undefined || value === '' ? t('common.notFilled') : String(value)
}

function imageName(imageId: number) {
  return current.value?.images.find((item) => item.id === imageId)?.filename || `#${imageId}`
}

function completedTime(task: MetadataQcTask) {
  return task.reviewedAt || task.submittedAt || task.claimedAt
}

async function refreshForRoute() {
  syncActiveFromRoute()
  await Promise.all([load(), loadScopeTotals()])
}

watch(
  () => route.fullPath,
  () => {
    void refreshForRoute()
  },
)

watch(
  () => current.value?.id,
  () => {
    fillMetadataFormFromCurrent()
  },
)

onMounted(refreshForRoute)
onBeforeUnmount(() => {
  stopCrop()
  if (claimedTask.value?.status === 'reviewing') {
    void qcApi.release(claimedTask.value.id).catch(() => undefined)
  }
})
</script>

<template>
  <AppShell>
    <div v-if="showListChrome" class="qc-page-header">
      <div class="page-title qc-page-title">
        <div><h1>{{ t('qc.title') }}</h1><p>{{ t('qc.subtitle') }}</p></div>
        <div class="toolbar qc-toolbar">
          <el-button :icon="'Refresh'" @click="refreshPage">{{ t('common.refresh') }}</el-button>
        </div>
      </div>
      <div class="qc-summary-strip">
        <div v-for="item in summaryItems" :key="item.label" class="qc-summary-item">
          <span>{{ item.label }}</span>
          <strong>{{ item.value }}</strong>
        </div>
      </div>
    </div>

    <section v-if="active === 'pending'" v-loading="loading || detailLoading" class="panel pending-queue-panel">
      <div class="queue-heading">
        <div>
          <p class="eyebrow">{{ t('qc.pendingQueue') }}</p>
          <h2>{{ t('qc.pendingCount', { count: tasks.length }) }}</h2>
        </div>
        <el-alert v-if="claimedTask" type="info" :closable="false" :title="t('qc.activeTaskHint', { name: claimedTask.metadata.folderName })" show-icon />
      </div>
      <el-table :data="tasks" row-key="id" class="pending-task-table" empty-text="No pending tasks">
        <el-table-column prop="metadata.projectName" :label="t('qc.fields.projectName')" min-width="170" />
        <el-table-column prop="metadata.boxName" :label="t('qc.fields.boxDetails')" min-width="160" />
        <el-table-column prop="metadata.folderName" :label="t('qc.fields.folderName')" min-width="220" />
        <el-table-column prop="imageCount" :label="t('qc.images')" width="100" align="center" />
        <el-table-column :label="t('qc.sourceTime')" min-width="180">
          <template #default="{ row }">{{ displayValue(row.metadata.sourceCreatedAt) }}</template>
        </el-table-column>
        <el-table-column :label="t('common.actions')" width="130" fixed="right">
          <template #default="{ row }">
            <el-button type="primary" link :disabled="Boolean(claimedTask)" @click="open(row)">{{ t('qc.claim') }}</el-button>
          </template>
        </el-table-column>
      </el-table>
    </section>

    <div v-else-if="active === 'mine'" class="qc-desk" :class="{ 'qc-desk--compact': isWorkbenchRoute }">
      <template v-if="current">
        <header class="qc-desk-header">
          <el-button class="qc-back-button" :icon="'ArrowLeft'" :loading="actionLoading" @click="returnToQcTasks">
            {{ t('common.back') }}
          </el-button>
          <div class="qc-project-title">
            <strong>{{ current.metadata.folderName }}</strong>
            <span v-if="image">{{ image.filename }}</span>
          </div>
          <div v-if="current.status === 'reviewing'" class="qc-primary-actions">
            <el-button :icon="'Close'" :loading="actionLoading" @click="closeCurrentTask">
              {{ t('common.close') }}
            </el-button>
            <el-button type="danger" :icon="'Close'" :loading="actionLoading" @click="openRejectDialog">
              {{ t('qc.reject') }}
            </el-button>
            <el-button type="success" :icon="'Check'" :loading="actionLoading" :disabled="!current.imageAvailable" @click="approve">
              {{ t('qc.pass') }}
            </el-button>
          </div>
        </header>

        <aside v-loading="loading" class="qc-image-rail">
          <div class="qc-rail-summary">
            <div>
              <span>{{ t('qc.imageList') }}</span>
              <strong>{{ current.imageCount }} {{ t('qc.images') }}</strong>
            </div>
            <div v-if="current.status === 'reviewing'" class="qc-batch-tools">
              <span>{{ t('qc.batchSelected') }} {{ batchSelectionLabel }}</span>
              <div>
                <el-button size="small" link :disabled="!batchableImageIds.length" @click="selectAllBatchImages">
                  {{ t('qc.selectAllImages') }}
                </el-button>
                <el-button size="small" link :disabled="!selectedBatchIds.length" @click="clearBatchSelection">
                  {{ t('qc.clearImageSelection') }}
                </el-button>
              </div>
            </div>
          </div>

          <div class="qc-thumbnail-list">
            <button
              v-for="(item, index) in current.images"
              :key="item.id"
              type="button"
              class="qc-thumbnail"
              :class="{ active: image?.id === item.id, selected: selectedBatchIds.includes(item.id), unavailable: !item.available }"
              :title="item.filename"
              @click="image = item"
            >
              <el-checkbox
                v-if="current.status === 'reviewing'"
                class="qc-thumbnail-check"
                :model-value="selectedBatchIds.includes(item.id)"
                :disabled="!item.available"
                @click.stop
                @change="(checked: boolean) => toggleImageSelection(item.id, checked)"
              />
              <span class="qc-thumbnail-index">{{ String(index + 1).padStart(2, '0') }}</span>
              <span class="qc-thumbnail-preview">
                <el-icon v-if="!item.available"><WarningFilled /></el-icon>
                <el-icon v-else><Document /></el-icon>
              </span>
              <span class="qc-thumbnail-name">{{ item.filename }}</span>
              <span v-if="current.draftImageIds.includes(item.id)" class="qc-draft-flag">{{ t('qc.draftUnsaved') }}</span>
              <span v-if="item.draftState" class="qc-draft-state">{{ item.draftState }}</span>
              <el-button
                v-if="current.status === 'reviewing' && separationMode"
                class="qc-separation-dot"
                size="small"
                :type="item.separationStart ? 'warning' : 'default'"
                circle
                @click.stop="toggleSeparationMarker(item.id)"
              >
                S
              </el-button>
            </button>
          </div>
        </aside>

        <section v-loading="detailLoading || previewLoading" class="qc-preview-stage">
          <template v-if="image">
            <div class="qc-preview-canvas">
              <img v-if="previewSrc" class="qc-main-image" :src="previewSrc" :alt="image.filename" @click="openViewer" />
              <el-alert v-else-if="!image.available" type="error" :closable="false" :title="t('qc.imageMissing')" />
              <span v-else-if="previewError" class="error-message">{{ previewError }}</span>
            </div>
            <button
              v-if="currentImageIndex > 1"
              class="qc-nav-button qc-nav-button--prev"
              @click="image = current.images[currentImageIndex - 2]"
              :title="t('common.previous')"
            >
              <el-icon><ArrowLeft /></el-icon>
            </button>
            <button
              v-if="currentImageIndex < current.imageCount"
              class="qc-nav-button qc-nav-button--next"
              @click="image = current.images[currentImageIndex]"
              :title="t('common.next')"
            >
              <el-icon><ArrowRight /></el-icon>
            </button>
          </template>
          <el-empty v-else :description="t('qc.selectImage')" />
        </section>

        <aside class="qc-review-panel">
          <section class="qc-comment-card">
            <div class="qc-comment-box">
              <p>{{ t('qc.rejectReason') }}</p>
              <span>{{ t('qc.selectRejectedImages') }}</span>
              <el-input
                v-if="current.status === 'reviewing' && image"
                v-model="currentRejectReason"
                type="textarea"
                :rows="4"
                maxlength="10000"
                show-word-limit
                resize="vertical"
              />
              <span v-else>{{ t('qc.selectImage') }}</span>
            </div>
            <div v-if="current.status === 'reviewing'" class="qc-draft-actions">
              <span v-if="current.hasDraft" class="draft-status">{{ t('qc.draftUnsaved') }}</span>
              <el-button type="success" :icon="'Finished'" :loading="draftSaving" :disabled="!current.hasDraft" @click="saveDraft">
                {{ t('qc.saveDraft') }}
              </el-button>
              <el-button :icon="'Delete'" :loading="draftDiscarding" :disabled="!current.hasDraft" @click="discardDraft">
                {{ t('qc.discardDraft') }}
              </el-button>
            </div>
          </section>

          <section class="qc-info-card">
            <div class="qc-panel-heading">
              <span>{{ t('qc.metadata') }}</span>
              <strong>{{ current.metadata.folderName }}</strong>
            </div>
            <el-form
              :model="metadataForm"
              label-position="top"
              class="qc-inline-metadata-form"
              :disabled="current.status !== 'reviewing' || metadataSaving"
            >
              <el-form-item
                v-for="field in editableTemplateFields"
                :key="field.key"
                :label="field.label"
                :required="field.mandatory"
              >
                <el-select
                  v-if="field.input === 'select'"
                  v-model="metadataForm[field.key]"
                  clearable
                  filterable
                  style="width: 100%"
                  @change="syncDerivedMetadataFields"
                >
                  <el-option
                    v-for="option in field.options"
                    :key="option"
                    :label="displayOption(option)"
                    :value="optionValue(field, option)"
                  />
                </el-select>
                <el-input v-else-if="field.input === 'fixed'" :model-value="field.value || ''" readonly />
                <el-input v-else v-model="metadataForm[field.key]" @input="syncDerivedMetadataFields" />
              </el-form-item>
              <el-form-item :label="t('qc.fields.recordType')">
                <el-input v-model="metadataForm.recordType" readonly />
              </el-form-item>
            </el-form>
            <div v-if="current.status === 'reviewing'" class="qc-inline-metadata-actions">
              <el-button
                :type="metadataDirty ? 'primary' : 'info'"
                :loading="metadataSaving"
                :disabled="!metadataDirty"
                @click="saveMetadata"
              >
                {{ metadataDirty ? t('common.save') : t('common.saved') }}
              </el-button>
            </div>
          </section>
        </aside>

        <footer class="qc-tool-strip">
          <input ref="replaceInputEl" class="hidden-file-input" type="file" accept=".tif,.tiff" @change="handleReplaceUpload" />
          <input ref="insertInputEl" class="hidden-file-input" type="file" accept=".tif,.tiff" @change="handleInsertUpload" />
          <div class="qc-tool-row">
            <template v-if="current.status === 'reviewing'">
              <el-button :icon="'Upload'" :loading="actionLoading" @click="triggerReplaceUpload">{{ t('qc.replaceImage') }}</el-button>
              <el-button :icon="'Plus'" :loading="actionLoading" @click="triggerInsertUpload">{{ t('qc.insertBefore') }}</el-button>
              <el-button :icon="'Delete'" :loading="actionLoading" @click="deleteCurrentImage">{{ t('common.delete') }}</el-button>
              <el-button v-if="image?.available" :icon="'Crop'" @click="openCropDialog">{{ t('qc.cropImage') }}</el-button>
              <el-button :icon="'RefreshLeft'" :loading="actionLoading" @click="rotateCurrent(-90)">{{ t('qc.rotateLeft') }}</el-button>
              <el-button :icon="'RefreshRight'" :loading="actionLoading" @click="rotateCurrent(90)">{{ t('qc.rotateRight') }}</el-button>
              <el-button :icon="'ArrowUp'" :loading="actionLoading" @click="moveCurrentImage(-1)">{{ t('qc.moveUp') }}</el-button>
              <el-button :icon="'ArrowDown'" :loading="actionLoading" @click="moveCurrentImage(1)">{{ t('qc.moveDown') }}</el-button>
              <el-button :loading="actionLoading" @click="undoDraftAction">{{ t('qc.undo') }}</el-button>
              <el-button :loading="actionLoading" @click="redoDraftAction">{{ t('qc.redo') }}</el-button>
              <el-popover
                v-model:visible="showMoreImageTools"
                placement="top-start"
                trigger="click"
                :width="360"
                popper-class="qc-tool-popover"
              >
                <div class="qc-more-tool-grid">
                  <el-button :icon="'Operation'" :loading="actionLoading" @click="rotateSelectedBatch(90)">{{ t('qc.batchRotate') }}</el-button>
                  <el-button :loading="actionLoading" @click="deskewCurrent(-1)">{{ t('qc.deskewMinus') }}</el-button>
                  <el-button :loading="actionLoading" @click="deskewCurrent(1)">{{ t('qc.deskewPlus') }}</el-button>
                  <el-button :type="separationMode ? 'warning' : 'default'" @click="separationMode = !separationMode">{{ t('qc.separationMode') }}</el-button>
                  <el-button :loading="actionLoading" @click="restoreCurrentImage">{{ t('qc.restoreOriginal') }}</el-button>
                  <el-button v-if="image?.available" :icon="'Sunny'" :loading="luminanceLoading" @click="applyLuminanceToCurrent">{{ t('qc.luminance') }}</el-button>
                  <el-button :icon="'Operation'" :loading="luminanceLoading" @click="applyLuminanceBatch">{{ t('qc.batchLuminance') }}</el-button>
                </div>
                <template #reference>
                  <el-button :icon="'MoreFilled'">{{ t('common.more') }}</el-button>
                </template>
              </el-popover>
            </template>
          </div>
        </footer>
      </template>
      <el-empty v-else :description="t('qc.noMineTask')" />
    </div>

    <div v-else-if="active === 'mine'" class="qc-workbench-redesign" :class="{ 'qc-workbench-redesign--compact': isWorkbenchRoute }">
      <!-- 左侧缩略图侧边栏（可折叠） -->
      <aside v-loading="loading" class="thumbnail-sidebar" :class="{ collapsed: false }">
        <template v-if="active === 'mine' && current">
          <div class="sidebar-header">
            <div class="folder-info">
              <span class="folder-label">{{ current.metadata.folderName }}</span>
              <span class="image-count">{{ current.imageCount }} {{ t('qc.images') }}</span>
            </div>
            <div v-if="current.status === 'reviewing'" class="batch-selection-tools">
              <span>{{ t('qc.batchSelected') }} {{ batchSelectionLabel }}</span>
              <div>
                <el-button size="small" link :disabled="!batchableImageIds.length" @click="selectAllBatchImages">
                  {{ t('qc.selectAllImages') }}
                </el-button>
                <el-button size="small" link :disabled="!selectedBatchIds.length" @click="clearBatchSelection">
                  {{ t('qc.clearImageSelection') }}
                </el-button>
              </div>
            </div>
          </div>
          <div class="thumbnail-list">
            <button
              v-for="(item, index) in current.images"
              :key="item.id"
              type="button"
              class="thumbnail-item"
              :class="{ active: image?.id === item.id, selected: selectedBatchIds.includes(item.id), unavailable: !item.available }"
              @click="image = item"
              :title="item.filename"
            >
              <el-checkbox
                v-if="current.status === 'reviewing'"
                class="thumbnail-select"
                :model-value="selectedBatchIds.includes(item.id)"
                :disabled="!item.available"
                @click.stop
                @change="(checked: boolean) => toggleImageSelection(item.id, checked)"
              />
              <div class="thumbnail-number">{{ String(index + 1).padStart(2, '0') }}</div>
              <div class="thumbnail-preview">
                <el-icon v-if="!item.available" class="unavailable-icon"><WarningFilled /></el-icon>
                <span v-else class="file-icon">📄</span>
              </div>
              <span v-if="current.draftImageIds.includes(item.id)" class="draft-dot">{{ t('qc.draftUnsaved') }}</span>
              <span v-if="item.draftState" class="draft-state">{{ item.draftState }}</span>
              <el-button
                v-if="current.status === 'reviewing' && separationMode"
                class="separation-marker"
                size="small"
                :type="item.separationStart ? 'warning' : 'default'"
                circle
                @click.stop="toggleSeparationMarker(item.id)"
              >
                S
              </el-button>
              <div class="thumbnail-name">{{ item.filename }}</div>
            </button>
          </div>
        </template>
        <template v-else>
          <el-empty :description="t('qc.noMineTask')" />
        </template>
      </aside>

      <!-- 中央图片预览主区域 -->
      <section v-loading="detailLoading || previewLoading" class="main-preview-area">
        <template v-if="image && current">
          <!-- 浮动工具条 -->
          <div class="image-toolbar">
            <div class="toolbar-left">
              <span class="current-filename">{{ image.filename }}</span>
              <span class="image-counter">{{ currentImageIndex }} / {{ current.imageCount }}</span>
            </div>
            <div class="toolbar-right">
              <input ref="replaceInputEl" class="hidden-file-input" type="file" accept=".tif,.tiff" @change="handleReplaceUpload" />
              <input ref="insertInputEl" class="hidden-file-input" type="file" accept=".tif,.tiff" @change="handleInsertUpload" />
              <el-button v-if="current.status === 'reviewing'" size="small" text :loading="actionLoading" :icon="'Upload'" @click="triggerReplaceUpload">
                {{ t('qc.replaceImage') }}
              </el-button>
              <el-button v-if="current.status === 'reviewing'" size="small" text :loading="actionLoading" :icon="'Plus'" @click="triggerInsertUpload">
                {{ t('qc.insertBefore') }}
              </el-button>
              <el-button v-if="current.status === 'reviewing'" size="small" text :loading="actionLoading" :icon="'Delete'" @click="deleteCurrentImage">
                {{ t('common.delete') }}
              </el-button>
              <el-button v-if="current.status === 'reviewing'" size="small" text :loading="actionLoading" :icon="'RefreshLeft'" @click="rotateCurrent(-90)">
                {{ t('qc.rotateLeft') }}
              </el-button>
              <el-button v-if="current.status === 'reviewing'" size="small" text :loading="actionLoading" :icon="'RefreshRight'" @click="rotateCurrent(90)">
                {{ t('qc.rotateRight') }}
              </el-button>
              <el-button v-if="current.status === 'reviewing'" size="small" text :loading="actionLoading" :icon="'Operation'" @click="rotateSelectedBatch(90)">
                {{ t('qc.batchRotate') }}
              </el-button>
              <el-button v-if="current.status === 'reviewing'" size="small" text :loading="actionLoading" @click="deskewCurrent(-1)">
                {{ t('qc.deskewMinus') }}
              </el-button>
              <el-button v-if="current.status === 'reviewing'" size="small" text :loading="actionLoading" @click="deskewCurrent(1)">
                {{ t('qc.deskewPlus') }}
              </el-button>
              <el-button v-if="current.status === 'reviewing'" size="small" text :loading="actionLoading" :icon="'ArrowUp'" @click="moveCurrentImage(-1)">
                {{ t('qc.moveUp') }}
              </el-button>
              <el-button v-if="current.status === 'reviewing'" size="small" text :loading="actionLoading" :icon="'ArrowDown'" @click="moveCurrentImage(1)">
                {{ t('qc.moveDown') }}
              </el-button>
              <el-button v-if="current.status === 'reviewing'" size="small" text :type="separationMode ? 'warning' : 'default'" @click="separationMode = !separationMode">
                {{ t('qc.separationMode') }}
              </el-button>
              <el-button v-if="current.status === 'reviewing'" size="small" text :loading="actionLoading" @click="undoDraftAction">
                {{ t('qc.undo') }}
              </el-button>
              <el-button v-if="current.status === 'reviewing'" size="small" text :loading="actionLoading" @click="redoDraftAction">
                {{ t('qc.redo') }}
              </el-button>
              <el-button v-if="current.status === 'reviewing'" size="small" text :loading="actionLoading" @click="restoreCurrentImage">
                {{ t('qc.restoreOriginal') }}
              </el-button>
              <el-button
                v-if="current.status === 'reviewing' && image.available"
                size="small"
                text
                :loading="luminanceLoading"
                :icon="'Sunny'"
                @click="applyLuminanceToCurrent"
              >
                {{ t('qc.luminance') }}
              </el-button>
              <el-button
                v-if="current.status === 'reviewing'"
                size="small"
                text
                :loading="luminanceLoading"
                :icon="'Operation'"
                @click="applyLuminanceBatch"
              >
                {{ t('qc.batchLuminance') }}
              </el-button>
              <el-button
                v-if="current.status === 'reviewing' && image.available"
                size="small"
                text
                :icon="'Crop'"
                @click="openCropDialog"
              >
                {{ t('qc.cropImage') }}
              </el-button>
              <el-button size="small" text @click="openViewer" :icon="'ZoomIn'">{{ t('qc.viewLarge') }}</el-button>
            </div>
          </div>

          <!-- 图片展示 -->
          <div class="image-container">
            <img v-if="previewSrc" class="main-image" :src="previewSrc" :alt="image.filename" @click="openViewer" />
            <el-alert v-else-if="!image.available" type="error" :closable="false" :title="t('qc.imageMissing')" />
            <span v-else-if="previewError" class="error-message">{{ previewError }}</span>
          </div>

          <!-- 图片导航按钮 -->
          <button
            v-if="currentImageIndex > 1"
            class="nav-button nav-prev"
            @click="image = current.images[currentImageIndex - 2]"
            :title="t('common.previous')"
          >
            <el-icon><ArrowLeft /></el-icon>
          </button>
          <button
            v-if="currentImageIndex < current.imageCount"
            class="nav-button nav-next"
            @click="image = current.images[currentImageIndex]"
            :title="t('common.next')"
          >
            <el-icon><ArrowRight /></el-icon>
          </button>
        </template>
        <el-empty v-else :description="t('qc.selectImage')" />
      </section>

      <!-- 右侧元数据面板（可折叠） -->
      <aside class="metadata-sidebar" :class="{ collapsed: false }">
        <template v-if="current">
          <div class="sidebar-header">
            <div>
              <p class="metadata-label">{{ t('qc.metadata') }}</p>
              <h3 class="folder-name">{{ current.metadata.folderName }}</h3>
            </div>
            <span class="status-pill" :data-status="current.status">{{ translateValue('metadataQcStatus', current.status) }}</span>
          </div>

          <div class="metadata-content">
            <el-button v-if="current.status === 'reviewing'" class="edit-metadata-btn" :icon="'Edit'" @click="openMetadataEditor">
              {{ t('qc.editMetadata') }}
            </el-button>

            <div class="metadata-summary">
              <div class="summary-item">
                <span class="summary-label">{{ t('qc.fields.projectName') }}</span>
                <span class="summary-value">{{ current.metadata.projectName }}</span>
              </div>
              <div class="summary-item">
                <span class="summary-label">{{ t('qc.fields.boxDetails') }}</span>
                <span class="summary-value">{{ current.metadata.boxName }}</span>
              </div>
              <div class="summary-item">
                <span class="summary-label">{{ t('qc.fields.title') }}</span>
                <span class="summary-value">{{ displayValue(current.metadata.title) }}</span>
              </div>
            </div>

            <details class="metadata-details" open>
              <summary>{{ t('qc.viewAllMetadata') }}</summary>
              <section v-for="group in metadataGroups" :key="group.title" class="metadata-group-compact">
                <h4>{{ group.title }}</h4>
                <dl class="metadata-list-compact">
                  <div v-for="field in group.fields" :key="String(field[0])">
                    <dt>{{ field[0] }}</dt>
                    <dd>{{ displayValue(field[1]) }}</dd>
                  </div>
                </dl>
              </section>
            </details>

            <section v-if="current.status !== 'reviewing'" class="review-history-compact">
              <p class="metadata-label">{{ t('qc.reviewHistory') }}</p>
            </section>
          </div>
        </template>
        <el-empty v-else :description="t('qc.noMineTask')" />
      </aside>

      <!-- 底部固定操作栏 -->
      <footer v-if="current" class="action-bar">
        <div v-if="false" class="breadcrumb">
          <span class="breadcrumb-item">{{ current.metadata.projectName }}</span>
          <span class="breadcrumb-separator">›</span>
          <span class="breadcrumb-item">{{ current.metadata.boxName }}</span>
          <span class="breadcrumb-separator">›</span>
          <span class="breadcrumb-item active">{{ current.metadata.folderName }}</span>
        </div>
        <div v-if="current.status === 'reviewing'" class="action-buttons">
          <span v-if="current.hasDraft" class="draft-status">{{ t('qc.draftUnsaved') }}</span>
          <el-button
            size="large"
            type="success"
            :icon="'Finished'"
            :loading="draftSaving"
            :disabled="!current.hasDraft"
            @click="saveDraft"
          >
            {{ t('qc.saveDraft') }}
          </el-button>
          <el-button
            size="large"
            :icon="'Delete'"
            :loading="draftDiscarding"
            :disabled="!current.hasDraft"
            @click="discardDraft"
          >
            {{ t('qc.discardDraft') }}
          </el-button>
          <el-button size="large" type="primary" :icon="'Check'" :loading="actionLoading" :disabled="!current.imageAvailable" @click="approve">
            {{ t('qc.passFolder') }}
          </el-button>
          <el-button size="large" :icon="'Close'" :loading="actionLoading" @click="closeCurrentTask">
            {{ t('common.close') }}
          </el-button>
          <el-button size="large" type="danger" :icon="'Close'" :loading="actionLoading" @click="openRejectDialog">
            {{ t('qc.rejectImages') }}
          </el-button>
        </div>
      </footer>
    </div>

    <div v-else class="completed-history-redesign" :class="{ 'completed-history-redesign--compact': route.name === 'qc-completed' }">
      <!-- 左侧任务列表 -->
      <aside v-loading="loading" class="completed-sidebar">
        <div class="completed-sidebar-header">
          <div>
            <p class="sidebar-label">{{ t('qc.completed') }}</p>
            <h3 class="total-count">{{ scopeTotals.completed ?? tasks.length }}</h3>
          </div>
        </div>

        <div class="completed-task-list">
          <el-empty v-if="!tasks.length && !loading" :description="t('qc.noTasks')" />
          <button
            v-for="task in tasks"
            :key="task.id"
            type="button"
            class="completed-task-card"
            :class="{ active: current?.id === task.id }"
            @click="open(task)"
          >
            <div class="task-card-header">
              <span class="status-badge" :data-status="task.status">
                {{ translateValue('metadataQcStatus', task.status) }}
              </span>
              <span class="image-badge">{{ task.imageCount }}</span>
            </div>
            <div class="task-card-body">
              <strong class="task-folder-name">{{ task.metadata.folderName }}</strong>
              <small class="task-project">{{ task.metadata.projectName }}</small>
              <small class="task-box">{{ task.metadata.boxName }}</small>
              <small class="task-time">{{ displayValue(completedTime(task)) }}</small>
            </div>
          </button>
        </div>
      </aside>

      <!-- 中央图片预览区 -->
      <section v-loading="detailLoading || previewLoading" class="completed-main-preview">
        <template v-if="image && current">
          <!-- 浮动工具条 -->
          <div class="image-toolbar">
            <div class="toolbar-left">
              <span class="current-filename">{{ image.filename }}</span>
              <span class="image-counter">{{ currentImageIndex }} / {{ current.imageCount }}</span>
            </div>
            <div class="toolbar-right">
              <el-button size="small" text @click="openViewer" :icon="'ZoomIn'">{{ t('qc.viewLarge') }}</el-button>
            </div>
          </div>

          <!-- 图片展示 -->
          <div class="image-container">
            <img v-if="previewSrc" class="main-image" :src="previewSrc" :alt="image.filename" @click="openViewer" />
            <el-alert v-else-if="!image.available" type="error" :closable="false" :title="t('qc.imageMissing')" />
            <span v-else-if="previewError" class="error-message">{{ previewError }}</span>
          </div>

          <!-- 图片导航按钮 -->
          <button
            v-if="currentImageIndex > 1"
            class="nav-button nav-prev"
            @click="image = current.images[currentImageIndex - 2]"
            :title="t('common.previous')"
          >
            <el-icon><ArrowLeft /></el-icon>
          </button>
          <button
            v-if="currentImageIndex < current.imageCount"
            class="nav-button nav-next"
            @click="image = current.images[currentImageIndex]"
            :title="t('common.next')"
          >
            <el-icon><ArrowRight /></el-icon>
          </button>
        </template>
        <el-empty v-else :description="t('common.selectTask')" />
      </section>

      <!-- 右侧详情面板 -->
      <aside class="completed-detail-sidebar">
        <template v-if="current">
          <div class="sidebar-header">
            <div>
              <p class="metadata-label">{{ t('qc.metadata') }}</p>
              <h3 class="folder-name">{{ current.metadata.folderName }}</h3>
            </div>
            <span class="status-pill" :data-status="current.status">{{ translateValue('metadataQcStatus', current.status) }}</span>
          </div>

          <div class="detail-content">
            <!-- 图片快速导航 -->
            <div class="image-quick-nav">
              <h4>{{ t('qc.images') }} ({{ current.imageCount }})</h4>
              <div class="image-chip-grid">
                <button
                  v-for="(item, index) in current.images"
                  :key="item.id"
                  type="button"
                  class="image-chip"
                  :class="{ active: image?.id === item.id, unavailable: !item.available }"
                  :title="item.filename"
                  @click="image = item"
                >
                  {{ String(index + 1).padStart(2, '0') }}
                </button>
              </div>
            </div>

            <!-- 元数据摘要 -->
            <div class="metadata-summary">
              <div class="summary-item">
                <span class="summary-label">{{ t('qc.fields.projectName') }}</span>
                <span class="summary-value">{{ current.metadata.projectName }}</span>
              </div>
              <div class="summary-item">
                <span class="summary-label">{{ t('qc.fields.boxDetails') }}</span>
                <span class="summary-value">{{ current.metadata.boxName }}</span>
              </div>
              <div class="summary-item">
                <span class="summary-label">{{ t('qc.fields.title') }}</span>
                <span class="summary-value">{{ displayValue(current.metadata.title) }}</span>
              </div>
            </div>

            <!-- 完整元数据 -->
            <details class="metadata-details">
              <summary>{{ t('qc.viewAllMetadata') }}</summary>
              <section v-for="group in metadataGroups" :key="group.title" class="metadata-group-compact">
                <h4>{{ group.title }}</h4>
                <dl class="metadata-list-compact">
                  <div v-for="field in group.fields" :key="String(field[0])">
                    <dt>{{ field[0] }}</dt>
                    <dd>{{ displayValue(field[1]) }}</dd>
                  </div>
                </dl>
              </section>
            </details>
          </div>
        </template>
        <el-empty v-else :description="t('common.selectTask')" />
      </aside>
    </div>

    <el-dialog v-model="rejectDialogVisible" :title="t('qc.rejectImages')" width="520px">
      <el-form label-position="top">
        <el-form-item :label="t('qc.selectRejectedImages')" required>
          <el-checkbox-group v-model="rejectedImageIds" class="reject-image-options" @change="syncRejectReasons">
            <el-checkbox v-for="item in current?.images || []" :key="item.id" :value="item.id">{{ item.filename }}</el-checkbox>
          </el-checkbox-group>
        </el-form-item>
        <div v-if="rejectedImageIds.length" class="reject-reason-list">
          <el-form-item
            v-for="imageId in rejectedImageIds"
            :key="imageId"
            :label="`${current?.images.find((item) => item.id === imageId)?.filename || imageId} - ${t('qc.rejectReason')}`"
            required
          >
            <el-input v-model="rejectReasons[imageId]" type="textarea" :rows="3" maxlength="10000" show-word-limit />
          </el-form-item>
        </div>
      </el-form>
      <template #footer>
        <el-button @click="rejectDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="danger" :loading="actionLoading" @click="submitReject">{{ t('qc.confirmReject') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="metadataDialogVisible" :title="t('qc.editMetadata')" width="760px">
      <el-form :model="metadataForm" label-position="top" class="metadata-edit-grid">
        <el-form-item
          v-for="field in editableTemplateFields"
          :key="field.key"
          :label="field.label"
          :required="field.mandatory"
        >
          <el-select
            v-if="field.input === 'select'"
            v-model="metadataForm[field.key]"
            clearable
            filterable
            style="width: 100%"
            @change="syncDerivedMetadataFields"
          >
            <el-option
              v-for="option in field.options"
              :key="option"
              :label="displayOption(option)"
              :value="optionValue(field, option)"
            />
          </el-select>
          <el-input v-else-if="field.input === 'fixed'" :model-value="field.value || ''" readonly />
          <el-input v-else v-model="metadataForm[field.key]" @input="syncDerivedMetadataFields" />
        </el-form-item>
        <el-form-item :label="t('qc.fields.recordType')">
          <el-input v-model="metadataForm.recordType" readonly />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="metadataDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button type="primary" :loading="metadataSaving" @click="saveMetadata">{{ t('common.save') }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="cropDialogVisible" :title="t('qc.cropImage')" width="min(1120px, 96vw)" class="crop-dialog" @closed="resetCropSelection">
      <div class="crop-workspace">
        <div class="crop-stage">
          <div v-if="previewSrc" class="crop-image-wrap">
            <img
              ref="cropImageEl"
              class="crop-image"
              :src="previewSrc"
              :alt="image?.filename"
              draggable="false"
              @pointerdown="startCrop"
            />
            <div v-if="hasCropSelection" class="crop-selection" :style="cropSelectionStyle" />
          </div>
        </div>
        <p class="crop-hint">{{ t('qc.cropHint') }}</p>
      </div>
      <template #footer>
        <el-button @click="cropDialogVisible = false">{{ t('common.cancel') }}</el-button>
        <el-button @click="resetCropSelection">{{ t('common.reset') }}</el-button>
        <el-button type="primary" :loading="cropLoading" :disabled="!hasCropSelection" @click="submitCrop">
          {{ t('qc.confirmCrop') }}
        </el-button>
      </template>
    </el-dialog>

    <ImagePreviewViewer v-model="viewerVisible" :src="previewSrc" :alt="image?.filename" />
  </AppShell>
</template>

<style scoped>
.qc-page-header {
  display: grid;
  gap: 20px;
  margin-bottom: 24px;
}

.qc-page-title {
  margin-bottom: 0;
}

.qc-toolbar {
  flex-shrink: 0;
  margin-bottom: 0;
}

.qc-summary-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 16px;
}

.qc-summary-item {
  position: relative;
  min-width: 0;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  min-height: 80px;
  padding: 20px 24px;
  border: none;
  border-radius: 12px;
  background: linear-gradient(135deg, #ffffff 0%, #f8fffe 100%);
  box-shadow: 0 2px 8px rgba(4, 98, 65, 0.08), 0 1px 2px rgba(0, 0, 0, 0.04);
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  overflow: hidden;
}

.qc-summary-item::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  width: 4px;
  height: 100%;
  background: linear-gradient(180deg, var(--el-color-primary) 0%, var(--el-color-success) 100%);
  transition: width 0.3s ease;
}

.qc-summary-item:hover {
  transform: translateY(-2px);
  box-shadow: 0 4px 16px rgba(4, 98, 65, 0.12), 0 2px 4px rgba(0, 0, 0, 0.06);
}

.qc-summary-item:hover::before {
  width: 6px;
}

.qc-summary-item span {
  color: var(--el-text-color-secondary);
  font-size: 14px;
  font-weight: 500;
  letter-spacing: 0.3px;
}

.qc-summary-item strong {
  overflow: hidden;
  color: var(--el-color-primary);
  font-size: 32px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
  line-height: 1;
}

:global(.crop-dialog .el-dialog__body) {
  padding-top: 8px;
  overflow: hidden;
}

.crop-workspace {
  display: grid;
  gap: 12px;
}

.crop-stage {
  position: relative;
  width: 100%;
  min-height: 220px;
  max-height: min(62vh, 680px);
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  border: 1px solid #D6DDD6;
  border-radius: 8px;
  background: #101612;
  user-select: none;
}

.crop-image-wrap {
  position: relative;
  display: inline-block;
  max-width: 100%;
  line-height: 0;
}

.crop-image {
  display: block;
  max-width: 100%;
  max-height: min(62vh, 680px);
  width: auto;
  height: auto;
  object-fit: contain;
  cursor: crosshair;
  user-select: none;
  touch-action: none;
}

.crop-selection {
  position: absolute;
  z-index: 2;
  border: 2px solid #FFB13B;
  background: rgba(255, 177, 59, 0.18);
  box-shadow: 0 0 0 9999px rgba(0, 0, 0, 0.42);
  pointer-events: none;
}

.crop-hint {
  margin: 0;
  color: #5A6F66;
  font-size: 13px;
}

.pending-queue-panel {
  padding: 28px;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04), 0 1px 3px rgba(0, 0, 0, 0.02);
}

.queue-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 24px;
  margin-bottom: 24px;
}

.queue-heading h2 {
  margin: 6px 0 0;
  font-size: 24px;
  font-weight: 600;
}

.queue-heading .el-alert {
  max-width: 480px;
}

.pending-task-table {
  border-top: none;
  border-radius: 8px;
  overflow: hidden;
}

.pending-task-table :deep(.el-table__header) {
  background: linear-gradient(180deg, #f8fffe 0%, #f5f7f6 100%);
}

.pending-task-table :deep(.el-table__row) {
  transition: all 0.2s ease;
}

.pending-task-table :deep(.el-table__row:hover) {
  background: var(--el-color-primary-light-9);
  transform: scale(1.002);
}

.pending-task-table :deep(.cell) {
  padding: 12px 8px;
}

/* 新布局：图片为中心设计 */
.qc-workbench-redesign {
  position: relative;
  display: grid;
  grid-template-columns: minmax(160px, 180px) 1fr minmax(280px, 320px);
  grid-template-rows: 1fr auto;
  gap: 0;
  height: calc(100vh - 236px);
  max-height: calc(100vh - 236px);
  background: #E8ECEA;
  overflow: hidden;
}

.qc-workbench-redesign--compact {
  height: calc(100vh - 136px);
  max-height: calc(100vh - 136px);
}

/* 左侧缩略图侧边栏 */
.thumbnail-sidebar {
  grid-column: 1;
  grid-row: 1 / 3;
  display: flex;
  flex-direction: column;
  background: #FAFBFA;
  border-right: 1px solid #D4D9D6;
  overflow: hidden;
}

.sidebar-header {
  display: grid;
  gap: 10px;
  padding: 16px 12px;
  border-bottom: 1px solid #D4D9D6;
  background: #F0F3F1;
}

.folder-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.folder-label {
  font-size: 13px;
  font-weight: 600;
  color: #2C5F4F;
  line-height: 1.3;
}

.image-count {
  font-size: 11px;
  color: #5A6F66;
  font-weight: 500;
}

.batch-selection-tools {
  display: grid;
  gap: 4px;
  padding: 8px;
  border: 1px solid #D4D9D6;
  border-radius: 8px;
  background: #FFFFFF;
}

.batch-selection-tools span {
  color: #2C5F4F;
  font-size: 11px;
  font-weight: 700;
}

.batch-selection-tools div {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.batch-selection-tools :deep(.el-button) {
  min-height: 22px;
  padding: 0;
  font-size: 11px;
}

.thumbnail-list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  max-height: 100%;
}

.thumbnail-item {
  position: relative;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
  padding: 8px 6px;
  border: 2px solid transparent;
  border-radius: 8px;
  background: #FFFFFF;
  cursor: pointer;
  transition: all 0.2s ease;
  flex-shrink: 0;
}

.thumbnail-item:hover {
  border-color: #2C5F4F;
  background: #F8FAF9;
  transform: translateX(2px);
}

.thumbnail-item.active {
  border-color: #2C5F4F;
  background: linear-gradient(135deg, #E8F3EF 0%, #F8FAF9 100%);
  box-shadow: 0 2px 8px rgba(44, 95, 79, 0.15);
}

.thumbnail-item.selected {
  border-color: #2C5F4F;
  box-shadow: inset 0 0 0 1px #2C5F4F, 0 2px 8px rgba(44, 95, 79, 0.15);
}

.thumbnail-item.unavailable {
  opacity: 0.5;
  background: #FFF5F5;
}

.thumbnail-select {
  position: absolute;
  z-index: 4;
  top: 6px;
  left: 6px;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  padding: 0 0 0 2px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 1px 4px rgba(26, 51, 41, 0.16);
}

.thumbnail-select :deep(.el-checkbox__label) {
  display: none;
}

.draft-dot {
  position: absolute;
  z-index: 2;
  top: 6px;
  right: 6px;
  max-width: calc(100% - 38px);
  padding: 2px 6px;
  overflow: hidden;
  border-radius: 6px;
  background: #FFF7E6;
  color: #B76E00;
  font-size: 10px;
  font-weight: 700;
  line-height: 1.2;
  text-overflow: ellipsis;
  white-space: nowrap;
  box-shadow: 0 1px 4px rgba(183, 110, 0, 0.16);
}

.draft-state {
  position: absolute;
  z-index: 2;
  left: 6px;
  bottom: 28px;
  max-width: calc(100% - 12px);
  padding: 2px 6px;
  overflow: hidden;
  border-radius: 6px;
  background: #E8F3EF;
  color: #2C5F4F;
  font-size: 10px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.separation-marker {
  position: absolute;
  z-index: 3;
  right: 6px;
  bottom: 26px;
}

.thumbnail-number {
  position: absolute;
  top: 6px;
  right: 6px;
  padding: 2px 6px;
  background: rgba(44, 95, 79, 0.85);
  color: white;
  font-size: 10px;
  font-weight: 700;
  border-radius: 4px;
  font-variant-numeric: tabular-nums;
}

.thumbnail-preview {
  width: 100%;
  height: 60px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #F5F7F6;
  border-radius: 6px;
  font-size: 24px;
  flex-shrink: 0;
}

.unavailable-icon {
  font-size: 28px;
  color: #D14343;
}

.thumbnail-name {
  width: 100%;
  font-size: 11px;
  color: #5A6F66;
  text-align: center;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 中央图片预览主区域 */
.main-preview-area {
  grid-column: 2;
  grid-row: 1;
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #E8ECEA;
  overflow: hidden;
}

.image-toolbar {
  position: absolute;
  top: 12px;
  left: 12px;
  right: 12px;
  z-index: 10;
  display: grid;
  grid-template-columns: max-content minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  padding: 10px 12px;
  background: rgba(44, 95, 79, 0.92);
  backdrop-filter: blur(12px);
  border-radius: 8px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.2);
  max-width: 100%;
}

.toolbar-left {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
  max-width: 240px;
}

.current-filename {
  font-size: 12px;
  font-weight: 600;
  color: white;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  flex: 0 1 auto;
  max-width: 160px;
  min-width: 0;
}

.image-counter {
  padding: 3px 7px;
  background: rgba(255, 255, 255, 0.15);
  border-radius: 6px;
  font-size: 10px;
  font-weight: 700;
  color: white;
  font-variant-numeric: tabular-nums;
  white-space: nowrap;
  flex-shrink: 0;
}

.toolbar-right {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px 8px;
  min-width: 0;
  overflow: visible;
}

.hidden-file-input {
  display: none;
}

.toolbar-right :deep(.el-button) {
  color: white;
  border-color: rgba(255, 255, 255, 0.3);
  height: 28px;
  margin: 0;
  padding: 0 8px;
  font-size: 11px;
  font-weight: 600;
}

.toolbar-right :deep(.el-button:hover) {
  background: rgba(255, 255, 255, 0.1);
  border-color: rgba(255, 255, 255, 0.5);
}

.image-container {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 70px 16px 16px;
}

.main-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  cursor: zoom-in;
  box-shadow: 0 8px 32px rgba(0, 0, 0, 0.15);
  border-radius: 4px;
  transition: transform 0.3s ease;
}

.main-image:hover {
  transform: scale(1.01);
}

.error-message {
  color: #D14343;
  font-size: 13px;
}

/* 图片导航按钮 */
.nav-button {
  position: absolute;
  top: 50%;
  transform: translateY(-50%);
  width: 44px;
  height: 44px;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(44, 95, 79, 0.92);
  border: none;
  border-radius: 50%;
  color: white;
  font-size: 18px;
  cursor: pointer;
  transition: all 0.2s ease;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
  z-index: 10;
}

.nav-button:hover {
  background: #2C5F4F;
  transform: translateY(-50%) scale(1.1);
}

.nav-prev {
  left: 16px;
}

.nav-next {
  right: 16px;
}

/* 右侧元数据面板 */
.metadata-sidebar {
  grid-column: 3;
  grid-row: 1 / 3;
  display: flex;
  flex-direction: column;
  background: #FAFBFA;
  border-left: 1px solid #D4D9D6;
  overflow: hidden;
  max-height: 100%;
}

.metadata-label {
  font-size: 10px;
  font-weight: 600;
  color: #5A6F66;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  margin: 0 0 4px;
}

.folder-name {
  font-size: 14px;
  font-weight: 700;
  color: #2C5F4F;
  margin: 0 0 4px;
  line-height: 1.3;
  word-break: break-word;
}

.version-info {
  font-size: 10px;
  color: #5A6F66;
  margin: 0;
}

.metadata-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 100%;
}

.edit-metadata-btn {
  width: 100%;
  height: 36px;
  border-radius: 8px;
  font-weight: 600;
  flex-shrink: 0;
}

.metadata-summary {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 10px;
  background: #F0F3F1;
  border-radius: 8px;
  border: 1px solid #D4D9D6;
  flex-shrink: 0;
}

.summary-item {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.summary-label {
  font-size: 10px;
  color: #5A6F66;
  font-weight: 500;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.summary-value {
  font-size: 12px;
  color: #1A3329;
  font-weight: 600;
  line-height: 1.3;
  word-break: break-word;
}

.metadata-details {
  border: 1px solid #D4D9D6;
  border-radius: 8px;
  overflow: hidden;
}

.metadata-details summary {
  padding: 8px 10px;
  background: #F0F3F1;
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  color: #2C5F4F;
  user-select: none;
}

.metadata-details summary:hover {
  background: #E8ECEA;
}

.metadata-details[open] summary {
  border-bottom: 1px solid #D4D9D6;
}

.metadata-group-compact {
  padding: 10px;
  border-bottom: 1px solid #E8ECEA;
}

.metadata-group-compact:last-child {
  border-bottom: none;
}

.metadata-group-compact h4 {
  margin: 0 0 6px;
  font-size: 11px;
  font-weight: 700;
  color: #2C5F4F;
}

.metadata-list-compact {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin: 0;
}

.metadata-list-compact div {
  display: grid;
  grid-template-columns: 85px 1fr;
  gap: 8px;
  align-items: baseline;
}

.metadata-list-compact dt {
  font-size: 10px;
  color: #5A6F66;
  font-weight: 500;
}

.metadata-list-compact dd {
  margin: 0;
  font-size: 11px;
  color: #1A3329;
  font-weight: 600;
  word-break: break-word;
}

.review-history-compact {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.review-history-compact h4 {
  margin: 0;
  font-size: 12px;
  font-weight: 700;
  color: #2C5F4F;
}

.review-item {
  padding: 10px;
  background: #F0F3F1;
  border-radius: 6px;
  border-left: 3px solid #2C5F4F;
}

.review-item[data-result="rework"] {
  background: #FFF5F5;
  border-left: 3px solid #D14343;
}

.review-item strong {
  font-size: 12px;
  color: #1A3329;
  display: block;
  margin-bottom: 4px;
}

.review-item[data-result="rework"] strong {
  color: #D14343;
}

.review-reason {
  font-size: 11px;
  color: #5A6F66;
  margin: 4px 0;
  line-height: 1.4;
}

.review-item[data-result="rework"] .review-images,
.review-item[data-result="rework"] .review-reason {
  color: #B83838;
  font-weight: 500;
}

.review-time {
  font-size: 10px;
  color: #8A9A91;
}

/* 底部固定操作栏 */
.action-bar {
  grid-column: 2;
  grid-row: 2;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 0;
  padding: 10px 16px;
  background: #FAFBFA;
  border-top: 2px solid #2C5F4F;
  box-shadow: 0 -4px 12px rgba(0, 0, 0, 0.05);
  height: 60px;
  max-height: 60px;
  flex-shrink: 0;
}

.breadcrumb {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: #5A6F66;
  overflow: hidden;
  min-width: 0;
  flex: 1;
}

.breadcrumb-item {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  min-width: 0;
}

.breadcrumb-item.active {
  color: #2C5F4F;
  font-weight: 600;
}

.breadcrumb-separator {
  color: #B4BEB9;
  flex-shrink: 0;
}

.action-buttons {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  flex-shrink: 1;
  flex-wrap: wrap;
  justify-content: center;
}

.draft-status {
  display: inline-flex;
  align-items: center;
  min-height: 32px;
  padding: 0 10px;
  border: 1px solid #F3D19E;
  border-radius: 8px;
  background: #FFF7E6;
  color: #B76E00;
  font-size: 12px;
  font-weight: 700;
  white-space: nowrap;
}

.action-buttons :deep(.el-button) {
  height: 40px;
  padding: 0 20px;
  border-radius: 8px;
  font-weight: 600;
  font-size: 13px;
}

.action-buttons :deep(.el-button--primary) {
  background: #2C5F4F;
  border-color: #2C5F4F;
}

.action-buttons :deep(.el-button--primary:hover) {
  background: #234D3F;
}

.action-buttons :deep(.el-button--danger) {
  background: #D14343;
  border-color: #D14343;
  color: white;
}

.action-buttons :deep(.el-button--danger:hover) {
  background: #B83838;
}

/* 保留旧布局以兼容其他标签页 */
.qc-workbench {
  display: grid;
  grid-template-columns: minmax(260px, 300px) minmax(420px, 1fr) minmax(340px, 400px);
  gap: 20px;
  min-height: calc(100vh - 236px);
}

.image-nav-panel,
.metadata-qc-panel,
.completed-list-panel {
  min-width: 0;
  min-height: 0;
  overflow: auto;
  border-radius: 12px;
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04), 0 1px 3px rgba(0, 0, 0, 0.02);
}

.image-nav-panel {
  padding: 0;
  background: linear-gradient(180deg, #ffffff 0%, #fafcfb 100%);
}

.image-nav-heading {
  padding: 20px 20px 16px;
  border-bottom: 1px solid var(--el-border-color-lighter);
}

.image-nav-heading h2 {
  margin: 6px 0 6px;
  overflow: hidden;
  font-size: 19px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.image-nav-heading span {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.image-nav-section {
  display: grid;
  gap: 6px;
  padding: 16px 12px 20px;
}

.hierarchy-context {
  padding: 16px 20px 12px;
  border-bottom: 1px solid var(--el-border-color-lighter);
  background: linear-gradient(135deg, rgba(4, 98, 65, 0.03) 0%, rgba(4, 98, 65, 0.01) 100%);
}

.hierarchy-context .eyebrow {
  font-weight: 600;
  color: var(--el-color-primary);
  margin-bottom: 4px;
}

.hierarchy-context span {
  color: var(--el-text-color-regular);
  font-size: 13px;
}

.tree-root {
  padding: 16px 12px;
}

.tree-folder-row {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 12px;
  margin-bottom: 8px;
  border-radius: 10px;
  background: linear-gradient(135deg, var(--el-color-primary-light-9) 0%, var(--el-color-success-light-9) 100%);
  border: 1px solid var(--el-color-primary-light-7);
}

.tree-folder-row .el-icon {
  font-size: 20px;
  color: var(--el-color-primary);
}

.tree-folder-row strong {
  display: block;
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.tree-folder-row small {
  display: block;
  font-size: 12px;
  color: var(--el-text-color-secondary);
  margin-top: 2px;
}

.tree-branch {
  margin-left: 8px;
  padding-left: 16px;
  border-left: 2px solid var(--el-border-color-light);
}

.tree-section-row,
.tree-section-label,
.tree-image-row {
  display: flex;
  align-items: center;
}

.tree-section-row,
.tree-section-label {
  gap: 10px;
  min-height: 40px;
  padding: 0 10px;
  font-size: 13px;
  font-weight: 600;
}

.tree-section-row .el-icon,
.tree-section-label .el-icon {
  font-size: 16px;
  color: var(--el-color-primary);
}

.tree-section-row .el-tag,
.tree-section-label small {
  margin-left: auto;
}

.tree-section-label small {
  color: var(--el-text-color-secondary);
  background: var(--el-fill-color);
  padding: 2px 8px;
  border-radius: 12px;
  font-size: 12px;
}

.tree-image-row {
  width: 100%;
  gap: 10px;
  min-height: 44px;
  padding: 0 12px;
  margin: 2px 0;
  border: 1.5px solid transparent;
  border-radius: 10px;
  background: transparent;
  color: var(--el-text-color-regular);
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.tree-image-row:hover {
  background: var(--el-fill-color-light);
  border-color: var(--el-border-color);
  transform: translateX(2px);
}

.tree-image-row.active {
  border-color: var(--el-color-primary);
  background: linear-gradient(135deg, var(--el-color-primary-light-9) 0%, rgba(255, 255, 255, 0.5) 100%);
  color: var(--el-color-primary);
  box-shadow: 0 2px 8px rgba(4, 98, 65, 0.12);
  font-weight: 500;
}

.tree-image-row.unavailable {
  color: var(--el-color-danger);
  opacity: 0.7;
}

.tree-index {
  flex: 0 0 auto;
  color: var(--el-text-color-placeholder);
  font-size: 11px;
  font-variant-numeric: tabular-nums;
  font-weight: 600;
}

.tree-image-name {
  min-width: 0;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.availability-dot {
  flex: 0 0 auto;
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--el-color-success);
  box-shadow: 0 0 0 2px rgba(103, 194, 58, 0.2);
}

.availability-dot.unavailable {
  background: var(--el-color-danger);
  box-shadow: 0 0 0 2px rgba(245, 108, 108, 0.2);
}

.workbench-preview,
.completed-preview {
  position: relative;
  min-height: 420px;
  border-radius: 12px;
  overflow: hidden;
  background: linear-gradient(135deg, #f9fafb 0%, #ffffff 100%);
  box-shadow: 0 2px 12px rgba(0, 0, 0, 0.04), 0 1px 3px rgba(0, 0, 0, 0.02);
}

.preview-caption {
  position: absolute;
  z-index: 2;
  top: 16px;
  right: 16px;
  left: 16px;
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 10px 16px;
  border: 1px solid rgb(255 255 255 / 20%);
  border-radius: 10px;
  background: linear-gradient(135deg, rgb(17 24 39 / 85%), rgb(31 41 55 / 85%));
  color: white;
  font-size: 13px;
  font-weight: 500;
  backdrop-filter: blur(12px);
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.2);
}

.preview-caption span {
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.preview-caption small {
  background: rgba(255, 255, 255, 0.15);
  padding: 2px 10px;
  border-radius: 6px;
  font-weight: 600;
}

.preview-image--clickable {
  cursor: zoom-in;
  transition: transform 0.3s ease;
}

.preview-image--clickable:hover {
  transform: scale(1.02);
}

.metadata-qc-panel {
  display: flex;
  flex-direction: column;
  max-height: calc(100vh - 236px);
  background: linear-gradient(180deg, #ffffff 0%, #fafcfb 100%);
}

.panel-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 14px;
}

.panel-heading h2 {
  margin: 4px 0 6px;
  overflow-wrap: anywhere;
  font-size: 19px;
  font-weight: 600;
}

.panel-heading .eyebrow {
  font-size: 12px;
  font-weight: 600;
  color: var(--el-color-primary);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.metadata-edit-button {
  width: 100%;
  flex-shrink: 0;
  margin: 16px 0;
  height: 42px;
  border-radius: 10px;
  font-weight: 500;
}

.metadata-group {
  display: grid;
  gap: 10px;
  margin-top: 20px;
  padding: 16px;
  border-radius: 10px;
  background: rgba(4, 98, 65, 0.02);
  border: 1px solid rgba(4, 98, 65, 0.06);
}

.metadata-group h3 {
  margin: 0 0 8px;
  color: var(--el-text-color-primary);
  font-size: 14px;
  font-weight: 600;
}

.metadata-list {
  display: grid;
  gap: 0;
  margin: 0;
}

.metadata-list div {
  display: grid;
  grid-template-columns: minmax(100px, 0.42fr) minmax(0, 0.58fr);
  gap: 12px;
  padding: 12px 0;
  border-bottom: 1px solid rgba(19, 48, 32, 0.06);
}

.metadata-list div:last-child {
  border-bottom: none;
}

.metadata-list dt {
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 500;
}

.metadata-list dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.review-actions {
  position: sticky;
  bottom: 0;
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin: auto -20px -20px;
  padding: 16px 20px;
  border-top: 1px solid var(--el-border-color-lighter);
  background: linear-gradient(180deg, rgba(255, 255, 255, 0.95) 0%, rgba(255, 255, 255, 1) 100%);
  backdrop-filter: blur(8px);
  box-shadow: 0 -2px 8px rgba(0, 0, 0, 0.02);
}

.review-actions .el-button {
  width: 100%;
  margin: 0;
  height: 44px;
  border-radius: 10px;
  font-weight: 500;
  font-size: 14px;
}

.review-history {
  margin-top: 20px;
}

.review-history h3 {
  margin: 0 0 12px;
  font-size: 14px;
  font-weight: 600;
}

/* 已完成界面 - 重新设计 */
.completed-history-redesign {
  position: relative;
  display: grid;
  grid-template-columns: minmax(240px, 280px) 1fr minmax(280px, 320px);
  gap: 0;
  height: calc(100vh - 236px);
  max-height: calc(100vh - 236px);
  background: #E8ECEA;
  overflow: hidden;
}

.completed-history-redesign--compact {
  height: calc(100vh - 136px);
  max-height: calc(100vh - 136px);
}

/* 左侧任务列表 */
.completed-sidebar {
  display: flex;
  flex-direction: column;
  background: #FAFBFA;
  border-right: 1px solid #D4D9D6;
  overflow: hidden;
}

.completed-sidebar-header {
  padding: 16px;
  border-bottom: 2px solid #D4D9D6;
  background: linear-gradient(135deg, #F0F3F1 0%, #FAFBFA 100%);
}

.sidebar-label {
  font-size: 10px;
  font-weight: 600;
  color: #5A6F66;
  text-transform: uppercase;
  letter-spacing: 0.8px;
  margin: 0 0 6px;
}

.total-count {
  font-size: 32px;
  font-weight: 700;
  color: #2C5F4F;
  margin: 0;
  line-height: 1;
}

.completed-task-list {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.completed-task-card {
  position: relative;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  border: 1.5px solid transparent;
  border-radius: 10px;
  background: #FFFFFF;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  text-align: left;
}

.completed-task-card:hover {
  border-color: #2C5F4F;
  background: #F8FAF9;
  transform: translateX(3px);
  box-shadow: 0 2px 8px rgba(44, 95, 79, 0.12);
}

.completed-task-card.active {
  border-color: #2C5F4F;
  background: linear-gradient(135deg, #E8F3EF 0%, #F8FAF9 100%);
  box-shadow: 0 4px 12px rgba(44, 95, 79, 0.18);
}

.task-card-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.status-badge {
  display: inline-flex;
  align-items: center;
  padding: 3px 8px;
  border-radius: 12px;
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

.status-badge[data-status="passed"] {
  background: #E8F3EF;
  color: #2C5F4F;
  border: 1px solid #2C5F4F;
}

.status-badge[data-status="rework"] {
  background: #FFF5F5;
  color: #D14343;
  border: 1px solid #D14343;
}

.image-badge {
  padding: 3px 8px;
  background: #F0F3F1;
  border-radius: 8px;
  font-size: 11px;
  font-weight: 600;
  color: #5A6F66;
}

.task-card-body {
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.task-folder-name {
  font-size: 14px;
  font-weight: 700;
  color: #1A3329;
  line-height: 1.3;
  word-break: break-word;
}

.task-project,
.task-box,
.task-time {
  font-size: 11px;
  color: #5A6F66;
  line-height: 1.3;
}

/* 中央图片预览区（复用样式） */
.completed-main-preview {
  position: relative;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #E8ECEA;
  overflow: hidden;
}

/* 右侧详情面板 */
.completed-detail-sidebar {
  display: flex;
  flex-direction: column;
  background: #FAFBFA;
  border-left: 1px solid #D4D9D6;
  overflow: hidden;
  max-height: 100%;
}

.detail-content {
  flex: 1;
  overflow-y: auto;
  overflow-x: hidden;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-height: 100%;
}

/* 图片快速导航 */
.image-quick-nav {
  flex-shrink: 0;
}

.image-quick-nav h4 {
  margin: 0 0 8px;
  font-size: 11px;
  font-weight: 700;
  color: #2C5F4F;
}

.image-chip-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(36px, 1fr));
  gap: 6px;
}

.image-chip {
  width: 100%;
  height: 32px;
  border: 1.5px solid #D4D9D6;
  border-radius: 6px;
  background: #FFFFFF;
  color: #5A6F66;
  font-size: 11px;
  font-weight: 700;
  cursor: pointer;
  transition: all 0.2s ease;
}

.image-chip:hover {
  border-color: #2C5F4F;
  background: #E8F3EF;
  transform: scale(1.05);
}

.image-chip.active {
  border-color: #2C5F4F;
  background: #2C5F4F;
  color: #FFFFFF;
  box-shadow: 0 2px 6px rgba(44, 95, 79, 0.25);
}

.image-chip.unavailable {
  border-color: #D14343;
  color: #D14343;
  opacity: 0.6;
}

/* 审核历史样式优化 */
.review-images {
  font-size: 10px;
  color: #5A6F66;
  margin: 4px 0;
  line-height: 1.4;
}

/* 保留旧布局以防回退 */
.completed-history-layout {
  display: grid;
  grid-template-columns: minmax(300px, 380px) minmax(0, 1fr);
  gap: 20px;
  min-height: calc(100vh - 236px);
}

.completed-list-panel {
  display: grid;
  align-content: start;
  gap: 10px;
  padding: 20px;
  background: linear-gradient(180deg, #ffffff 0%, #fafcfb 100%);
}

.completed-list-heading {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 6px 6px 16px;
  border-bottom: 2px solid var(--el-border-color-lighter);
  margin-bottom: 8px;
}

.completed-list-heading h2 {
  margin: 6px 0 0;
  font-size: 32px;
  font-weight: 700;
  color: var(--el-color-primary);
}

.completed-list-heading > span {
  color: var(--el-text-color-secondary);
  font-size: 13px;
  font-weight: 500;
  background: var(--el-fill-color);
  padding: 4px 12px;
  border-radius: 8px;
}

.completed-task-row {
  width: 100%;
  display: flex;
  align-items: stretch;
  justify-content: space-between;
  gap: 14px;
  min-height: 96px;
  padding: 16px;
  border: 1.5px solid transparent;
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.6);
  color: inherit;
  font: inherit;
  text-align: left;
  cursor: pointer;
  transition: all 0.25s cubic-bezier(0.4, 0, 0.2, 1);
}

.completed-task-row:hover {
  border-color: var(--el-color-primary-light-5);
  background: #ffffff;
  transform: translateX(4px);
  box-shadow: 0 4px 12px rgba(4, 98, 65, 0.08), 0 2px 4px rgba(0, 0, 0, 0.04);
}

.completed-task-row.active {
  border-color: var(--el-color-primary);
  background: linear-gradient(135deg, var(--el-color-primary-light-9) 0%, #ffffff 100%);
  box-shadow: 0 4px 16px rgba(4, 98, 65, 0.12), 0 2px 6px rgba(0, 0, 0, 0.06);
}

.completed-task-main {
  min-width: 0;
  display: grid;
  gap: 4px;
}

.completed-task-main strong {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 15px;
  font-weight: 600;
  color: var(--el-text-color-primary);
}

.completed-task-main small,
.completed-task-meta small {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  color: var(--el-text-color-secondary);
  font-size: 12px;
}

.completed-task-meta {
  flex: 0 0 auto;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  justify-content: space-between;
  gap: 10px;
}

.completed-detail {
  min-width: 0;
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(320px, 400px);
  gap: 20px;
}

.completed-metadata-panel {
  max-height: calc(100vh - 236px);
}

.completed-image-strip {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  margin: 16px 0 8px;
  padding: 12px;
  border-radius: 10px;
  background: rgba(4, 98, 65, 0.02);
}

.completed-image-chip {
  width: 38px;
  height: 34px;
  border: 1.5px solid var(--el-border-color);
  border-radius: 8px;
  background: #ffffff;
  color: var(--el-text-color-regular);
  font: inherit;
  font-size: 12px;
  font-weight: 600;
  cursor: pointer;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.completed-image-chip:hover {
  border-color: var(--el-color-primary-light-5);
  background: var(--el-color-primary-light-9);
  transform: translateY(-2px);
  box-shadow: 0 2px 8px rgba(4, 98, 65, 0.12);
}

.completed-image-chip.active {
  border-color: var(--el-color-primary);
  background: var(--el-color-primary);
  color: #ffffff;
  box-shadow: 0 2px 12px rgba(4, 98, 65, 0.2);
}

.completed-image-chip.unavailable {
  border-color: rgba(216, 92, 72, 0.3);
  color: var(--el-color-danger);
  opacity: 0.6;
}

.reject-image-options {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  max-height: 260px;
  overflow-y: auto;
  padding: 8px;
  gap: 8px;
}

.reject-image-options :deep(.el-checkbox) {
  padding: 8px 12px;
  border-radius: 8px;
  transition: background 0.2s ease;
}

.reject-image-options :deep(.el-checkbox:hover) {
  background: var(--el-fill-color-light);
}

.reject-reason-list {
  display: grid;
  gap: 14px;
  max-height: 360px;
  overflow-y: auto;
  padding-right: 4px;
}

.reject-reason-list :deep(.el-form-item) {
  margin-bottom: 0;
  padding: 12px;
  border: 1px solid var(--el-border-color-lighter);
  border-radius: 8px;
  background: var(--el-fill-color-blank);
}

.reject-reason-list :deep(.el-form-item__label) {
  color: #2C5F4F;
  font-weight: 700;
}

.metadata-edit-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 0 20px;
}

.status-pill {
  display: inline-flex;
  align-items: center;
  padding: 4px 12px;
  border-radius: 16px;
  font-size: 12px;
  font-weight: 600;
  white-space: nowrap;
}

.status-pill[data-status="pending"] {
  background: var(--el-color-info-light-9);
  color: var(--el-color-info-dark-2);
  border: 1px solid var(--el-color-info-light-7);
}

.status-pill[data-status="reviewing"] {
  background: var(--el-color-warning-light-9);
  color: var(--el-color-warning-dark-2);
  border: 1px solid var(--el-color-warning-light-7);
}

.status-pill[data-status="passed"] {
  background: var(--el-color-success-light-9);
  color: var(--el-color-success-dark-2);
  border: 1px solid var(--el-color-success-light-7);
}

/* 响应式设计 - 新布局 */
@media (min-width: 1920px) {
  .qc-workbench-redesign {
    grid-template-columns: minmax(180px, 200px) 1fr minmax(300px, 340px);
  }
}

@media (max-width: 1680px) {
  .qc-workbench-redesign {
    grid-template-columns: 160px 1fr 280px;
  }

  .thumbnail-preview {
    height: 55px;
  }

  .folder-name {
    font-size: 13px;
  }
}

@media (max-width: 1440px) {
  .qc-workbench-redesign {
    grid-template-columns: 150px 1fr 260px;
  }

  .thumbnail-preview {
    height: 50px;
  }

  .action-buttons :deep(.el-button) {
    height: 36px;
    padding: 0 16px;
    font-size: 12px;
  }
}

@media (max-width: 1200px) {
  .qc-workbench-redesign {
    grid-template-columns: 140px 1fr 240px;
  }

  .image-toolbar {
    grid-template-columns: max-content minmax(0, 1fr);
  }

  .toolbar-right {
    gap: 4px 6px;
  }

  .toolbar-right :deep(.el-button) {
    padding: 0 6px;
    font-size: 10px;
  }

  .action-bar {
    flex-direction: column;
    align-items: stretch;
    gap: 8px;
    height: auto;
    max-height: none;
    padding: 8px 12px;
  }

  .breadcrumb {
    order: 2;
    justify-content: center;
  }

  .action-buttons {
    order: 1;
    justify-content: center;
    flex-wrap: wrap;
  }
}

@media (max-width: 1024px) {
  .qc-workbench-redesign {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr auto;
    height: auto;
    max-height: none;
  }

  .thumbnail-sidebar {
    grid-column: 1;
    grid-row: 1;
    flex-direction: row;
    overflow-x: auto;
    overflow-y: hidden;
    border-right: none;
    border-bottom: 1px solid #D4D9D6;
    max-height: 130px;
  }

  .sidebar-header {
    min-width: 150px;
    border-right: 1px solid #D4D9D6;
    border-bottom: none;
  }

  .thumbnail-list {
    flex-direction: row;
    padding: 12px;
    overflow-x: auto;
    overflow-y: hidden;
  }

  .thumbnail-item {
    min-width: 90px;
    flex-shrink: 0;
  }

  .main-preview-area {
    grid-row: 2;
    min-height: 400px;
  }

  .metadata-sidebar {
    grid-row: 3;
    grid-column: 1;
    border-left: none;
    border-top: 1px solid #D4D9D6;
    max-height: 400px;
  }

  .action-bar {
    display: none;
  }

  .metadata-content {
    padding-bottom: 80px;
  }
}

@media (max-width: 768px) {
  .image-toolbar {
    grid-template-columns: 1fr;
    gap: 6px;
    padding: 8px 10px;
  }

  .toolbar-left {
    width: 100%;
    flex-direction: row;
    align-items: center;
    gap: 4px;
  }

  .toolbar-right {
    justify-content: flex-start;
  }

  .current-filename {
    font-size: 12px;
  }

  .image-counter {
    font-size: 10px;
    padding: 2px 6px;
  }

  .nav-button {
    width: 36px;
    height: 36px;
    font-size: 16px;
  }

  .nav-prev {
    left: 10px;
  }

  .nav-next {
    right: 10px;
  }

  .thumbnail-preview {
    height: 45px;
  }
}

/* 已完成界面 - 响应式设计 */
@media (min-width: 1920px) {
  .completed-history-redesign {
    grid-template-columns: minmax(280px, 320px) 1fr minmax(300px, 340px);
  }
}

@media (max-width: 1680px) {
  .completed-history-redesign {
    grid-template-columns: 240px 1fr 280px;
  }
}

@media (max-width: 1440px) {
  .completed-history-redesign {
    grid-template-columns: 220px 1fr 260px;
  }

  .task-folder-name {
    font-size: 13px;
  }

  .total-count {
    font-size: 28px;
  }
}

@media (max-width: 1200px) {
  .completed-history-redesign {
    grid-template-columns: 200px 1fr 240px;
  }

  .completed-task-card {
    padding: 10px;
  }

  .image-chip-grid {
    grid-template-columns: repeat(auto-fill, minmax(32px, 1fr));
  }

  .image-chip {
    height: 28px;
    font-size: 10px;
  }
}

@media (max-width: 1024px) {
  .completed-history-redesign {
    grid-template-columns: 1fr;
    grid-template-rows: auto 1fr auto;
    height: auto;
    max-height: none;
  }

  .completed-sidebar {
    grid-row: 1;
    flex-direction: row;
    border-right: none;
    border-bottom: 1px solid #D4D9D6;
    max-height: 180px;
  }

  .completed-sidebar-header {
    min-width: 140px;
    border-right: 1px solid #D4D9D6;
    border-bottom: none;
  }

  .completed-task-list {
    flex-direction: row;
    overflow-x: auto;
    overflow-y: hidden;
  }

  .completed-task-card {
    min-width: 200px;
    flex-shrink: 0;
  }

  .completed-main-preview {
    grid-row: 2;
    min-height: 400px;
  }

  .completed-detail-sidebar {
    grid-row: 3;
    border-left: none;
    border-top: 1px solid #D4D9D6;
    max-height: 400px;
  }
}

@media (max-width: 768px) {
  .completed-sidebar-header {
    padding: 12px;
  }

  .total-count {
    font-size: 24px;
  }

  .completed-task-card {
    min-width: 180px;
  }

  .task-folder-name {
    font-size: 12px;
  }

  .image-chip-grid {
    grid-template-columns: repeat(auto-fill, minmax(28px, 1fr));
  }

  .image-chip {
    height: 26px;
    font-size: 9px;
  }
}

/* 保留旧布局的响应式 */
@media (max-width: 1280px) {
  .qc-workbench,
  .completed-detail {
    grid-template-columns: minmax(240px, 300px) minmax(0, 1fr);
  }

  .qc-workbench .metadata-qc-panel,
  .completed-metadata-panel {
    grid-column: 1 / -1;
    max-height: none;
  }
}

@media (max-width: 1100px) {
  .queue-heading,
  .qc-page-title {
    align-items: flex-start;
    flex-direction: column;
  }

  .queue-heading .el-alert {
    max-width: none;
  }

  .qc-workbench,
  .completed-history-layout,
  .completed-detail {
    grid-template-columns: 1fr;
    min-height: auto;
  }

  .image-nav-panel,
  .completed-list-panel,
  .metadata-qc-panel {
    max-height: none;
  }
}

@media (max-width: 640px) {
  .qc-summary-strip,
  .metadata-edit-grid {
    grid-template-columns: 1fr;
  }

  .qc-summary-item {
    min-height: 70px;
    padding: 16px 20px;
  }

  .qc-summary-item strong {
    font-size: 28px;
  }

  .review-actions {
    grid-template-columns: 1fr;
  }

  .metadata-list div {
    grid-template-columns: 1fr;
    gap: 6px;
  }

  .completed-task-row {
    flex-direction: column;
    gap: 12px;
    min-height: auto;
  }

  .completed-task-meta {
    align-items: flex-start;
    flex-direction: row;
  }
}

.eyebrow {
  display: block;
  margin-bottom: 4px;
  color: var(--el-text-color-secondary);
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.8px;
}

.muted {
  color: var(--el-text-color-secondary);
  font-size: 13px;
}

.qc-desk {
  position: relative;
  display: grid;
  grid-template-columns: minmax(170px, 210px) minmax(0, 1fr) minmax(290px, 340px);
  grid-template-rows: 58px minmax(0, 1fr) auto;
  height: calc(100vh - 236px);
  max-height: calc(100vh - 236px);
  min-height: 620px;
  overflow: hidden;
  border: 1px solid #d5dbd7;
  background: #eef1ef;
}

.qc-desk--compact {
  height: 100vh;
  max-height: 100vh;
  min-height: 0;
}

.qc-desk-header {
  grid-column: 1 / -1;
  grid-row: 1;
  display: grid;
  grid-template-columns: minmax(140px, 170px) minmax(0, 1fr) auto;
  align-items: center;
  gap: 12px;
  padding: 8px 10px;
  border-bottom: 1px solid #d5dbd7;
  background: #f7f8f6;
}

.qc-back-button {
  justify-content: flex-start;
  height: 40px;
  border-radius: 4px;
  font-weight: 700;
}

.qc-project-title {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 12px;
}

.qc-project-title strong {
  min-width: 0;
  overflow: hidden;
  color: #1a3329;
  font-size: 17px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.qc-project-title span {
  min-width: 0;
  overflow: hidden;
  color: #607267;
  font-size: 13px;
  font-weight: 700;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.qc-primary-actions {
  display: flex;
  align-items: center;
  gap: 8px;
}

.qc-primary-actions :deep(.el-button) {
  height: 38px;
  min-width: 84px;
  margin: 0;
  border-radius: 4px;
  font-weight: 800;
}

.qc-image-rail {
  grid-column: 1;
  grid-row: 2 / 4;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
  border-right: 1px solid #d5dbd7;
  background: #f7f8f6;
}

.qc-rail-summary {
  flex: 0 0 auto;
  display: grid;
  gap: 10px;
  padding: 12px 10px;
  border-bottom: 1px solid #d5dbd7;
}

.qc-rail-summary > div:first-child {
  display: grid;
  gap: 4px;
}

.qc-rail-summary span {
  color: #607267;
  font-size: 11px;
  font-weight: 700;
}

.qc-rail-summary strong {
  min-width: 0;
  overflow: hidden;
  color: #2c5f4f;
  font-size: 15px;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.qc-batch-tools {
  display: grid;
  gap: 4px;
  padding: 8px;
  border: 1px solid #d5dbd7;
  border-radius: 4px;
  background: #ffffff;
}

.qc-batch-tools div {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.qc-thumbnail-list {
  flex: 1 1 auto;
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 10px;
  overflow-x: hidden;
  overflow-y: auto;
}

.qc-thumbnail {
  position: relative;
  display: grid;
  grid-template-columns: 28px minmax(0, 1fr) 30px;
  grid-template-rows: 54px auto;
  gap: 6px 8px;
  width: 100%;
  min-height: 92px;
  padding: 8px;
  border: 2px solid transparent;
  border-radius: 6px;
  background: #ffffff;
  color: inherit;
  cursor: pointer;
  transition: border-color 0.2s ease, background 0.2s ease, box-shadow 0.2s ease;
}

.qc-thumbnail:hover,
.qc-thumbnail.active {
  border-color: #2c5f4f;
  background: #f4f8f6;
  box-shadow: 0 2px 8px rgba(44, 95, 79, 0.14);
}

.qc-thumbnail.selected {
  box-shadow: inset 0 0 0 1px #2c5f4f, 0 2px 8px rgba(44, 95, 79, 0.14);
}

.qc-thumbnail.unavailable {
  opacity: 0.56;
  background: #fff5f5;
}

.qc-thumbnail-check {
  grid-column: 1;
  grid-row: 1;
  align-self: start;
  justify-self: start;
  z-index: 2;
  display: inline-flex;
  width: 24px;
  height: 24px;
  padding-left: 2px;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 1px 4px rgba(26, 51, 41, 0.16);
}

.qc-thumbnail-check :deep(.el-checkbox__label) {
  display: none;
}

.qc-thumbnail-index {
  grid-column: 3;
  grid-row: 1;
  align-self: start;
  justify-self: end;
  padding: 2px 7px;
  border-radius: 4px;
  background: #4d7769;
  color: #ffffff;
  font-size: 11px;
  font-weight: 800;
}

.qc-thumbnail-preview {
  grid-column: 2;
  grid-row: 1;
  display: flex;
  align-items: center;
  justify-content: center;
  min-width: 0;
  min-height: 54px;
  border-radius: 5px;
  background: #f0f2f1;
  color: #9d90b8;
  font-size: 24px;
}

.qc-thumbnail-name {
  grid-column: 1 / -1;
  grid-row: 2;
  min-width: 0;
  overflow: hidden;
  color: #607267;
  font-size: 11px;
  font-weight: 600;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.qc-draft-flag,
.qc-draft-state {
  position: absolute;
  z-index: 3;
  right: 8px;
  max-width: calc(100% - 16px);
  overflow: hidden;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 800;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.qc-draft-flag {
  bottom: 28px;
  background: #fff7e6;
  color: #b76e00;
}

.qc-draft-state {
  left: 8px;
  right: auto;
  bottom: 28px;
  background: #e8f3ef;
  color: #2c5f4f;
}

.qc-separation-dot {
  position: absolute;
  right: 8px;
  bottom: 8px;
  z-index: 4;
}

.qc-preview-stage {
  grid-column: 2;
  grid-row: 2;
  position: relative;
  min-width: 0;
  min-height: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  overflow: hidden;
  background: #eef1ef;
}

.qc-preview-canvas {
  width: 100%;
  height: 100%;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 16px 24px 18px;
}

.qc-main-image {
  max-width: 100%;
  max-height: 100%;
  object-fit: contain;
  border-radius: 4px;
  box-shadow: 0 10px 30px rgba(18, 40, 31, 0.22);
  cursor: zoom-in;
}

.qc-nav-button {
  position: absolute;
  top: 50%;
  z-index: 6;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 48px;
  height: 48px;
  border: none;
  border-radius: 50%;
  background: #477262;
  color: #ffffff;
  cursor: pointer;
  box-shadow: 0 4px 14px rgba(18, 40, 31, 0.24);
  transform: translateY(-50%);
  transition: background 0.2s ease, transform 0.2s ease;
}

.qc-nav-button:hover {
  background: #2c5f4f;
  transform: translateY(-50%) scale(1.06);
}

.qc-nav-button--prev {
  left: 18px;
}

.qc-nav-button--next {
  right: 18px;
}

.qc-review-panel {
  grid-column: 3;
  grid-row: 2 / 4;
  min-height: 0;
  display: grid;
  grid-template-rows: auto minmax(0, 1fr);
  gap: 8px;
  overflow: hidden;
  border-left: 1px solid #d5dbd7;
  background: #f7f8f6;
}

.qc-comment-card,
.qc-info-card {
  min-width: 0;
  overflow: hidden;
  background: #f7f8f6;
}

.qc-comment-card {
  display: grid;
  gap: 10px;
  padding: 12px;
  border-bottom: 1px solid #d5dbd7;
}

.qc-info-card {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 12px;
  overflow-y: auto;
}

.qc-panel-heading {
  display: grid;
  gap: 4px;
}

.qc-panel-heading span {
  color: #607267;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: 0.7px;
  text-transform: uppercase;
}

.qc-panel-heading strong {
  min-width: 0;
  overflow-wrap: anywhere;
  color: #1a3329;
  font-size: 15px;
  font-weight: 800;
}

.qc-comment-box {
  display: grid;
  gap: 8px;
  min-height: 112px;
  padding: 10px;
  border: 1px solid #d5dbd7;
  border-radius: 4px;
  background: #ffffff;
}

.qc-comment-box p {
  margin: 0;
  color: #1a3329;
  font-size: 13px;
  font-weight: 800;
}

.qc-comment-box span {
  color: #607267;
  font-size: 12px;
  line-height: 1.4;
}

.qc-comment-box :deep(.el-textarea__inner) {
  min-height: 96px;
  border-radius: 4px;
  color: #1a3329;
  font-weight: 600;
  line-height: 1.45;
}

.qc-draft-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.qc-draft-actions :deep(.el-button),
.qc-comment-box :deep(.el-button),
.qc-edit-metadata {
  margin: 0;
  border-radius: 4px;
  font-weight: 700;
}

.qc-edit-metadata {
  width: 100%;
  min-height: 38px;
}

.qc-inline-metadata-form {
  display: grid;
  gap: 8px;
  min-width: 0;
}

.qc-inline-metadata-form :deep(.el-form-item) {
  margin-bottom: 0;
}

.qc-inline-metadata-form :deep(.el-form-item__label) {
  margin-bottom: 4px;
  color: #607267;
  font-size: 11px;
  font-weight: 800;
  line-height: 1.25;
}

.qc-inline-metadata-form :deep(.el-input__wrapper),
.qc-inline-metadata-form :deep(.el-select__wrapper) {
  min-height: 34px;
  border-radius: 4px;
}

.qc-inline-metadata-form :deep(.el-input__inner),
.qc-inline-metadata-form :deep(.el-select__placeholder) {
  min-width: 0;
  color: #1a3329;
  font-size: 12px;
  font-weight: 700;
}

.qc-inline-metadata-actions {
  position: sticky;
  bottom: -12px;
  z-index: 2;
  display: flex;
  justify-content: flex-end;
  padding: 10px 0 0;
  border-top: 1px solid #d5dbd7;
  background: #f7f8f6;
}

.qc-inline-metadata-actions :deep(.el-button) {
  min-width: 92px;
  margin: 0;
  border-radius: 4px;
  font-weight: 800;
}

.qc-metadata-summary {
  display: grid;
  gap: 8px;
  padding: 10px;
  border: 1px solid #d5dbd7;
  border-radius: 4px;
  background: #eef1ef;
}

.qc-metadata-summary div {
  display: grid;
  gap: 3px;
}

.qc-metadata-summary span {
  color: #607267;
  font-size: 11px;
  font-weight: 700;
}

.qc-metadata-summary strong {
  min-width: 0;
  overflow-wrap: anywhere;
  color: #1a3329;
  font-size: 13px;
  font-weight: 800;
}

.qc-metadata-details {
  border: 1px solid #d5dbd7;
  border-radius: 4px;
  background: #ffffff;
}

.qc-metadata-details summary {
  padding: 9px 10px;
  border-bottom: 1px solid #d5dbd7;
  background: #eef1ef;
  color: #2c5f4f;
  cursor: pointer;
  font-size: 12px;
  font-weight: 800;
}

.qc-metadata-group {
  padding: 10px;
  border-bottom: 1px solid #e5e9e6;
}

.qc-metadata-group:last-child {
  border-bottom: none;
}

.qc-metadata-group h4 {
  margin: 0 0 8px;
  color: #2c5f4f;
  font-size: 13px;
  font-weight: 800;
}

.qc-metadata-group dl {
  display: grid;
  gap: 7px;
  margin: 0;
}

.qc-metadata-group dl div {
  display: grid;
  grid-template-columns: minmax(72px, 0.42fr) minmax(0, 0.58fr);
  gap: 8px;
  align-items: start;
}

.qc-metadata-group dt {
  color: #607267;
  font-size: 11px;
  font-weight: 700;
}

.qc-metadata-group dd {
  min-width: 0;
  margin: 0;
  overflow-wrap: anywhere;
  color: #1a3329;
  font-size: 12px;
  font-weight: 800;
}

.qc-tool-strip {
  grid-column: 2;
  grid-row: 3;
  min-width: 0;
  display: grid;
  gap: 8px;
  min-height: 58px;
  padding: 10px 14px;
  overflow: visible;
  border-top: 2px solid #2c5f4f;
  background: #f7f8f6;
}

.qc-tool-row {
  min-width: 0;
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.qc-tool-strip :deep(.el-button) {
  flex: 0 0 auto;
  height: 38px;
  margin: 0;
  border-radius: 4px;
  font-size: 12px;
  font-weight: 800;
}

:global(.qc-tool-popover) {
  border-color: var(--lw-line);
  border-radius: 8px;
  background: rgba(255, 255, 255, 0.96);
  box-shadow: 0 18px 50px rgba(19, 48, 32, 0.12);
}

:global(.qc-tool-popover .qc-more-tool-grid) {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 8px;
}

:global(.qc-tool-popover .el-button) {
  width: 100%;
  height: 36px;
  margin: 0;
  border-radius: 6px;
  color: var(--lw-dark);
  font-weight: 800;
}

.qc-desk {
  border-color: var(--lw-line);
  background:
    linear-gradient(180deg, rgba(245, 238, 219, 0.72) 0, rgba(249, 247, 247, 0.98) 180px),
    var(--lw-sea-salt);
  box-shadow: inset 0 0 0 1px rgba(255, 255, 255, 0.72);
}

.qc-desk-header,
.qc-image-rail,
.qc-review-panel,
.qc-comment-card,
.qc-info-card,
.qc-tool-strip,
.qc-inline-metadata-actions {
  border-color: var(--lw-line);
  background: rgba(255, 255, 255, 0.76);
}

.qc-desk-header {
  background: rgba(245, 238, 219, 0.9);
}

.qc-project-title strong,
.qc-panel-heading strong,
.qc-comment-box p,
.qc-metadata-summary strong,
.qc-metadata-group dd,
.qc-inline-metadata-form :deep(.el-input__inner),
.qc-inline-metadata-form :deep(.el-select__placeholder) {
  color: var(--lw-dark);
}

.qc-project-title span,
.qc-rail-summary span,
.qc-thumbnail-name,
.qc-panel-heading span,
.qc-comment-box span,
.qc-inline-metadata-form :deep(.el-form-item__label),
.qc-metadata-summary span,
.qc-metadata-group dt {
  color: var(--lw-muted);
}

.qc-rail-summary strong,
.qc-metadata-details summary,
.qc-metadata-group h4 {
  color: var(--lw-green);
}

.qc-back-button.el-button,
.qc-primary-actions :deep(.el-button),
.qc-tool-strip :deep(.el-button),
.qc-inline-metadata-actions :deep(.el-button),
.qc-draft-actions :deep(.el-button) {
  border-radius: 6px;
}

.qc-back-button.el-button {
  border-color: var(--lw-line);
  background: rgba(255, 255, 255, 0.72);
  color: var(--lw-dark);
  box-shadow: 0 8px 18px rgba(19, 48, 32, 0.06);
}

.qc-back-button.el-button:hover,
.qc-back-button.el-button:focus {
  border-color: var(--lw-line-strong);
  background: var(--lw-sea-salt);
  color: var(--lw-green);
}

.qc-batch-tools,
.qc-thumbnail,
.qc-comment-box,
.qc-metadata-summary,
.qc-metadata-details,
.qc-inline-metadata-form :deep(.el-input__wrapper),
.qc-inline-metadata-form :deep(.el-select__wrapper),
.qc-comment-box :deep(.el-textarea__inner) {
  border-color: var(--lw-line);
  background: var(--lw-white);
  box-shadow: 0 8px 22px rgba(19, 48, 32, 0.035);
}

.qc-thumbnail:hover,
.qc-thumbnail.active {
  border-color: var(--lw-green);
  background: rgba(4, 98, 65, 0.06);
  box-shadow: 0 10px 24px rgba(19, 48, 32, 0.09);
}

.qc-thumbnail.selected {
  box-shadow: inset 0 0 0 1px var(--lw-green), 0 10px 24px rgba(19, 48, 32, 0.09);
}

.qc-thumbnail-index,
.qc-nav-button {
  background: var(--lw-green);
  color: var(--lw-white);
}

.qc-nav-button {
  box-shadow: 0 10px 24px rgba(19, 48, 32, 0.16);
}

.qc-nav-button:hover {
  background: #034b32;
}

.qc-thumbnail-preview,
.qc-metadata-summary,
.qc-metadata-details summary {
  background: var(--lw-sea-salt);
}

.qc-draft-flag {
  background: var(--lw-saffron-soft);
  color: var(--lw-dark);
}

.qc-draft-state {
  background: var(--lw-green-soft);
  color: var(--lw-green);
}

.qc-thumbnail.unavailable {
  background: var(--lw-danger-soft);
}

.qc-preview-stage {
  background:
    linear-gradient(180deg, rgba(249, 247, 247, 0.92), rgba(255, 255, 255, 0.78)),
    var(--lw-sea-salt);
}

.qc-main-image {
  border-radius: 6px;
  box-shadow: 0 18px 50px rgba(19, 48, 32, 0.16);
}

.qc-tool-strip {
  border-top-color: var(--lw-green);
}

.qc-primary-actions :deep(.el-button--success),
.qc-inline-metadata-actions :deep(.el-button--primary:not(.is-disabled)) {
  --el-button-bg-color: var(--lw-green);
  --el-button-border-color: var(--lw-green);
  --el-button-hover-bg-color: #034b32;
  --el-button-hover-border-color: #034b32;
  --el-button-active-bg-color: #034b32;
  --el-button-active-border-color: #034b32;
}

.qc-primary-actions :deep(.el-button--danger) {
  --el-button-bg-color: var(--lw-danger);
  --el-button-border-color: var(--lw-danger);
  --el-button-hover-bg-color: #c84c3b;
  --el-button-hover-border-color: #c84c3b;
}

.qc-tool-strip :deep(.el-button:not(.el-button--primary):not(.el-button--danger):not(.el-button--success)),
.qc-draft-actions :deep(.el-button:not(.el-button--primary):not(.el-button--danger):not(.el-button--success)) {
  background: rgba(255, 255, 255, 0.78);
  color: var(--lw-dark);
}

.qc-tool-strip :deep(.el-button:not(.el-button--primary):not(.el-button--danger):not(.el-button--success):hover),
.qc-draft-actions :deep(.el-button:not(.el-button--primary):not(.el-button--danger):not(.el-button--success):hover) {
  border-color: var(--lw-saffron);
  background: var(--lw-saffron-soft);
  color: var(--lw-dark);
}

@media (min-width: 1920px) {
  .qc-desk {
    grid-template-columns: minmax(190px, 230px) minmax(0, 1fr) minmax(320px, 360px);
  }
}

@media (max-width: 1440px) {
  .qc-desk {
    grid-template-columns: 180px minmax(0, 1fr) 286px;
  }

  .qc-project-title span {
    font-size: 12px;
  }
}

@media (max-width: 1200px) {
  .qc-desk {
    grid-template-columns: 160px minmax(0, 1fr) 250px;
  }

  .qc-primary-actions :deep(.el-button) {
    min-width: 72px;
    padding: 0 10px;
  }
}

@media (max-width: 1024px) {
  .qc-desk,
  .qc-desk--compact {
    grid-template-columns: 1fr;
    grid-template-rows: auto auto minmax(420px, 1fr) auto auto;
    height: auto;
    max-height: none;
    min-height: 0;
    overflow: visible;
  }

  .qc-desk-header {
    grid-column: 1;
    grid-row: 1;
    grid-template-columns: 1fr;
    align-items: stretch;
  }

  .qc-project-title,
  .qc-primary-actions {
    justify-content: center;
  }

  .qc-image-rail {
    grid-column: 1;
    grid-row: 2;
    border-right: none;
    border-bottom: 1px solid #d5dbd7;
  }

  .qc-thumbnail-list {
    flex-direction: row;
    overflow-x: auto;
    overflow-y: hidden;
  }

  .qc-thumbnail {
    width: 150px;
    flex: 0 0 150px;
  }

  .qc-preview-stage {
    grid-column: 1;
    grid-row: 3;
    min-height: 420px;
  }

  .qc-tool-strip {
    grid-column: 1;
    grid-row: 4;
  }

  .qc-review-panel {
    grid-column: 1;
    grid-row: 5;
    grid-template-rows: auto auto;
    border-left: none;
    border-top: 1px solid #d5dbd7;
    overflow: visible;
  }
}

@media (max-width: 640px) {
  .qc-desk-header {
    padding: 8px;
  }

  .qc-project-title {
    align-items: flex-start;
    flex-direction: column;
    gap: 4px;
  }

  .qc-primary-actions {
    display: grid;
    grid-template-columns: repeat(3, minmax(0, 1fr));
  }

  .qc-primary-actions :deep(.el-button) {
    width: 100%;
  }

  .qc-preview-canvas {
    padding: 12px;
  }

  .qc-nav-button {
    width: 40px;
    height: 40px;
  }

  .qc-metadata-group dl div {
    grid-template-columns: 1fr;
    gap: 3px;
  }
}

:deep(.el-loading-spinner) {
  margin-top: -25px;
}

:deep(.el-loading-spinner .circular) {
  width: 50px;
  height: 50px;
}
</style>
