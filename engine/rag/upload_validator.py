"""Small, bounded checks before untrusted documents reach format parsers."""
from __future__ import annotations

from io import BytesIO
from pathlib import PurePosixPath
import zipfile

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_ARCHIVE_ENTRIES = 2_000
MAX_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_MEMBER_BYTES = 24 * 1024 * 1024
MAX_COMPRESSION_RATIO = 100
MAX_PDF_PAGES = 500

SUPPORTED_SUFFIXES = {".pdf", ".docx", ".txt", ".md", ".csv", ".xlsx", ".xlsm"}


class UploadValidationError(ValueError):
    """The upload is unsupported, malformed, or exceeds a resource bound."""


def _check_archive(content: bytes, suffix: str) -> None:
    try:
        with zipfile.ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if not entries or len(entries) > MAX_ARCHIVE_ENTRIES:
                raise UploadValidationError("document archive has an invalid entry count")
            total = 0
            names = set()
            for entry in entries:
                path = PurePosixPath(entry.filename.replace("\\", "/"))
                if path.is_absolute() or ".." in path.parts:
                    raise UploadValidationError("document archive contains an unsafe path")
                if entry.flag_bits & 0x1:
                    raise UploadValidationError("encrypted document archives are not supported")
                total += entry.file_size
                if entry.file_size > MAX_MEMBER_BYTES:
                    raise UploadValidationError("document archive member exceeds the size limit")
                if entry.file_size and entry.compress_size == 0:
                    raise UploadValidationError("document archive has an invalid compression ratio")
                if entry.compress_size and entry.file_size / entry.compress_size > MAX_COMPRESSION_RATIO:
                    raise UploadValidationError("document archive compression ratio exceeds the limit")
                names.add(entry.filename)
            if total > MAX_UNCOMPRESSED_BYTES:
                raise UploadValidationError("document archive expands beyond the 64 MiB limit")
            required = ({"[Content_Types].xml", "word/document.xml"}
                        if suffix == ".docx" else {"[Content_Types].xml", "xl/workbook.xml"})
            if not required.issubset(names):
                raise UploadValidationError("archive does not match the declared Office document type")
    except zipfile.BadZipFile as exc:
        raise UploadValidationError("Office documents must be valid ZIP packages") from exc


def validate_upload(filename: str, content: bytes) -> str:
    """Validate a bounded in-memory upload and return its normalized suffix."""
    suffix = PurePosixPath((filename or "").replace("\\", "/")).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise UploadValidationError("unsupported file type")
    if not content:
        raise UploadValidationError("uploaded file is empty")
    if len(content) > MAX_UPLOAD_BYTES:
        raise UploadValidationError("file exceeds the 10 MiB upload limit")
    if suffix == ".pdf":
        if not content.startswith(b"%PDF-"):
            raise UploadValidationError("PDF signature does not match the file extension")
        try:
            from pypdf import PdfReader
            reader = PdfReader(BytesIO(content), strict=True)
            if len(reader.pages) > MAX_PDF_PAGES:
                raise UploadValidationError("PDF exceeds the 500 page limit")
        except UploadValidationError:
            raise
        except Exception as exc:  # noqa: BLE001
            raise UploadValidationError("PDF file is malformed or encrypted") from exc
    elif suffix in {".docx", ".xlsx", ".xlsm"}:
        if not content.startswith((b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")):
            raise UploadValidationError("Office archive signature does not match the file extension")
        _check_archive(content, ".xlsx" if suffix == ".xlsm" else suffix)
    else:
        if b"\x00" in content:
            raise UploadValidationError("text uploads cannot contain NUL bytes")
        try:
            content.decode("utf-8-sig")
        except UnicodeDecodeError as exc:
            raise UploadValidationError("text uploads must use UTF-8 encoding") from exc
    return suffix
