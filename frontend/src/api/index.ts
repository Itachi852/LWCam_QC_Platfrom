import request from '@/api/client'
import type {
  AdminQcTask,
  ApiResponse,
  AuthResponse,
  EditableFolderMetadata,
  CropRect,
  MetadataQcTask,
  PageResult,
  ProjectOption,
  RejectedImagePayload,
  StatsOverview,
  UserAdmin,
  UserInfo,
} from '@/types'

export const authApi = {
  login: (data: { username: string; password: string }) => request.post<ApiResponse<AuthResponse>>('/auth/login', data),
  me: () => request.get<ApiResponse<UserInfo>>('/auth/me'),
  changePassword: (oldPassword: string, newPassword: string) =>
    request.put<ApiResponse<UserInfo>>('/auth/password', { oldPassword, newPassword }),
}

export const adminApi = {
  stats: () => request.get<ApiResponse<StatsOverview>>('/admin/stats/overview'),
  users: (params: Record<string, unknown>) => request.get<ApiResponse<PageResult<UserAdmin>>>('/admin/users', { params }),
  createUser: (data: { userId: string; password: string; role: string; projectIds: number[] }) =>
    request.post<ApiResponse<UserAdmin>>('/admin/users', data),
  updateUser: (id: number, data: { role: string; status: string; projectIds: number[] }) =>
    request.put<ApiResponse<UserAdmin>>(`/admin/users/${id}`, data),
  deleteUser: (id: number) => request.delete<ApiResponse<void>>(`/admin/users/${id}`),
  resetPassword: (id: number, newPassword: string) =>
    request.put<ApiResponse<void>>(`/admin/users/${id}/password`, { newPassword }),
  projectOptions: () => request.get<ApiResponse<ProjectOption[]>>('/admin/projects/options'),
  qcTasks: (params: Record<string, unknown>) =>
    request.get<ApiResponse<PageResult<AdminQcTask>>>('/admin/qc-tasks', { params }),
  releaseQcTask: (folderId: number) =>
    request.post<ApiResponse<void>>(`/admin/qc-tasks/${folderId}/release`),
}

export const qcApi = {
  tasks: (params: Record<string, unknown>) =>
    request.get<ApiResponse<PageResult<MetadataQcTask>>>('/qc/metadata-tasks', { params }),
  detail: (id: number) =>
    request.get<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}`),
  claimNext: () =>
    request.post<ApiResponse<MetadataQcTask>>('/qc/metadata-tasks/claim-next'),
  claim: (id: number) =>
    request.post<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/claim`),
  release: (id: number) =>
    request.post<ApiResponse<void>>(`/qc/metadata-tasks/${id}/release`),
  approve: (id: number, sourceHash: string, comment?: string) =>
    request.post<ApiResponse<void>>(`/qc/metadata-tasks/${id}/approve`, { sourceHash, comment }),
  reject: (id: number, sourceHash: string, rejectedImages: RejectedImagePayload[], comment?: string) =>
    request.post<ApiResponse<void>>(`/qc/metadata-tasks/${id}/reject`, { sourceHash, rejectedImages, comment }),
  updateMetadata: (id: number, sourceHash: string, metadata: EditableFolderMetadata) =>
    request.put<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/metadata`, { sourceHash, metadata }),
  luminanceImage: (id: number, imageId: number, sourceHash: string) =>
    request.post<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/images/${imageId}/luminance`, { sourceHash }),
  luminanceBatch: (id: number, sourceHash: string, imageIds: number[]) =>
    request.post<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/images/luminance-batch`, { sourceHash, imageIds }),
  replaceImage: (id: number, imageId: number, sourceHash: string, file: File) => {
    const form = new FormData()
    form.append('sourceHash', sourceHash)
    form.append('file', file)
    return request.post<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/images/${imageId}/replace`, form)
  },
  insertBeforeImage: (id: number, imageId: number, sourceHash: string, file: File) => {
    const form = new FormData()
    form.append('sourceHash', sourceHash)
    form.append('file', file)
    return request.post<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/images/${imageId}/insert-before`, form)
  },
  deleteImage: (id: number, imageId: number, sourceHash: string) =>
    request.post<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/images/${imageId}/delete`, { sourceHash }),
  rotateImage: (id: number, imageId: number, sourceHash: string, degrees: number) =>
    request.post<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/images/${imageId}/rotate`, { sourceHash, degrees }),
  rotateBatch: (id: number, sourceHash: string, imageIds: number[], degrees: number) =>
    request.post<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/images/rotate-batch`, { sourceHash, imageIds, degrees }),
  deskewImage: (id: number, imageId: number, sourceHash: string, degrees: number) =>
    request.post<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/images/${imageId}/deskew`, { sourceHash, degrees }),
  reorderImages: (id: number, sourceHash: string, imageIds: number[]) =>
    request.post<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/images/reorder`, { sourceHash, imageIds }),
  restoreOriginal: (id: number, imageId: number, sourceHash: string) =>
    request.post<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/images/${imageId}/restore-original`, { sourceHash }),
  undoDraft: (id: number) =>
    request.post<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/draft/undo`),
  redoDraft: (id: number) =>
    request.post<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/draft/redo`),
  updateSeparationMarkers: (id: number, sourceHash: string, firstPageImageIds: number[]) =>
    request.put<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/separation-markers`, { sourceHash, firstPageImageIds }),
  saveDraft: (id: number, sourceHash: string) =>
    request.post<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/draft/save`, { sourceHash }),
  discardDraft: (id: number) =>
    request.post<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/draft/discard`),
  cropImage: (id: number, imageId: number, sourceHash: string, crop: CropRect) =>
    request.post<ApiResponse<MetadataQcTask>>(`/qc/metadata-tasks/${id}/images/${imageId}/crop`, {
      sourceHash,
      ...crop,
    }),
}
