"""Recursive chunker for parsed resume profiles (DEC-019, active 2026-07-05).

Replaces the Document-Aware chunker (``src.rag.chunker.DocumentAwareChunker``)
as the active strategy for HireIntel AI's regular RAG pipeline. The Document-Aware
chunker is retained for one release as a migration aid.

Why Recursive:
    Resumes do not have uniform section boundaries, and the platform no longer
    uses Section-Routed Evidence Retrieval (DEC-012 → DEC-017). Uniform-sized
    chunks are more comparable under cosine similarity, and the splitter is
    simple, deterministic, and free of model calls.

Algorithm:
    ``RecursiveCharacterTextSplitter`` walks the text using a separator
    hierarchy (``["\\n\\n", "\\n", ". ", " "]``) and accumulates pieces until
    adding the next separator-piece would exceed ``chunk_size``. Adjacent
    pieces share ``chunk_overlap`` characters of trailing text so retrieval
    can recover a chunk that was split mid-sentence. The default values
    ``chunk_size=500`` and ``chunk_overlap=50`` are DEC-019 defaults and are
    also Optuna hyperparameters (DEC-021).

Output:
    A list of :class:`src.rag.chunker.ChunkRecord` objects, sharing the same
    schema as the Document-Aware chunker so downstream code (embedding,
    retrieval, scoring) is unchanged.
"""

from __future__ import annotations

import uuid
from dataclasses import replace
from typing import Any, Dict, Iterable, List, Optional, Sequence

from src.rag.document_aware_chunker import ChunkRecord


# ---------------------------------------------------------------------------
# Tunables (DEC-019 defaults; Optuna hyperparameters per DEC-021).
#
# Owner guidance (2026-07-07): larger chunks reduce the chance that resume
# entries (company/role/dates/bullets) get split across multiple chunks, which
# in turn reduces the failure mode where the rubric LLM sees a skill mention
# but cannot correlate it to a duration because the date line landed in a
# different chunk. The defaults below reflect that guidance:
#
#   chunk_size     = 1000  (was 500)
#   chunk_overlap  = 500   (was 100 — now 50% of chunk_size, ensuring a
#                            date line in chunk N also appears in chunk N+1)
#
# Optuna search-space bounds (widened accordingly):
#   chunk_size     ∈ [500, 1000]  — minimum 500 to avoid over-fragmentation,
#                                    maximum 1000 to prevent token bloat
#   chunk_overlap  ∈ [floor(0.50 * chunk_size), floor(0.60 * chunk_size)]
#                                 — overlap is at least 50% of chunk_size,
#                                    capped at 60%
# The shipped defaults sit at the high end of the search range (1000/500),
# which is the configuration that minimizes date/skill split incidents.
# Promoting a new "Active" config via M0.5d may lower these if the Optuna
# sweep shows a smaller chunk size is sufficient at the operating theta.
# ---------------------------------------------------------------------------

#: Default chunk size in characters. Upper end of [500, 1000].
RECURSIVE_CHUNK_SIZE: int = 1000

#: Default chunk overlap in characters. 50% of chunk_size (= 500 at default).
RECURSIVE_CHUNK_OVERLAP: int = 500

#: Optuna lower/upper bounds for chunk_size (chars).
CHUNK_SIZE_LOWER: int = 500
CHUNK_SIZE_UPPER: int = 1000

#: Minimum overlap as a fraction of chunk_size (not less than 50%).
CHUNK_OVERLAP_MIN_FRACTION: float = 0.50

#: Optuna lower bound for chunk_overlap (chars). Computed per chunk_size.
def min_overlap_for(chunk_size: int) -> int:
    """Return the minimum allowed overlap for a given ``chunk_size``.

    Per owner spec (2026-07-07): overlap is at least 50% of chunk_size.
    """
    return int(CHUNK_OVERLAP_MIN_FRACTION * chunk_size)

#: Maximum overlap as a fraction of chunk_size (not more than 60%).
CHUNK_OVERLAP_MAX_FRACTION: float = 0.60


def max_overlap_for(chunk_size: int) -> int:
    """Return the maximum allowed overlap for a given ``chunk_size``.

    Per owner spec: overlap is at least 50% of chunk_size and capped at 60%.
    """
    return max(min_overlap_for(chunk_size), int(CHUNK_OVERLAP_MAX_FRACTION * chunk_size))

#: Separator hierarchy. Recursive splitter tries the first separator; if a
#: piece is still too large it falls back to the next, and so on. The last
#: separator is a single space; if that still leaves an oversized piece, the
#: splitter hard-splits on character count.
DEFAULT_SEPARATORS: Sequence[str] = ("\n\n", "\n", ". ", " ")


# ---------------------------------------------------------------------------
# Pure-function splitter (no profile required)
# ---------------------------------------------------------------------------


def recursive_split_text(
        text: str,
        chunk_size: int = RECURSIVE_CHUNK_SIZE,
        chunk_overlap: int = RECURSIVE_CHUNK_OVERLAP,
        separators: Sequence[str] = DEFAULT_SEPARATORS,
    ) -> List[str]:
    """Split ``text`` into a list of strings, each at most ``chunk_size`` characters.

    Implements the RecursiveCharacterTextSplitter algorithm without
    depending on LangChain or any third-party library. The splitter tries
    the first separator in ``separators``; if every piece produced is
    already within ``chunk_size``, it returns them. Otherwise it recurses
    on each oversized piece with the next separator. If no separator
    produces a small enough piece (e.g. a single very long word), the
    splitter hard-splits on character count.

    Adjacent pieces share ``chunk_overlap`` characters of trailing text
    from the previous piece, so retrieval can recover a chunk that was
    split mid-sentence.

    Args:
        text:
            The input text. May be empty or whitespace-only; in either case
            an empty list is returned.
        chunk_size:
            Maximum length of any returned piece, in characters.
            Must be in ``[CHUNK_SIZE_LOWER, CHUNK_SIZE_UPPER]``.
        chunk_overlap:
            Number of trailing characters of each piece to prepend to the
            next piece. Must be in
            ``[min_overlap_for(chunk_size), max_overlap_for(chunk_size)]``
            (i.e. 50-60% of chunk_size) and strictly less than ``chunk_size``.
        separators:
            Ordered list of separator strings to try, from most preferred
            (e.g. paragraph break) to least preferred (e.g. space).

    Returns:
        A list of strings, each at most ``chunk_size`` characters long,
        in the order they appear in the source text. Empty input returns
        an empty list.

    Raises:
        ValueError:
            If ``chunk_size`` or ``chunk_overlap`` is outside its
            owner-specified bound, or ``chunk_overlap >= chunk_size``.
    """
    if not CHUNK_SIZE_LOWER <= chunk_size <= CHUNK_SIZE_UPPER:
        raise ValueError(
            f"chunk_size must be in [{CHUNK_SIZE_LOWER}, {CHUNK_SIZE_UPPER}], "
            f"got {chunk_size}"
        )
    max_overlap = max_overlap_for(chunk_size)
    min_overlap = min_overlap_for(chunk_size)
    if not min_overlap <= chunk_overlap <= max_overlap:
        raise ValueError(
            f"chunk_overlap must be in [{min_overlap}, {max_overlap}] "
            f"for chunk_size={chunk_size}; got chunk_overlap={chunk_overlap}"
        )
    if chunk_overlap >= chunk_size:
        raise ValueError(
            f"chunk_overlap must be < chunk_size; "
            f"got chunk_overlap={chunk_overlap} chunk_size={chunk_size}"
        )

    text = text.strip()
    if not text:
        return []

    return _split_recursive(text, chunk_size, chunk_overlap, tuple(separators))


def _split_recursive(
    text: str,
    chunk_size: int,
    chunk_overlap: int,
    separators: Sequence[str],
) -> List[str]:
    """Recursive helper. Picks the first usable separator and recurses on oversize pieces."""
    if len(text) <= chunk_size:
        return [text]

    if not separators:
        # No separator worked: hard-split on character count. This branch
        # is rare (only triggered for a single token longer than chunk_size).
        return _hard_split(text, chunk_size, chunk_overlap)

    separator = separators[0]
    remaining = separators[1:]

    if separator and separator in text:
        raw_pieces = text.split(separator)
    else:
        # Separator not in text: recurse with the next separator, treating
        # the whole text as a single piece.
        return _split_recursive(text, chunk_size, chunk_overlap, remaining)

    out: List[str] = []
    buffer: List[str] = []
    buffer_len = 0  # sum of piece lengths plus separator lengths

    def flush() -> None:
        nonlocal buffer, buffer_len
        if not buffer:
            return
        joined = separator.join(buffer)
        out.append(joined)
        buffer = []
        buffer_len = 0

    for piece in raw_pieces:
        piece = piece.strip()
        if not piece:
            continue
        # If a single piece is itself larger than chunk_size, flush and
        # recurse on it with the next separator.
        if len(piece) > chunk_size:
            flush()
            sub = _split_recursive(piece, chunk_size, chunk_overlap, remaining)
            out.extend(sub)
            continue

        # Length if we add this piece + the joining separator.
        prospective_len = buffer_len + len(piece) + (len(separator) if buffer else 0)
        if prospective_len <= chunk_size:
            buffer.append(piece)
            buffer_len = prospective_len
        else:
            flush()
            buffer.append(piece)
            buffer_len = len(piece)

    flush()
    return _apply_overlap(out, chunk_overlap)


def _hard_split(text: str, chunk_size: int, chunk_overlap: int) -> List[str]:
    """Last-resort hard split on character count."""
    out: List[str] = []
    cursor = 0
    while cursor < len(text):
        end = min(cursor + chunk_size, len(text))
        out.append(text[cursor:end])
        if end >= len(text):
            break
        cursor = max(end - chunk_overlap, cursor + 1)
    return out


def _apply_overlap(pieces: List[str], chunk_overlap: int) -> List[str]:
    """Prepend ``chunk_overlap`` trailing characters of piece ``i`` to piece ``i+1``."""
    if chunk_overlap <= 0 or len(pieces) <= 1:
        return pieces

    out: List[str] = [pieces[0]]
    for i in range(1, len(pieces)):
        prev = pieces[i - 1]
        tail = prev[-chunk_overlap:] if len(prev) > chunk_overlap else prev
        # Prepend a single space if the previous piece did not end in whitespace
        # and the current piece does not start with one.
        if tail and not tail[-1].isspace() and pieces[i] and not pieces[i][0].isspace():
            tail = tail + " "
        out.append((tail + pieces[i]).strip())
    return out


# ---------------------------------------------------------------------------
# Chunker class — the public API for the active strategy (DEC-019)
# ---------------------------------------------------------------------------


class RecursiveChunker:
    """Recursive chunker (DEC-019). The active chunking strategy.

    Wraps :func:`recursive_split_text` and produces :class:`ChunkRecord`
    objects that share the schema of the Document-Aware chunker so
    downstream embedding, retrieval, and scoring code is unchanged.

    Typical usage::

        chunker = RecursiveChunker(chunk_size=500, chunk_overlap=50)
        chunks = chunker.chunk_profile(parsed_profile, role_bucket="BusinessAnalyst")

    Args:
        chunk_size:
            Maximum chunk length in characters. Default
            :data:`RECURSIVE_CHUNK_SIZE` (500).
        chunk_overlap:
            Overlap between adjacent chunks in characters. Default
            :data:`RECURSIVE_CHUNK_OVERLAP` (50).
        separators:
            Separator hierarchy tried in order. Default
            :data:`DEFAULT_SEPARATORS`.
        section_type:
            The ``section_type`` value written to every chunk this
            chunker produces. Document-Aware emitted one section_type per
            chunk (e.g. "experience"); the Recursive chunker emits a
            single ``section_type="document"`` (or a caller-provided
            override). Per DEC-019, ``section_type`` is now a soft tag
            used only by the structured profile, not by retrieval.
    """

    def __init__(
        self,
        chunk_size: int = RECURSIVE_CHUNK_SIZE,
        chunk_overlap: int = RECURSIVE_CHUNK_OVERLAP,
        separators: Sequence[str] = DEFAULT_SEPARATORS,
        section_type: str = "document",
    ) -> None:
        if not CHUNK_SIZE_LOWER <= chunk_size <= CHUNK_SIZE_UPPER:
            raise ValueError(
                f"chunk_size must be in [{CHUNK_SIZE_LOWER}, {CHUNK_SIZE_UPPER}], "
                f"got {chunk_size}"
            )
        max_overlap = max_overlap_for(chunk_size)
        min_overlap = min_overlap_for(chunk_size)
        if not min_overlap <= chunk_overlap <= max_overlap:
            raise ValueError(
                f"chunk_overlap must be in [{min_overlap}, {max_overlap}] "
                f"for chunk_size={chunk_size} (overlap is 50-60% of chunk_size); "
                f"got chunk_overlap={chunk_overlap}"
            )
        if chunk_overlap >= chunk_size:
            raise ValueError(
                f"chunk_overlap must be < chunk_size; "
                f"got chunk_overlap={chunk_overlap} chunk_size={chunk_size}"
            )
        if not separators:
            raise ValueError("separators must be a non-empty sequence")

        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = tuple(separators)
        self.section_type = section_type

    def chunk_text(
        self,
        text: str,
        candidate_id: str,
        role_bucket: str = "",
        source_file: str = "",
        base_metadata: Optional[Dict[str, Any]] = None,
    ) -> List[ChunkRecord]:
        """Split a single block of text into ChunkRecord objects.

        Use this when you have a raw text block (e.g. one section of a
        resume) and want uniform Recursive chunks. For full-profile
        chunking, prefer :meth:`chunk_profile`.

        Args:
            text:
                The text to chunk. Empty/whitespace returns an empty list.
            candidate_id:
                The candidate identifier. Used in ``chunk_id``.
            role_bucket:
                The role folder the resume was filed under.
            source_file:
                The original source file path, if any.
            base_metadata:
                Optional metadata dict to copy into every chunk's
                ``metadata`` field.

        Returns:
            A list of :class:`ChunkRecord`. ``chunk_id`` is
            ``{candidate_id}__{chunk_index}`` per the DEC-023 simplified
            schema. ``section_type`` is whatever the chunker was
            constructed with (default ``"document"``).
        """
        pieces = recursive_split_text(
            text,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=self.separators,
        )
        if not pieces:
            return []

        metadata_template = dict(base_metadata or {})
        out: List[ChunkRecord] = []
        cursor = 0
        for i, piece in enumerate(pieces):
            start = text.find(piece, cursor)
            if start < 0:
                start = cursor
            end = start + len(piece)
            cursor = end
            out.append(
                ChunkRecord(
                    chunk_id=f"{candidate_id}__{i}",
                    candidate_id=candidate_id,
                    role_bucket=role_bucket,
                    source_file=source_file,
                    section=self.section_type,
                    chunk_index=i,
                    text=piece,
                    char_span=(start, end),
                    metadata=dict(metadata_template),
                    section_type=self.section_type,
                    parent_structure={},
                    skills_asserted=[],
                    experience_type="unknown",
                )
            )
        return out

    def chunk_profile(
        self,
        profile: Dict[str, Any],
        role_bucket: str = "",
    ) -> List[ChunkRecord]:
        """Convert one parsed profile into a list of chunk records.

        The Document-Aware chunker emits one chunk per section. The
        Recursive chunker emits chunks that respect the section
        boundaries as soft groupers (one ``chunk_index`` series per
        section) but the chunk size and shape are uniform within each
        section. This is a deliberate trade-off: simpler, more
        cosine-friendly chunks, at the cost of less section coherence.

        Args:
            profile:
                A parsed resume dict as produced by
                :func:`src.resume_parsing.parser.parse_resume`.
            role_bucket:
                The role folder the resume was filed under
                (``"BusinessAnalyst"``, ``"DataScience"`` ...). Used as
                a metadata field so the vector store can be filtered by
                role.

        Returns:
            List of :class:`ChunkRecord`. Order is deterministic:
            summary, experience entries, education entries, projects,
            skills, certifications, languages.
        """
        candidate_id = profile.get("candidate_id") or "cand_unknown"
        source_file = profile.get("source_file", "")

        # Per-section input text + the section's "label" we use for
        # ``ChunkRecord.section``. Order matches the Document-Aware
        # chunker to keep downstream consumers stable.
        sections: List[tuple[str, str]] = []  # (section_name, text)

        summary = profile.get("summary") or {}
        if isinstance(summary, dict):
            summary_text = (summary.get("value") or summary.get("text") or "").strip()
        else:
            summary_text = str(summary or "").strip()
        if summary_text:
            sections.append(("summary", summary_text))

        experience = profile.get("experience") or {}
        # ``experience`` is canonically a dict with an ``entries`` list, but
        # downstream artifacts sometimes store it as a list or a string.
        # Coerce to the canonical shape so chunk_profile doesn't crash.
        if isinstance(experience, dict):
            exp_entries = experience.get("entries") or []
        elif isinstance(experience, list):
            exp_entries = experience
        else:
            exp_entries = []
        for i, entry in enumerate(exp_entries):
            sections.append((f"experience_{i}", _entry_to_text(entry)))

        education = profile.get("education") or {}
        # Same defensive coercion as for ``experience``: ``education`` may be
        # a dict (canonical), a list (downstream artifact), a string, or null.
        if isinstance(education, dict):
            edu_entries = education.get("entries") or []
        elif isinstance(education, list):
            edu_entries = education
        else:
            edu_entries = []
        for i, entry in enumerate(edu_entries):
            sections.append((f"education_{i}", _entry_to_text(entry)))

        projects = profile.get("projects") or []
        if isinstance(projects, list):
            for i, proj in enumerate(projects):
                sections.append((f"project_{i}", str(proj).strip()))
        elif isinstance(projects, str) and projects.strip():
            sections.append(("projects", projects.strip()))

        skills = profile.get("skills") or []
        if isinstance(skills, list):
            skills_text = ", ".join(str(s) for s in skills if s)
        else:
            skills_text = str(skills)
        if skills_text.strip():
            sections.append(("skills", skills_text))

        certifications = profile.get("certifications") or []
        if isinstance(certifications, list):
            certs_text = ", ".join(str(c) for c in certifications if c)
        else:
            certs_text = str(certifications)
        if certs_text.strip():
            sections.append(("certifications", certs_text))

        languages = profile.get("languages") or []
        if isinstance(languages, list):
            langs_text = ", ".join(str(l) for l in languages if l)
        else:
            langs_text = str(languages)
        if langs_text.strip():
            sections.append(("languages", langs_text))

        out: List[ChunkRecord] = []
        for section_name, text in sections:
            base_metadata = {"section": section_name}
            section_chunker = RecursiveChunker(
                chunk_size=self.chunk_size,
                chunk_overlap=self.chunk_overlap,
                separators=self.separators,
                section_type=section_name,
            )
            out.extend(
                section_chunker.chunk_text(
                    text,
                    candidate_id=candidate_id,
                    role_bucket=role_bucket,
                    source_file=source_file,
                    base_metadata=base_metadata,
                )
            )

        return _renumber_chunks(out, candidate_id)


def _renumber_chunks(chunks: List[ChunkRecord], candidate_id: str) -> List[ChunkRecord]:
    """Reassign ``chunk_id`` and ``chunk_index`` to be globally increasing."""
    out: List[ChunkRecord] = []
    for i, c in enumerate(chunks):
        out.append(
            replace(
                c,
                chunk_id=f"{candidate_id}__{i}",
                chunk_index=i,
            )
        )
    return out


def _entry_to_text(entry: Any) -> str:
    """Render an experience/education entry as a single human-readable block.

    Mirrors the helper in :mod:`src.rag.chunker` but does not depend on it
    (so this module can be imported without side effects).
    """
    if not isinstance(entry, dict):
        return str(entry or "").strip()
    parts: List[str] = []
    title = (entry.get("title") or "").strip()
    company = (entry.get("company") or "").strip()
    description = (entry.get("description") or "").strip()
    if title and company:
        parts.append(f"{title} @ {company}")
    elif title:
        parts.append(title)
    elif company:
        parts.append(company)
    elif description:
        parts.append(description)
    dates = (entry.get("dates") or "").strip()
    location = (entry.get("location") or "").strip()
    if dates or location:
        meta = " | ".join(x for x in (dates, location) if x)
        parts.append(meta)
    details = [str(d).strip() for d in (entry.get("details") or []) if d and str(d).strip()]
    for bullet in details:
        parts.append(f"- {bullet}")
    return "\n".join(parts).strip()


__all__ = [
    "RECURSIVE_CHUNK_SIZE",
    "RECURSIVE_CHUNK_OVERLAP",
    "CHUNK_SIZE_LOWER",
    "CHUNK_SIZE_UPPER",
    "CHUNK_OVERLAP_MIN_FRACTION",
    "CHUNK_OVERLAP_MAX_FRACTION",
    "min_overlap_for",
    "max_overlap_for",
    "DEFAULT_SEPARATORS",
    "RecursiveChunker",
    "recursive_split_text",
]
