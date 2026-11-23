from __future__ import annotations

from io import BytesIO
import zipfile
import unittest

from engine.rag.upload_validator import UploadValidationError, validate_upload


def _docx(entries: dict[str, bytes]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, value in entries.items():
            archive.writestr(name, value)
    return output.getvalue()


class UploadValidatorTests(unittest.TestCase):
    def test_rejects_extension_signature_mismatch(self):
        with self.assertRaisesRegex(UploadValidationError, "signature"):
            validate_upload("brief.pdf", b"not a PDF")

    def test_rejects_zip_path_traversal(self):
        content = _docx({"[Content_Types].xml": b"types",
                         "word/document.xml": b"document",
                         "../outside.txt": b"no extraction allowed"})
        with self.assertRaisesRegex(UploadValidationError, "unsafe path"):
            validate_upload("brief.docx", content)

    def test_rejects_high_expansion_ratio_office_archives(self):
        content = _docx({"[Content_Types].xml": b"types",
                         "word/document.xml": b"x" * 100_000})
        with self.assertRaisesRegex(UploadValidationError, "compression ratio"):
            validate_upload("brief.docx", content)

    def test_accepts_valid_small_office_package_and_utf8_text(self):
        content = _docx({"[Content_Types].xml": b"types",
                         "word/document.xml": b"document text"})
        self.assertEqual(validate_upload("brief.docx", content), ".docx")
        self.assertEqual(validate_upload("brief.txt", "hello\nनमस्ते".encode()), ".txt")


if __name__ == "__main__":
    unittest.main()
