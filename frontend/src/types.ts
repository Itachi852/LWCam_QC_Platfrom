export interface ApiResponse<T> {
  code: number
  message: string
  data: T
}

export interface PageResult<T> {
  records: T[]
  total: number
  page: number
  size: number
}

export interface UserInfo {
  id: number
  userId: string
  role: string
  status: string
  homePath: string
  mustChangePassword: boolean
}

export interface AuthResponse {
  token: string
  user: UserInfo
}

export interface UserAdmin {
  id: number
  userId: string
  role: string
  status: string
  projectIds: number[]
  projectNames: string[]
  createdAt: string
  lastLoginAt?: string
  mustChangePassword: boolean
}

export interface ProjectOption {
  id: number
  projectId: string
  projectName: string
}

export interface AdminQcTask {
  folderId: number
  folderName: string
  folderSeq: number
  boxId: number
  boxName: string
  projectId?: number
  projectCode?: string
  projectName?: string
  reviewerId?: number
  reviewerUserId: string
  imageCount: number
  claimedAt?: string
  updatedAt: string
}

export interface StatsOverview {
  todayNewTasks: number
  todayCompletedTasks: number
  todayQcPassRate: number
  totalUsers: number
  totalTasks: number
  pendingClaimTasks: number
  taskTrend: Array<Record<string, unknown>>
  taskStatusDistribution: Array<{ status: string; label: string; count: number }>
  reviewerWorkload: Array<{
    reviewerId: number
    reviewerName: string
    total: number
    approved: number
    rejected: number
  }>
}

export interface MetadataRecord {
  folderId: number
  boxId: number
  boxName: string
  projectId?: number
  projectName?: string
  folderName: string
  folderSeq: number
  deviceId: string
  coverTag?: string
  imageTags?: string
  title?: string
  volume?: string
  startDate?: string
  endDate?: string
  archivalRefNo?: string
  recordType?: string
  place?: string
  language?: string
  recordCustodian?: string
  captureOperatorId?: string
  captureOperatorName?: string
  digitizingEntity?: string
  sourceCreatedAt?: string
  sourceUpdatedAt?: string
}

export interface EditableFolderMetadata {
  folderName?: string | null
  coverTag?: string | null
  imageTags?: string | null
  title?: string | null
  volume?: string | null
  startDate?: string | null
  endDate?: string | null
  archivalRefNo?: string | null
  recordType?: string | null
  place?: string | null
  language?: string | null
  recordCustodian?: string | null
  captureOperatorId?: string | null
  captureOperatorName?: string | null
  digitizingEntity?: string | null
}

export interface MetadataQcImage {
  id: number
  filename: string
  available: boolean
  previewUrl: string
  draftState?: string | null
  separationStart?: boolean
}

export interface MetadataTemplateField {
  key: keyof EditableFolderMetadata
  label: string
  input: 'text' | 'select' | 'fixed'
  mandatory: boolean
  exported: boolean
  options: string[]
  value?: string | null
}

export interface MetadataTemplate {
  fields: MetadataTemplateField[]
  titleRecordTypeMap: Record<string, string>
}

export interface MetadataQcTask {
  id: number
  status: string
  sourceHash: string
  hasDraft: boolean
  draftImageIds: number[]
  draftMetadataDirty: boolean
  assignedTo?: number
  claimedAt?: string
  submittedAt: string
  metadata: MetadataRecord
  metadataTemplate: MetadataTemplate
  imageCount: number
  imageAvailable: boolean
  images: MetadataQcImage[]
}

export interface CropRect {
  x: number
  y: number
  width: number
  height: number
  previewWidth?: number
  previewHeight?: number
}

export interface RejectedImagePayload {
  imageId: number
  rejectReason: string
}
