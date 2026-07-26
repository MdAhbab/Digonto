"""Grounded answer generation: retrieve, then answer only from what was found.

This is the core of the product and the place where its central promise is kept:
every claim is supported by a retrieved passage, and when nothing supports an
answer the system refuses instead of inventing one.

**Why generation is streamed through a schema.** The interface reveals the answer
word by word, so tokens have to arrive progressively. Citations, however, have to
be structurally valid: a half-parsed citation is worse than none. The model is
therefore asked for schema-constrained JSON with streaming on, and the answer
field is decoded incrementally from the growing buffer while it arrives.
Citations are emitted only after the object closes and parses. That gives a fast
first token without ever emitting a malformed citation.

The system prompt and schema here are not new. They are the ones verified against
the live model in backend/tests/test_model_contracts.py, including the
requirement that refusal_reason is always non-empty. That requirement exists
because during testing the model returned an empty reason while setting
is_refusal true, which would violate the CHECK constraint on the answers table.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import AsyncIterator
from typing import Any

from app.config import get_settings
from app.llm.router import LLMRequest, ModelRouter, TaskKind
from app.rag.cache import SemanticCache
from app.rag.embeddings import Embedder
from app.rag.retrieval import Passage, Retriever
from app.rag.student_context import STUDENT_CONTEXT_RULE
from app.security.framing import DATA_ONLY_RULE, frame_untrusted

log = logging.getLogger(__name__)

# A citation quote is evidence for one claim, so a sentence or two. The cap is
# defence against a model that quotes a whole page: the Truth Ledger panel shows
# the full snapshot anyway, and the quote only has to locate the claim within it.
QUOTED_SPAN_MAX_CHARS = 600

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answer_bn": {"type": "string"},
        "answer_en": {"type": "string"},
        "is_refusal": {"type": "boolean"},
        "refusal_reason": {"type": "string"},
        "citations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "ordinal": {"type": "integer"},
                    "snapshot_id": {"type": "string"},
                    "quoted_span": {"type": "string"},
                },
                "required": ["ordinal", "snapshot_id", "quoted_span"],
            },
        },
        "confidence": {"type": "number"},
    },
    "required": [
        "answer_bn", "answer_en", "is_refusal",
        "refusal_reason", "citations", "confidence",
    ],
}

SYSTEM_PROMPT = (
    "You answer questions from Bangladeshi students about studying abroad and "
    "visas, using ONLY the SOURCE passages provided.\n"
    "Cite each factual claim with the snapshot_id it came from and the exact "
    "quoted span from that passage. Put a marker of the form ‖n‖ in "
    "the answer text at each cited claim, where n is the citation ordinal.\n"
    "If no passage supports an answer, set is_refusal true and say what is "
    "missing. Never guess, and never use knowledge that is not in the passages.\n"
    "refusal_reason must ALWAYS be a non-empty string: give the reason when "
    "refusing, or 'not applicable' when answering.\n"
    "Keep each quoted_span to the single sentence that supports the claim, never "
    "a whole paragraph. Long quotes crowd out the answer itself.\n"
    "answer_bn must be natural, plain Bangla that a first-time applicant "
    "understands. answer_en is the same answer in plain English.\n" + DATA_ONLY_RULE
)


def _frame_sources(passages: list[Passage]) -> str:
    """Wrap retrieved text so an injected instruction reads as data.

    Crawled pages are untrusted. The fence is generated per passage by
    `app.security.framing`, so a page containing a literal end tag cannot close
    its own block and continue as top-level instruction; that is the part a
    fixed delimiter gets wrong. Saying so in the system prompt
    (`DATA_ONLY_RULE`) and disabling tool calling for this call are the rest of
    the defence.
    """
    if not passages:
        return "[no passages retrieved]"
    return "\n\n".join(
        frame_untrusted(
            p.text,
            label="SOURCE",
            attrs={
                "snapshot_id": p.snapshot_public_id,
                "portal": p.portal,
                "section": p.section_path,
            },
        )
        for p in passages
    )


def _partial_string_field(buffer: str, field: str) -> str:
    """Decode as much of a JSON string field as has arrived.

    The buffer is a partially written JSON object. This finds the field, walks
    forward honouring escapes, and returns the decoded prefix rather than
    failing. That is what makes progressive rendering possible without waiting
    for the object to close.
    """
    match = re.search(rf'"{field}"\s*:\s*"', buffer)
    if not match:
        return ""
    i = match.end()
    out: list[str] = []
    escapes = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/"}
    while i < len(buffer):
        ch = buffer[i]
        if ch == "\\":
            if i + 1 >= len(buffer):
                break  # escape sequence has not fully arrived
            nxt = buffer[i + 1]
            if nxt == "u":
                if i + 6 > len(buffer):
                    break
                try:
                    out.append(chr(int(buffer[i + 2 : i + 6], 16)))
                except ValueError:
                    pass
                i += 6
                continue
            out.append(escapes.get(nxt, nxt))
            i += 2
            continue
        if ch == '"':
            break  # field closed
        out.append(ch)
        i += 1
    return "".join(out)


def _chunks(text: str, size: int = 12) -> list[str]:
    """Split emitted text into word-sized pieces.

    The client staggers word by word, so pieces roughly a word long keep the
    animation smooth without one event per character.
    """
    if not text:
        return []
    out: list[str] = []
    current = ""
    for part in re.split(r"(\s+)", text):
        current += part
        if len(current) >= size:
            out.append(current)
            current = ""
    if current:
        out.append(current)
    return out


NO_SOURCE_EN = (
    "No official source in the archive covers this question yet. Rather than "
    "guess at a visa requirement, this is left unanswered and the relevant "
    "portals are being watched for it."
)
NO_SOURCE_BN = (
    "এই প্রশ্নের উত্তর দেওয়ার মতো কোনো সরকারি উৎস এখনো সংরক্ষণে নেই। "
    "ভিসার শর্ত নিয়ে অনুমান না করে উত্তরটি দেওয়া হচ্ছে না, এবং সংশ্লিষ্ট "
    "পোর্টালগুলো পর্যবেক্ষণে রাখা হয়েছে।"
)


async def stream_grounded_answer(
    *,
    question: str,
    lang: str | None,
    country: str | None,
    kb_version_id: int | None,
    router: ModelRouter,
    retriever: Retriever,
    cache: SemanticCache,
    student_context: str = "",
) -> AsyncIterator[dict[str, Any]]:
    """Yield the event sequence AskService consumes.

    Order: meta first, always. Then either a refusal, or tokens followed by
    citations, the mirror-language answer, and final. `incomplete` can appear
    in place of the citation group when generation was cut off after tokens
    were already emitted.

    `router`, `retriever`, and `cache` are process-lifetime singletons from
    app/main.py. This function borrows them and closes nothing.
    """
    settings = get_settings()
    primary = "en" if (lang or "bn") == "en" else "bn"
    alt_lang = "en" if primary == "bn" else "bn"
    primary_field = "answer_bn" if primary == "bn" else "answer_en"

    # Every collaborator is owned by the application lifespan and passed in. This
    # function used to construct its own on a None default, which meant each
    # question built a ModelRouter, an Embedder with no Redis handle (so no
    # embedding cache at all), and two AsyncQdrantClient instances that were
    # never closed. Requiring them here makes that impossible to reintroduce.
    if router is None or retriever is None or cache is None:
        raise ValueError(
            "stream_grounded_answer requires router, retriever, and cache; "
            "they are built once in app/main.py's lifespan and injected"
        )

    try:
        # 1. Semantic cache. A hit is valid only under the knowledge version
        #    that is live now, which lookup() enforces.
        # Only questions answered *without* a profile are cache-eligible. The cache key
        # is (kb_version, country, lang), which cannot distinguish two students, so a
        # personalised answer put in it would be served to whoever asked next. Sharing
        # one student's stated budget or test score with another is the kind of leak that
        # is obvious in hindsight and invisible in a diff, so the personalised path skips
        # the cache in both directions: no lookup, and no store.
        hit = None if student_context else await cache.lookup(
            question, kb_version_id=kb_version_id, country=country, lang=primary
        )
        if hit is not None:
            yield {
                "kind": "meta",
                "served_by": "cache",
                "cache_hit": True,
                "model_tag": settings.gemma_model,
            }
            if hit.is_refusal:
                yield {
                    "kind": "refusal",
                    "reason_en": hit.refusal_reason_en,
                    "reason_bn": hit.refusal_reason_bn,
                    "watching_portal_ids": [],
                }
                return
            for chunk in _chunks(hit.answer_primary):
                yield {"kind": "token", "text": chunk}
            for c in hit.citations:
                yield {"kind": "citation", **c}
            yield {"kind": "alt", "lang": hit.alt_lang, "text": hit.answer_alt}
            yield {
                "kind": "final",
                "confidence": hit.confidence,
                "answer_primary": hit.answer_primary,
            }
            return

        yield {
            "kind": "meta",
            "served_by": "local",
            "cache_hit": False,
            "model_tag": settings.gemma_model,
        }

        # 2. Retrieve. An empty result is a refusal, never an answer from model
        #    memory: the knowledge store is the only permitted source of fact.
        #
        #    `degraded` means the answer was built from the SQLite lexical fallback
        #    because the vector store returned nothing. The passages and their
        #    citations are just as real, so this is a quality warning rather than a
        #    trust warning, and it is reported rather than hidden.
        passages, degraded = await retriever.search(question, country=country)
        if not passages:
            yield {
                "kind": "refusal",
                "reason_en": NO_SOURCE_EN,
                "reason_bn": NO_SOURCE_BN,
                "watching_portal_ids": [],
            }
            if not student_context:
                await cache.store(
                    question,
                    kb_version_id=kb_version_id,
                    country=country,
                    lang=primary,
                    answer_primary="",
                    answer_alt="",
                    alt_lang=alt_lang,
                    citations=[],
                    confidence=0.0,
                    is_refusal=True,
                    refusal_reason_en=NO_SOURCE_EN,
                    refusal_reason_bn=NO_SOURCE_BN,
                )
            return

        if degraded:
            yield {
                "kind": "degraded",
                "reason_en": (
                    "The vector index is unavailable, so this answer was found by "
                    "keyword search over the same archived sources. Every citation "
                    "below is still a real snapshot, but a closely worded source may "
                    "have been missed."
                ),
                "reason_bn": (
                    "ভেক্টর ইনডেক্স এখন পাওয়া যাচ্ছে না, তাই একই সংরক্ষিত উৎসের ওপর "
                    "কীওয়ার্ড অনুসন্ধান করে এই উত্তরটি পাওয়া গেছে। নিচের প্রতিটি উদ্ধৃতি "
                    "সত্যিকারের স্ন্যাপশট, তবে কাছাকাছি শব্দের কোনো উৎস বাদ পড়ে থাকতে পারে।"
                ),
            }

        by_public_id = {p.snapshot_public_id: p for p in passages}
        # The student's own facts sit between the evidence and the question, so the model
        # reads the sources first and the person second. Leading with the profile
        # encourages an answer about the student instead of one grounded in the passages.
        user_prompt = f"SOURCE PASSAGES:\n{_frame_sources(passages)}\n\n"
        if student_context:
            user_prompt += f"ABOUT THE STUDENT ASKING:\n{student_context}\n\n"
        user_prompt += f"QUESTION: {question}"

        request = LLMRequest(
            kind=TaskKind.GROUNDED_ANSWER,
            messages=[
                {
                    "role": "system",
                    # The profile rule is added only when a profile is present. Telling
                    # the model how to treat a block that is not there wastes context and
                    # invites it to remark on the absence.
                    "content": (
                        f"{SYSTEM_PROMPT}\n{STUDENT_CONTEXT_RULE}"
                        if student_context
                        else SYSTEM_PROMPT
                    ),
                },
                {"role": "user", "content": user_prompt},
            ],
            json_schema=ANSWER_SCHEMA,
            # Tool calling stays off. A model that can call tools while reading
            # untrusted crawled text is a far larger attack surface.
            tools=None,
            thinking=False,
            temperature=0.1,
            # One reply carries two full answers (Bangla and English) plus quoted
            # spans. Bangla costs more tokens per character than English, so 2048
            # truncated real answers mid-JSON; the ceiling is not an allocation,
            # so raising it costs nothing when it is not reached.
            max_tokens=3072,
        )

        # 3. Stream, decoding the answer field out of the partial JSON.
        buffer = ""
        emitted = 0
        async for piece in router.stream(request):
            buffer += piece
            decoded = _partial_string_field(buffer, primary_field)
            if len(decoded) > emitted:
                for chunk in _chunks(decoded[emitted:]):
                    yield {"kind": "token", "text": chunk}
                emitted = len(decoded)

        # 4. Parse the finished object. Citations are emitted only from a valid
        #    parse, so a truncated stream never produces a citation to nothing.
        try:
            data = json.loads(buffer)
        except ValueError:
            # The object never closed, almost always because the generation hit
            # the token ceiling mid-JSON. Two different situations hide here and
            # they need opposite handling.
            #
            # If nothing was emitted, there is no answer and refusing is right.
            #
            # If tokens were already streamed, the student has just read a
            # complete-looking answer. Replacing it with "nothing is shown"
            # contradicts what is on their screen and throws away a real answer.
            # The honest outcome is to keep the text, emit no citations (none can
            # be trusted from a truncated object), and mark the answer
            # incomplete so the interface can say so. The citation guarantee is
            # preserved either way: an uncited answer claims no sources.
            log.warning(
                "grounded answer did not parse, %d chars buffered, %d chars emitted",
                len(buffer), emitted,
            )
            if emitted == 0:
                yield {
                    "kind": "refusal",
                    "reason_en": "The answer could not be produced in a verifiable form, "
                                 "so nothing is shown rather than an unverified answer.",
                    "reason_bn": "উত্তরটি যাচাইযোগ্য আকারে তৈরি করা যায়নি, তাই "
                                 "অযাচাইকৃত উত্তর না দেখিয়ে কিছুই দেখানো হচ্ছে না।",
                    "watching_portal_ids": [],
                }
                return

            salvaged = _partial_string_field(buffer, primary_field)
            if len(salvaged) > emitted:
                for chunk in _chunks(salvaged[emitted:]):
                    yield {"kind": "token", "text": chunk}
            yield {
                "kind": "incomplete",
                "reason_en": "This answer was cut off before its sources could be "
                             "attached, so it is shown without citations. Ask again "
                             "for a fully cited answer.",
                "reason_bn": "এই উত্তরটি উৎস সংযুক্ত হওয়ার আগেই থেমে গেছে, তাই "
                             "উদ্ধৃতি ছাড়াই দেখানো হচ্ছে। সম্পূর্ণ উদ্ধৃতিসহ উত্তরের "
                             "জন্য আবার প্রশ্ন করুন।",
            }
            yield {
                "kind": "final",
                "confidence": None,
                "answer_primary": salvaged,
            }
            # Deliberately not cached: an uncited, truncated answer must not be
            # served to the next student who asks the same thing.
            return

        if data.get("is_refusal"):
            reason = (data.get("refusal_reason") or "").strip() or NO_SOURCE_EN
            yield {
                "kind": "refusal",
                "reason_en": reason,
                "reason_bn": (data.get("answer_bn") or "").strip() or NO_SOURCE_BN,
                "watching_portal_ids": [],
            }
            return

        answer_primary = data.get(primary_field, "") or ""
        answer_alt = data.get("answer_en" if primary == "bn" else "answer_bn", "") or ""

        # Emit anything the incremental decoder missed, so what the student read
        # always equals what gets stored.
        if len(answer_primary) > emitted:
            for chunk in _chunks(answer_primary[emitted:]):
                yield {"kind": "token", "text": chunk}

        citation_payloads: list[dict[str, Any]] = []
        for c in data.get("citations", []):
            src = by_public_id.get(str(c.get("snapshot_id", "")))
            if src is None:
                # A citation naming a snapshot that was never retrieved is the
                # one output that would break the Truth Ledger guarantee, so it
                # is dropped rather than shown.
                log.warning("dropped citation to unretrieved snapshot %s", c.get("snapshot_id"))
                continue
            payload = {
                "ordinal": int(c.get("ordinal", len(citation_payloads) + 1)),
                "snapshot_id": src.snapshot_id,
                "passage_id": src.passage_id,
                "quoted": str(c.get("quoted_span", ""))[:QUOTED_SPAN_MAX_CHARS],
                "snapshot_public_id": src.snapshot_public_id,
                "portal": src.portal,
                "captured": src.captured,
            }
            citation_payloads.append(payload)
            yield {"kind": "citation", **payload}

        yield {"kind": "alt", "lang": alt_lang, "text": answer_alt}
        yield {
            "kind": "final",
            "confidence": data.get("confidence"),
            "answer_primary": answer_primary,
        }

        if not student_context:
            await cache.store(
                question,
                kb_version_id=kb_version_id,
                country=country,
                lang=primary,
                answer_primary=answer_primary,
                answer_alt=answer_alt,
                alt_lang=alt_lang,
                citations=citation_payloads,
                confidence=data.get("confidence"),
                is_refusal=False,
                snapshot_ids=[p.snapshot_id for p in passages],
            )
    except GeneratorExit:
        # The client disconnected mid-stream. Nothing here owns a connection, so
        # there is nothing to release; re-raise so the generator closes promptly
        # rather than being kept alive by the caller's iteration.
        raise
