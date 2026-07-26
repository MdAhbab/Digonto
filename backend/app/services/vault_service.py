"""Vault, Prohori, and the three document-adjacent agents: Bicharok
(rejection autopsy), Lekhok (statement forensics), Dalil (contract auditor).

api_contract.md section 8 and section 11.

Four rules govern the upload path, and each one is enforced here rather than
trusted to the caller:

1. **The client's `Content-Type` is a hint, never a fact.** Every upload is
   sniffed from its magic bytes and the sniffed type is what gets stored,
   what gets shown, and what decides whether the file can be read at all. A
   `.exe` renamed to `.png` is refused with 415.
2. **Nothing reaches a vision agent as a PDF.** `bicharok.analyse_rejection`
   and `dalil.audit_contract` both raise `ValueError` on a non-image, by
   design: they will not guess at contents they cannot see. Page 1 is
   rasterised to PNG here, in the one place that holds the decrypted bytes.
   If rasterisation fails the document is recorded `failed` with a bilingual
   reason, because a student who sees "failed" and nothing else cannot act.
3. **Extracted values are encrypted, and comparable anyway.** Each field
   value goes into `document_fields.value_enc` under the document's own DEK,
   alongside `value_hash` from `normalised_value_hash`, so Prohori can prove
   the name on a passport and the name on a bank statement differ without
   ever decrypting either.
4. **Deleting means shredding.** The ciphertext is overwritten before it is
   unlinked and the wrapped DEK is destroyed in the same breath, so a
   database backup that outlives the volume carries nothing usable.

Document content never leaves the machine: every model call below either
receives already-decrypted bytes for a local vision pass, or a
`contains_user_documents=True` request through `ModelRouter`, which raises
rather than route to a remote provider.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import re
import secrets
import struct
import zlib
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Final, Sequence

from app.agents.bicharok import analyse_rejection
from app.agents.dalil import audit_contract
from app.agents.lekhok import analyse_statement
from app.agents.prohori import run_audit
from app.config import Settings
from app.errors import AppError, NotFound, PayloadTooLarge, ValidationProblem
from app.events.bus import EventBus, EventType
from app.llm.router import LLMRequest, ModelRouter, TaskKind
from app.repositories.audit_repo import AuditRepo
from app.repositories.document_repo import DocumentRepo
from app.repositories.profile_repo import ProfileRepo
from app.repositories.target_repo import TargetRepo
from app.security.vault_crypto import (
    decrypt_file,
    encrypt_field,
    encrypt_file,
    normalised_value_hash,
    unwrap_dek,
)

log = logging.getLogger(__name__)

_ACCEPTED_MIME: Final[frozenset[str]] = frozenset(
    {"application/pdf", "image/jpeg", "image/png", "image/heic"}
)

# What the Gemma vision pass can actually be handed. HEIC is accepted for
# storage (an iPhone photo of a document is the single most common upload
# from a phone) but neither pdfium nor the served model decodes it, so a HEIC
# document is stored, encrypted, and marked `failed` for extraction with a
# reason that tells the student exactly what to do about it.
_RASTERISABLE_MIME: Final[frozenset[str]] = frozenset({"image/png", "image/jpeg"})

# Long edge of the image handed to the model. The vision tower downsamples
# anyway; rendering a 300 DPI A4 page at full size only costs base64 bytes.
_RASTER_MAX_EDGE: Final[int] = 1600
_PDF_RASTER_MIN_SCALE: Final[float] = 1.0

_UPLOAD_CHUNK: Final[int] = 64 * 1024


class UnsupportedMedia(AppError):
    """415. Distinct from 422: the request was well formed, the bytes were
    simply not a document this vault can hold. `app/errors.py` carries the
    status codes the contract names; this one is local to the upload path."""

    status_code = 415
    type_slug = "unsupported-media-type"
    title = "Unsupported media type"


class RasterError(RuntimeError):
    """Page 1 could not be turned into an image. Carries bilingual copy so
    the failure reaches the student in their own language."""

    def __init__(self, detail_en: str, detail_bn: str) -> None:
        self.detail_en = detail_en
        self.detail_bn = detail_bn
        super().__init__(detail_en)


# --- magic-byte sniffing ----------------------------------------------------


def sniff_mime(data: bytes) -> str | None:
    """The real type of `data`, from its leading bytes.

    Returns None when nothing recognisable is there. Deliberately narrow: it
    reports what it is sure of and lets the caller refuse everything else,
    rather than trying to name every format in the world.
    """
    if len(data) < 12:
        return None
    if data.startswith(b"%PDF-"):
        return "application/pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[4:8] == b"ftyp":
        brand = data[8:12]
        if brand in (b"heic", b"heix", b"hevc", b"hevx", b"mif1", b"msf1", b"heim", b"heis"):
            return "image/heic"
        return "video/mp4"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if data.startswith(b"GIF87a") or data.startswith(b"GIF89a"):
        return "image/gif"
    if data.startswith(b"PK\x03\x04"):
        return "application/zip"
    if data.startswith(b"MZ") or data.startswith(b"\x7fELF"):
        return "application/x-executable"
    return None


# --- PNG encoding and PDF rasterisation -------------------------------------


def _png_chunk(tag: bytes, payload: bytes) -> bytes:
    return (
        struct.pack(">I", len(payload))
        + tag
        + payload
        + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
    )


def encode_png(width: int, height: int, rgb: bytes) -> bytes:
    """Minimal 8-bit RGB PNG encoder.

    Written out rather than pulled in with Pillow: this is the only raster
    write in the product, pdfium already hands back a raw pixel buffer, and
    Pillow would add a compiled dependency to every deployment for forty
    lines of zlib.
    """
    stride = width * 3
    raw = bytearray()
    for y in range(height):
        raw.append(0)  # filter type 0 (None) for every scanline
        raw += rgb[y * stride : (y + 1) * stride]
    return (
        b"\x89PNG\r\n\x1a\n"
        + _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + _png_chunk(b"IDAT", zlib.compress(bytes(raw), 6))
        + _png_chunk(b"IEND", b"")
    )


def _bitmap_to_rgb(buffer: bytes, width: int, height: int, stride: int, mode: str) -> bytes:
    """pdfium's buffer (BGR/BGRA/RGB/RGBA, possibly row-padded) as packed RGB.

    Byte-slice assignment on a `bytearray` does the channel work at C speed;
    a per-pixel Python loop over an A4 page at 200 DPI takes seconds.
    """
    channels = 4 if mode in ("BGRA", "RGBA") else 3
    flat = bytearray()
    for y in range(height):
        flat += buffer[y * stride : y * stride + width * channels]
    if channels == 4:
        del flat[3::4]
    if mode.startswith("BGR"):
        blue = flat[0::3]
        flat[0::3] = flat[2::3]
        flat[2::3] = blue
    return bytes(flat)


def rasterise_pdf_page_one(pdf_bytes: bytes) -> tuple[bytes, int]:
    """Page 1 of a PDF as PNG bytes, plus the document's page count.

    Raises `RasterError` with bilingual copy for an encrypted, corrupt, or
    empty PDF. Synchronous and CPU-bound on purpose: callers run it through
    `asyncio.to_thread` so one large scan cannot stall the event loop.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise RasterError(
            "This deployment cannot open PDFs. Upload a photo or a PNG of the "
            "page instead.",
            "এই সিস্টেমে পিডিএফ খোলা যাচ্ছে না। পরিবর্তে পাতার একটি ছবি বা পিএনজি আপলোড করুন।",
        ) from exc

    try:
        document = pdfium.PdfDocument(pdf_bytes)
        page_count = len(document)
        if page_count < 1:
            raise ValueError("no pages")
        page = document[0]
        width_pt, height_pt = page.get_size()
        longest = max(width_pt, height_pt) or 1.0
        scale = max(_PDF_RASTER_MIN_SCALE, min(3.0, _RASTER_MAX_EDGE / longest))
        bitmap = page.render(scale=scale)
        rgb = _bitmap_to_rgb(
            bytes(bitmap.buffer), bitmap.width, bitmap.height, bitmap.stride, bitmap.mode
        )
        png = encode_png(bitmap.width, bitmap.height, rgb)
    except RasterError:
        raise
    except Exception as exc:  # noqa: BLE001 - every pdfium failure means the same thing to a student
        log.warning("pdf rasterisation failed: %s", exc)
        raise RasterError(
            "This PDF could not be opened. It may be password protected or "
            "damaged. Try exporting it again, or upload a photo of the page.",
            "এই পিডিএফটি খোলা যায়নি। এটি হয়তো পাসওয়ার্ড দেওয়া বা নষ্ট। আবার এক্সপোর্ট করে "
            "দেখুন, অথবা পাতার একটি ছবি আপলোড করুন।",
        ) from exc
    return png, page_count


# --- extracted field definitions --------------------------------------------


class _FieldSpec:
    """One document kind's vision extraction contract."""

    __slots__ = ("keys", "date_keys", "expiry_key", "issued_key", "instruction")

    def __init__(
        self,
        *,
        keys: Sequence[str],
        instruction: str,
        date_keys: Sequence[str] = (),
        expiry_key: str | None = None,
        issued_key: str | None = None,
    ) -> None:
        self.keys = tuple(keys)
        self.date_keys = frozenset(date_keys)
        self.expiry_key = expiry_key
        self.issued_key = issued_key
        self.instruction = instruction


_FIELD_SPECS: Final[dict[str, _FieldSpec]] = {
    "passport": _FieldSpec(
        keys=("surname", "given_name", "passport_no", "date_of_birth", "expiry"),
        date_keys=("date_of_birth", "expiry"),
        expiry_key="expiry",
        instruction=(
            "This is a passport biographical data page. Read the surname, the "
            "given names, the passport number, the date of birth, and the date "
            "of expiry. Take the names from the printed fields, not from the "
            "machine readable zone at the bottom."
        ),
    ),
    "bank_statement": _FieldSpec(
        keys=("balance", "currency", "statement_date"),
        date_keys=("statement_date",),
        issued_key="statement_date",
        instruction=(
            "This is a bank statement. Read the closing or available balance as "
            "digits only with no thousands separators, the three letter currency "
            "code (BDT, USD, EUR), and the date the statement was issued."
        ),
    ),
    "transcript": _FieldSpec(
        keys=("institution", "cgpa", "graduation_date"),
        date_keys=("graduation_date",),
        issued_key="graduation_date",
        instruction=(
            "This is an academic transcript. Read the full name of the awarding "
            "institution, the CGPA or GPA exactly as printed (keep the scale if "
            "one is printed, for example 3.62 out of 4.00), and the date of "
            "graduation or of the award."
        ),
    ),
}

_EXTRACT_SYSTEM: Final[str] = (
    "You read scanned documents belonging to Bangladeshi students and return "
    "only the values that are actually printed on the page. Copy the text "
    "exactly as it appears. If a field is not visible, is cut off, or is "
    "unreadable, leave it out of the list entirely. Never guess a value, never "
    "complete a partial one, and never carry a value over from a document you "
    "have seen before. Write every date as YYYY-MM-DD. Return JSON only."
)

_EXTRACT_SCHEMA: Final[dict[str, Any]] = {
    "type": "object",
    "properties": {
        "fields": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "key": {"type": "string"},
                    "value": {"type": "string"},
                    "confidence": {"type": "number"},
                },
                "required": ["key", "value", "confidence"],
            },
        }
    },
    "required": ["fields"],
}

_MONTHS: Final[dict[str, int]] = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_ISO_DATE_RE: Final[re.Pattern[str]] = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_DMY_RE: Final[re.Pattern[str]] = re.compile(r"^(\d{1,2})[\s./-]+([A-Za-z]{3,9}|\d{1,2})[\s./-]+(\d{4})$")


def normalise_date(raw: str) -> str | None:
    """A printed date as YYYY-MM-DD, or None if it is not a date.

    Passports print `22 SEP 2029`, bank statements print `22/09/2029`, and the
    model returns whichever it saw. Normalising here means `value_hash` for a
    date compares across documents, which is the entire point of storing the
    hash.
    """
    text = " ".join(raw.strip().split())
    if not text:
        return None
    iso = _ISO_DATE_RE.match(text)
    if iso:
        year, month, day = (int(g) for g in iso.groups())
    else:
        dmy = _DMY_RE.match(text)
        if not dmy:
            return None
        day_s, month_s, year_s = dmy.groups()
        month_key = month_s.lower()[:3]
        if month_key in _MONTHS:
            month = _MONTHS[month_key]
        elif month_s.isdigit():
            month = int(month_s)
        else:
            return None
        day, year = int(day_s), int(year_s)
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return None


class VaultService:
    def __init__(
        self,
        documents: DocumentRepo,
        audits: AuditRepo,
        profiles: ProfileRepo,
        targets: TargetRepo,
        bus: EventBus,
        router: ModelRouter,
        settings: Settings,
    ) -> None:
        self._documents = documents
        self._audits = audits
        self._profiles = profiles
        self._targets = targets
        self._bus = bus
        self._router = router
        self._settings = settings

    # -- documents -------------------------------------------------------

    def check_size(self, byte_count: int) -> None:
        """413 as soon as the limit is crossed.

        Exposed so the router can stop reading a stream mid-flight instead of
        buffering a gigabyte to disk and only then complaining.
        """
        limit = self._settings.max_upload_bytes
        if byte_count <= limit:
            return
        limit_mb = limit // (1024 * 1024)
        raise PayloadTooLarge(
            detail_en=(
                f"That file is larger than {limit_mb} MB. Photograph the page "
                "again at a lower resolution, or split the PDF and upload the "
                "pages that matter."
            ),
            detail_bn=(
                f"ফাইলটি {limit_mb} মেগাবাইটের চেয়ে বড়। পাতাটি আবার কম রেজোলিউশনে ছবি "
                "তুলুন, অথবা পিডিএফটি ভাগ করে প্রয়োজনীয় পাতাগুলো আপলোড করুন।"
            ),
        )

    async def upload_document(
        self, *, user_id: int, user_public_id: str, kind: str, filename: str,
        mime_type: str, data: bytes, expires_on: str | None,
    ) -> dict[str, Any]:
        """Store one encrypted document and announce it.

        `mime_type` is what the client claimed. It is logged when it disagrees
        with the bytes and otherwise ignored: the sniffed type is what is
        persisted.
        """
        if kind not in _KIND_LABELS_EN:
            raise ValidationProblem(
                detail_en="That is not a document type this vault recognises.",
                detail_bn="এই ধরনের নথি এই ভল্ট চেনে না।",
            )
        self.check_size(len(data))
        if not data:
            raise ValidationProblem(
                detail_en="That file is empty.",
                detail_bn="ফাইলটি খালি।",
            )

        sniffed = sniff_mime(data)
        if sniffed not in _ACCEPTED_MIME:
            raise UnsupportedMedia(
                detail_en=(
                    "Only PDF, JPEG, PNG, and HEIC files are accepted, and this "
                    "file's contents are none of those, whatever it is named."
                ),
                detail_bn=(
                    "শুধু পিডিএফ, জেপিইজি, পিএনজি এবং হেইক ফাইল গ্রহণযোগ্য। ফাইলের নাম "
                    "যাই হোক, এর ভেতরের তথ্য এগুলোর কোনোটিই নয়।"
                ),
            )
        if mime_type and mime_type != sniffed:
            log.info("declared mime %s does not match sniffed %s", mime_type, sniffed)

        expires_iso = _validated_date(
            expires_on,
            detail_en="The expiry date must be written as YYYY-MM-DD.",
            detail_bn="মেয়াদ শেষের তারিখ YYYY-MM-DD আকারে লিখতে হবে।",
        )

        sha256 = hashlib.sha256(data).hexdigest()
        ciphertext, wrapped_dek, nonce = encrypt_file(
            data, user_id=user_id, settings=self._settings
        )

        storage_dir = self._settings.vault_dir / user_public_id
        storage_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(storage_dir, 0o700)
        # Not `{sha256}.enc`: the same bytes uploaded twice would then be
        # written twice to one path with two different DEKs, and the first
        # document row would be left pointing at ciphertext its key can no
        # longer open. A random name per upload cannot collide; the digest
        # still lives in the `sha256` column for deduplication and integrity.
        storage_path = storage_dir / f"{secrets.token_hex(16)}.enc"
        storage_path.write_bytes(ciphertext)
        os.chmod(storage_path, 0o600)

        try:
            doc = await self._documents.create(
                user_id=user_id,
                kind=kind,
                original_name=_safe_filename(filename),
                storage_path=str(storage_path),
                mime_type=sniffed,
                byte_size=len(data),
                sha256=sha256,
                wrapped_dek=wrapped_dek,
                nonce=nonce,
                expires_on=expires_iso,
            )
        except Exception:
            storage_path.unlink(missing_ok=True)
            raise

        # A dead Redis must not lose a document the student already uploaded:
        # `EventBus.publish` writes the durable events.db row before it touches
        # the stream, so a delivery failure here has already been recorded.
        try:
            await self._bus.publish(
                EventType.VAULT_DOC_ADDED,
                user_id=user_id,
                subject_type="document",
                subject_id=doc["public_id"],
                payload={"kind": kind, "mime_type": sniffed, "byte_size": len(data)},
            )
        except Exception as exc:  # noqa: BLE001 - delivery is best effort, storage is not
            log.warning("vault.doc.added not delivered document=%s err=%s", doc["public_id"], exc)

        return doc

    async def extract_document(self, user_id: int, public_id: str) -> dict[str, Any]:
        """Run the Gemma vision pass over one stored document.

        Returns the refreshed row. Never raises for a document that simply
        could not be read: that outcome is `status='failed'` plus a bilingual
        reason, because this runs detached from the upload response and an
        exception here would only reach a log.
        """
        doc = await self.get_document(user_id, public_id)
        spec = _FIELD_SPECS.get(doc["kind"])

        try:
            image_png, page_count = await self._page_one_png(doc)
        except RasterError as exc:
            await self._documents.set_status(
                doc["id"], "failed", reason_en=exc.detail_en, reason_bn=exc.detail_bn
            )
            return await self.get_document(user_id, public_id)

        if spec is None:
            # Nothing to extract for this kind (a photo, an offer letter). The
            # document is still stored, encrypted, and auditable by Prohori.
            await self._documents.set_extraction_result(
                doc["id"], page_count=page_count, issued_on=None, expires_on=None
            )
            return await self.get_document(user_id, public_id)

        try:
            values = await self._read_fields(image_png, spec)
        except Exception as exc:  # noqa: BLE001 - a model failure is a document outcome, not a crash
            log.warning("field extraction failed document=%s err=%s", public_id, exc)
            await self._documents.set_status(
                doc["id"],
                "failed",
                reason_en=(
                    "The reader could not make out this document. Try a sharper, "
                    "straight-on photo with the whole page in frame."
                ),
                reason_bn=(
                    "এই নথিটি পড়া যায়নি। পুরো পাতা ফ্রেমে রেখে সোজাসুজি আরও স্পষ্ট ছবি তুলে "
                    "আবার চেষ্টা করুন।"
                ),
            )
            return await self.get_document(user_id, public_id)

        dek = unwrap_dek(doc["wrapped_dek"], user_id=user_id, settings=self._settings)
        for key, (value, confidence) in values.items():
            await self._documents.upsert_field(
                document_id=doc["id"],
                field_key=key,
                value_enc=encrypt_field(value, dek),
                value_hash=normalised_value_hash(value),
                confidence=confidence,
                page_no=1,
            )

        expiry = values.get(spec.expiry_key or "", ("", 0.0))[0] if spec.expiry_key else ""
        issued = values.get(spec.issued_key or "", ("", 0.0))[0] if spec.issued_key else ""
        await self._documents.set_extraction_result(
            doc["id"],
            page_count=page_count,
            issued_on=normalise_date(issued) if issued else None,
            expires_on=normalise_date(expiry) if expiry else None,
        )
        return await self.get_document(user_id, public_id)

    async def _page_one_png(self, doc: dict[str, Any]) -> tuple[bytes, int]:
        """Decrypted page 1 as PNG bytes, plus a page count where one exists.

        The single place a PDF becomes an image. Bicharok and Dalil both
        refuse anything that is not an image, and the Gemma vision pass needs
        the same thing, so all three go through here.
        """
        plaintext = await self._decrypt(doc)
        mime = doc["mime_type"]
        if mime == "application/pdf":
            return await asyncio.to_thread(rasterise_pdf_page_one, plaintext)
        if mime in _RASTERISABLE_MIME:
            return plaintext, 1
        raise RasterError(
            "This deployment cannot read HEIC images. On an iPhone, set "
            "Settings > Camera > Formats to Most Compatible, or share the photo "
            "as a JPEG and upload that.",
            "এই সিস্টেমে HEIC ছবি পড়া যায় না। আইফোনে Settings > Camera > Formats থেকে "
            "Most Compatible বেছে নিন, অথবা ছবিটি জেপিইজি হিসেবে শেয়ার করে আপলোড করুন।",
        )

    async def _read_fields(
        self, image_png: bytes, spec: _FieldSpec
    ) -> dict[str, tuple[str, float]]:
        """One schema-constrained vision call. Returns {key: (value, confidence)}."""
        wanted = ", ".join(spec.keys)
        schema = json.loads(json.dumps(_EXTRACT_SCHEMA))
        schema["properties"]["fields"]["items"]["properties"]["key"]["enum"] = list(spec.keys)

        response = await self._router.complete(
            LLMRequest(
                kind=TaskKind.VISION_EXTRACT,
                messages=[
                    {"role": "system", "content": _EXTRACT_SYSTEM},
                    {
                        "role": "user",
                        "content": (
                            f"{spec.instruction} Return one entry for each of these "
                            f"keys you can actually read: {wanted}. Give each entry a "
                            "confidence between 0 and 1 for how clearly you could read "
                            "that value."
                        ),
                        # Ollama takes media as base64 strings on the message
                        # itself; `LLMRequest.images` below only tells the
                        # router this call is a vision call and must stay local.
                        "images": [base64.b64encode(image_png).decode("ascii")],
                    },
                ],
                json_schema=schema,
                images=[image_png],
                contains_user_documents=True,
                temperature=0.0,
                max_tokens=768,
            )
        )

        payload = json.loads(response.text)
        out: dict[str, tuple[str, float]] = {}
        for entry in payload.get("fields", []):
            if not isinstance(entry, dict):
                continue
            key = str(entry.get("key", ""))
            value = str(entry.get("value", "")).strip()
            if key not in spec.keys or not value:
                continue
            if key in spec.date_keys:
                value = normalise_date(value) or value
            confidence = entry.get("confidence")
            try:
                score = min(1.0, max(0.0, float(confidence)))
            except (TypeError, ValueError):
                score = 0.0
            out[key] = (value, score)
        return out

    async def list_documents(self, user_id: int) -> list[dict[str, Any]]:
        docs = await self._documents.list_for_user(user_id)
        out: list[dict[str, Any]] = []
        for d in docs:
            findings = await self._audits.latest_findings_for_document(d["id"])
            top = findings[0] if findings else None
            expires_days = None
            if d["expires_on"]:
                try:
                    expires_days = (date.fromisoformat(d["expires_on"]) - date.today()).days
                except ValueError:
                    expires_days = None
            severity = "ok"
            finding_en = "No issues found."
            finding_bn = "কোনো সমস্যা পাওয়া যায়নি।"
            action_en = "No action needed."
            action_bn = "কোনো পদক্ষেপ প্রয়োজন নেই।"
            if d["status"] == "scanning":
                finding_en = "Reading this document now."
                finding_bn = "এই নথিটি এখন পড়া হচ্ছে।"
                action_en = "Nothing to do; this takes a few seconds."
                action_bn = "কিছু করতে হবে না; কয়েক সেকেন্ড সময় লাগবে।"
            if d["status"] == "failed":
                # The extraction reason is the honest finding here: Prohori
                # cannot audit a document nothing could read.
                severity = "warn"
                finding_en = d.get("failure_reason_en") or "This document could not be read."
                finding_bn = d.get("failure_reason_bn") or "এই নথিটি পড়া যায়নি।"
                action_en = "Upload a clearer copy of this document."
                action_bn = "এই নথির আরও স্পষ্ট একটি কপি আপলোড করুন।"
            if top:
                severity = _SEVERITY_MAP.get(top["severity"], "warn")
                finding_en = top["detail_en"]
                finding_bn = top["detail_bn"]
                action_en = top["action_en"] or "Review this document."
                action_bn = top["action_bn"] or "এই নথিটি পর্যালোচনা করুন।"
            out.append(
                {
                    "id": d["public_id"],
                    "kind": d["kind"],
                    "nameEn": _kind_label_en(d["kind"]),
                    "nameBn": _kind_label_bn(d["kind"]),
                    "count": 1,
                    "expiresDays": expires_days,
                    "severity": severity,
                    "findingEn": finding_en,
                    "findingBn": finding_bn,
                    "actionEn": action_en,
                    "actionBn": action_bn,
                    "status": d["status"],
                    "uploaded_at": d["uploaded_at"],
                }
            )
        return out

    async def get_document(self, user_id: int, public_id: str) -> dict[str, Any]:
        doc = await self._documents.get_by_public_id(user_id, public_id)
        if doc is None:
            raise NotFound(detail_en="Document not found.", detail_bn="নথিটি পাওয়া যায়নি।")
        return doc

    async def get_download_url(self, user_id: int, public_id: str) -> dict[str, Any]:
        doc = await self.get_document(user_id, public_id)
        # Signed, short-lived download URLs are issued by the router, which
        # owns request signing; this returns the metadata it needs to do so.
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=15)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        return {"document_id": doc["public_id"], "storage_path": doc["storage_path"], "expires_at": expires_at}

    async def read_document_bytes(self, user_id: int, public_id: str) -> tuple[bytes, dict[str, Any]]:
        """Decrypted bytes for a download, with the row that describes them.

        AES-GCM authenticates the whole ciphertext, so the file is decrypted
        in one pass (releasing unverified plaintext chunk by chunk would throw
        away the guarantee the tag exists for) and handed to the router to
        stream out.
        """
        doc = await self.get_document(user_id, public_id)
        path = Path(doc["storage_path"])
        if not path.is_file():
            raise NotFound(
                detail_en="The stored file for this document is missing.",
                detail_bn="এই নথির সংরক্ষিত ফাইলটি খুঁজে পাওয়া যায়নি।",
            )
        plaintext = await asyncio.to_thread(self._decrypt_path, path, doc)
        return plaintext, doc

    def _decrypt_path(self, path: Path, doc: dict[str, Any]) -> bytes:
        return decrypt_file(
            path.read_bytes(),
            doc["wrapped_dek"],
            doc["nonce"],
            user_id=doc["user_id"],
            settings=self._settings,
        )

    async def delete_document(self, user_id: int, public_id: str) -> None:
        doc = await self.get_document(user_id, public_id)
        path = Path(doc["storage_path"])
        if path.is_file():
            await asyncio.to_thread(_shred_file, path)
        await self._documents.shred_keys(doc["id"])
        await self._documents.soft_delete(doc["id"])

    async def _decrypt(self, doc: dict[str, Any]) -> bytes:
        path = Path(doc["storage_path"])
        if not path.is_file():
            raise RasterError(
                "The stored file for this document is missing.",
                "এই নথির সংরক্ষিত ফাইলটি খুঁজে পাওয়া যায়নি।",
            )
        return await asyncio.to_thread(self._decrypt_path, path, doc)

    # -- Prohori audit -----------------------------------------------------

    async def start_audit(self, user_id: int, target_public_id: str | None) -> dict[str, Any]:
        target_row = None
        if target_public_id:
            target_row = await self._targets.get_target(user_id, target_public_id)
        audit = await self._audits.create(user_id, target_row["id"] if target_row else None)
        await self._audits.set_status(audit["id"], "running")
        try:
            documents = await self._documents.list_for_user(user_id)
            profile = await self._profiles.get(user_id)
            findings = await run_audit(
                documents=documents, profile=profile, target=target_row, router=self._router
            )
            for f in findings:
                await self._audits.add_finding(
                    audit["id"],
                    document_id=f.get("document_id"),
                    code=f["code"],
                    severity=f["severity"],
                    title_en=f["title_en"],
                    title_bn=f["title_bn"],
                    detail_en=f["detail_en"],
                    detail_bn=f["detail_bn"],
                    evidence=f.get("evidence"),
                    action_en=f.get("action_en"),
                    action_bn=f.get("action_bn"),
                    snapshot_id=f.get("snapshot_id"),
                )
            await self._audits.set_status(audit["id"], "complete")
        except Exception as exc:  # noqa: BLE001
            await self._audits.set_status(audit["id"], "failed", str(exc))
            raise
        try:
            await self._bus.publish(
                EventType.AUDIT_UPDATED,
                user_id=user_id,
                subject_type="audit",
                subject_id=audit["public_id"],
                payload={},
            )
        except Exception as exc:  # noqa: BLE001 - see upload_document
            log.warning("audit.updated not delivered audit=%s err=%s", audit["public_id"], exc)
        return audit

    async def get_latest_audit(self, user_id: int) -> dict[str, Any]:
        audit = await self._audits.latest_for_user(user_id)
        if audit is None:
            raise NotFound(
                detail_en="No audit has been run yet.",
                detail_bn="এখনও কোনো অডিট চালানো হয়নি।",
            )
        findings = await self._audits.list_findings(audit["id"])
        return {**audit, "findings": findings}

    # -- Bicharok: rejection autopsy ---------------------------------------

    async def create_rejection_case(self, user_id: int, document_public_id: str) -> dict[str, Any]:
        doc = await self.get_document(user_id, document_public_id)
        # Rasterise before the case row exists: a refusal letter that cannot be
        # opened should leave no half-built case behind.
        try:
            page_png, _ = await self._page_one_png(doc)
        except RasterError as exc:
            raise ValidationProblem(detail_en=exc.detail_en, detail_bn=exc.detail_bn) from exc

        case = await self._documents.create_rejection_case(user_id, doc["id"])
        result = await analyse_rejection(
            document_bytes=page_png, mime_type="image/png", router=self._router
        )
        await self._documents.set_rejection_summary(
            case["id"],
            summary_en=result.get("summary_en", ""),
            summary_bn=result.get("summary_bn", ""),
            country_code=result.get("country_code"),
            visa_type=result.get("visa_type"),
            reapply_ready_at=result.get("reapply_ready_at"),
        )
        for g in result.get("grounds", []):
            await self._documents.add_rejection_ground(
                case["id"],
                code=g.get("code"),
                quoted_text=g["quoted_text"],
                meaning_en=g["meaning_en"],
                meaning_bn=g["meaning_bn"],
                remedy_en=g["remedy_en"],
                remedy_bn=g["remedy_bn"],
                remediable=g["remediable"],
                snapshot_id=g.get("snapshot_id"),
                linked_step_key=g.get("linked_step_key"),
            )
        return case

    async def get_rejection_case(self, user_id: int, public_id: str) -> dict[str, Any]:
        case = await self._documents.get_rejection_case(user_id, public_id)
        if case is None:
            raise NotFound(detail_en="Case not found.", detail_bn="কেসটি পাওয়া যায়নি।")
        grounds = await self._documents.list_rejection_grounds(case["id"])
        return {**case, "grounds": grounds}

    async def apply_rejection_to_plan(self, user_id: int, public_id: str) -> list[str]:
        case = await self._documents.get_rejection_case(user_id, public_id)
        if case is None:
            raise NotFound(detail_en="Case not found.", detail_bn="কেসটি পাওয়া যায়নি।")
        grounds = await self._documents.list_rejection_grounds(case["id"])
        applied = [g["linked_step_key"] for g in grounds if g.get("linked_step_key")]
        try:
            await self._bus.publish(
                EventType.PLAN_STEP_CHANGED,
                user_id=user_id,
                subject_type="rejection_case",
                subject_id=public_id,
                payload={"applied_step_keys": applied},
            )
        except Exception as exc:  # noqa: BLE001 - see upload_document
            log.warning("plan.step.changed not delivered case=%s err=%s", public_id, exc)
        return applied

    # -- Lekhok: statement forensics -----------------------------------------

    async def create_statement(
        self, user_id: int, kind: str, body: str, target_public_id: str | None
    ) -> dict[str, Any]:
        target_row = None
        if target_public_id:
            target_row = await self._targets.get_target(user_id, target_public_id)
        statement = await self._documents.create_statement(
            user_id, target_row["id"] if target_row else None, kind, body
        )
        documents = await self._documents.list_for_user(user_id)
        findings = await analyse_statement(body=body, documents=documents, router=self._router)
        for f in findings:
            await self._documents.add_statement_finding(
                statement["id"],
                severity=f["severity"],
                kind=f["kind"],
                excerpt=f["excerpt"],
                detail_en=f["detail_en"],
                detail_bn=f["detail_bn"],
                conflicts_document_id=f.get("conflicts_document_id"),
                suggestion_en=f.get("suggestion_en"),
                suggestion_bn=f.get("suggestion_bn"),
            )
        return statement

    async def get_statement_findings(self, user_id: int, public_id: str) -> list[dict[str, Any]]:
        statement = await self._documents.get_statement(user_id, public_id)
        if statement is None:
            raise NotFound(detail_en="Statement not found.", detail_bn="বিবৃতিটি পাওয়া যায়নি।")
        return await self._documents.list_statement_findings(statement["id"])

    # -- Dalil: contract auditor --------------------------------------------

    async def create_contract(self, user_id: int, document_public_id: str) -> dict[str, Any]:
        doc = await self.get_document(user_id, document_public_id)
        try:
            page_png, _ = await self._page_one_png(doc)
        except RasterError as exc:
            raise ValidationProblem(detail_en=exc.detail_en, detail_bn=exc.detail_bn) from exc

        contract = await self._documents.create_contract(user_id, doc["id"])
        result = await audit_contract(
            document_bytes=page_png, mime_type="image/png", router=self._router
        )
        await self._documents.set_contract_risk(contract["id"], result.get("risk_overall", "medium"))
        for c in result.get("clauses", []):
            await self._documents.add_contract_clause(
                contract["id"],
                quoted_text=c["quoted_text"],
                category=c["category"],
                risk=c["risk"],
                why_en=c["why_en"],
                why_bn=c["why_bn"],
                fair_alternative_en=c.get("fair_alternative_en"),
                fair_alternative_bn=c.get("fair_alternative_bn"),
            )
        return contract

    async def get_contract(self, user_id: int, public_id: str) -> dict[str, Any]:
        contract = await self._documents.get_contract(user_id, public_id)
        if contract is None:
            raise NotFound(detail_en="Contract not found.", detail_bn="চুক্তিটি পাওয়া যায়নি।")
        clauses = await self._documents.list_contract_clauses(contract["id"])
        return {**contract, "clauses": clauses}


def _shred_file(path: Path) -> None:
    """Overwrite the ciphertext in place, then unlink it.

    On a copy-on-write or log-structured filesystem this is not a guarantee,
    which is why it is the second line of defence and not the first: the DEK
    is destroyed in the same delete (`DocumentRepo.shred_keys`), and without
    the DEK the ciphertext is noise whether or not the blocks survive.
    """
    try:
        size = path.stat().st_size
        with path.open("r+b", buffering=0) as handle:
            written = 0
            while written < size:
                block = min(_UPLOAD_CHUNK, size - written)
                handle.write(secrets.token_bytes(block))
                written += block
            handle.flush()
            os.fsync(handle.fileno())
    except OSError as exc:  # noqa: BLE001 - unlinking still has to happen
        log.warning("could not overwrite %s before delete: %s", path, exc)
    path.unlink(missing_ok=True)


def _safe_filename(filename: str) -> str:
    """The original name, stripped of anything that could steer a path.

    `original_name` is echoed back in a `Content-Disposition` header on
    download, so a name carrying quotes, newlines, or a directory traversal
    never gets stored in the first place.
    """
    base = Path(filename.replace("\\", "/")).name
    cleaned = re.sub(r'[\x00-\x1f"\\]+', "", base).strip()
    return cleaned[:200] or "upload"


def _validated_date(value: str | None, *, detail_en: str, detail_bn: str) -> str | None:
    if value is None or not value.strip():
        return None
    try:
        return date.fromisoformat(value.strip()).isoformat()
    except ValueError as exc:
        raise ValidationProblem(detail_en=detail_en, detail_bn=detail_bn) from exc


_SEVERITY_MAP: Final[dict[str, str]] = {"critical": "error", "warning": "warn", "info": "ok"}

_KIND_LABELS_EN: Final[dict[str, str]] = {
    "passport": "Passport", "transcript": "Academic transcript", "certificate": "Certificate",
    "bank_statement": "Bank statement", "solvency_letter": "Solvency letter",
    "english_test": "English test result", "sop": "Statement of purpose",
    "recommendation": "Recommendation letter", "offer_letter": "Offer letter",
    "visa_refusal": "Visa refusal letter", "consultancy_contract": "Consultancy contract",
    "photo": "Photograph", "other": "Document",
}
_KIND_LABELS_BN: Final[dict[str, str]] = {
    "passport": "পাসপোর্ট", "transcript": "একাডেমিক ট্রান্সক্রিপ্ট", "certificate": "সার্টিফিকেট",
    "bank_statement": "ব্যাংক স্টেটমেন্ট", "solvency_letter": "সচ্ছলতা সনদ",
    "english_test": "ইংরেজি পরীক্ষার ফলাফল", "sop": "উদ্দেশ্য বিবৃতি",
    "recommendation": "সুপারিশপত্র", "offer_letter": "অফার লেটার",
    "visa_refusal": "ভিসা প্রত্যাখ্যান পত্র", "consultancy_contract": "কনসালটেন্সি চুক্তি",
    "photo": "ছবি", "other": "নথি",
}


def _kind_label_en(kind: str) -> str:
    return _KIND_LABELS_EN.get(kind, "Document")


def _kind_label_bn(kind: str) -> str:
    return _KIND_LABELS_BN.get(kind, "নথি")
