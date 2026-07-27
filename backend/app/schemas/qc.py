from datetime import datetime

from pydantic import BaseModel, Field


class FolderMetadataVO(BaseModel):
    folderId: int
    boxId: int
    boxName: str
    projectId: int | None = None
    projectName: str | None = None
    folderName: str
    folderSeq: int
    deviceId: str
    coverTag: str | None = None
    imageTags: str | None = None
    title: str | None = None
    volume: str | None = None
    startDate: datetime | None = None
    endDate: datetime | None = None
    archivalRefNo: str | None = None
    recordType: str | None = None
    place: str | None = None
    language: str | None = None
    recordCustodian: str | None = None
    captureOperatorId: str | None = None
    captureOperatorName: str | None = None
    digitizingEntity: str | None = None
    sourceCreatedAt: datetime | None = None
    sourceUpdatedAt: datetime | None = None


class MetadataQcImageVO(BaseModel):
    id: int
    filename: str
    available: bool
    previewUrl: str
    draftState: str | None = None
    separationStart: bool = False


class MetadataTemplateFieldVO(BaseModel):
    key: str
    label: str
    input: str
    mandatory: bool = False
    exported: bool = False
    options: list[str] = Field(default_factory=list)
    value: str | None = None


class MetadataTemplateVO(BaseModel):
    fields: list[MetadataTemplateFieldVO] = Field(default_factory=list)
    titleRecordTypeMap: dict[str, str] = Field(default_factory=dict)


class MetadataQcTaskVO(BaseModel):
    id: int
    status: str
    sourceHash: str
    hasDraft: bool = False
    draftImageIds: list[int] = Field(default_factory=list)
    draftMetadataDirty: bool = False
    assignedTo: int | None = None
    claimedAt: datetime | None = None
    submittedAt: datetime
    metadata: FolderMetadataVO
    metadataTemplate: MetadataTemplateVO
    imageCount: int
    imageAvailable: bool
    images: list[MetadataQcImageVO] = Field(default_factory=list)


class ReviewRequest(BaseModel):
    sourceHash: str = Field(min_length=64, max_length=64)
    comment: str | None = Field(default=None, max_length=2000)


class CropImageRequest(BaseModel):
    sourceHash: str = Field(min_length=64, max_length=64)
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    previewWidth: int | None = Field(default=None, gt=0)
    previewHeight: int | None = Field(default=None, gt=0)


class LuminanceRequest(ReviewRequest):
    pass


class BatchLuminanceRequest(ReviewRequest):
    imageIds: list[int] = Field(min_length=1)


class RotateImageRequest(ReviewRequest):
    degrees: int


class BatchRotateRequest(ReviewRequest):
    imageIds: list[int] = Field(min_length=1)
    degrees: int


class DeskewImageRequest(ReviewRequest):
    degrees: int


class ReorderImagesRequest(ReviewRequest):
    imageIds: list[int] = Field(min_length=1)


class SeparationMarkersRequest(ReviewRequest):
    firstPageImageIds: list[int] = Field(default_factory=list)


class RejectedImageRequest(BaseModel):
    imageId: int
    rejectReason: str = Field(min_length=1, max_length=10000)


class RejectRequest(ReviewRequest):
    rejectReason: str | None = Field(default=None, max_length=10000)
    imageIds: list[int] = Field(default_factory=list)
    rejectedImages: list[RejectedImageRequest] = Field(default_factory=list)


class EditableFolderMetadata(BaseModel):
    folderName: str | None = Field(default=None, max_length=255)
    coverTag: str | None = Field(default=None, max_length=255)
    imageTags: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    volume: str | None = Field(default=None, max_length=255)
    startDate: datetime | None = None
    endDate: datetime | None = None
    archivalRefNo: str | None = Field(default=None, max_length=255)
    recordType: str | None = Field(default=None, max_length=255)
    place: str | None = Field(default=None, max_length=255)
    language: str | None = Field(default=None, max_length=255)
    recordCustodian: str | None = Field(default=None, max_length=255)
    captureOperatorId: str | None = Field(default=None, max_length=255)
    captureOperatorName: str | None = Field(default=None, max_length=255)
    digitizingEntity: str | None = Field(default=None, max_length=255)


class MetadataUpdateRequest(BaseModel):
    sourceHash: str = Field(min_length=64, max_length=64)
    metadata: EditableFolderMetadata
