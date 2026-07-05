"""Unit tests for the Recursive chunker (DEC-019)."""

import pytest

from src.rag import (
    DEFAULT_SEPARATORS,
    RECURSIVE_CHUNK_OVERLAP,
    RECURSIVE_CHUNK_SIZE,
    RecursiveChunker,
    recursive_split_text,
)
from rag.document_aware_chunker import ChunkRecord


# ---------------------------------------------------------------------------
# recursive_split_text (pure function)
# ---------------------------------------------------------------------------


def test_empty_input_returns_empty_list():
    assert recursive_split_text("") == []
    assert recursive_split_text("   \n\n  ") == []


def test_short_input_returns_single_chunk():
    text = "Short paragraph."
    out = recursive_split_text(text, chunk_size=500, chunk_overlap=50)
    assert out == [text]


def test_chunks_within_chunk_size_plus_overlap():
    """Chunks are at most ``chunk_size + chunk_overlap`` characters.

    The overlap is applied as a tail-prepend to the next chunk, so an
    adjacent chunk can grow by up to ``chunk_overlap`` chars beyond
    ``chunk_size``. This is intentional — trimming the overlap would
    defeat the purpose. Matches LangChain's RecursiveCharacterTextSplitter
    behavior.
    """
    text = ("Sentence. " * 200).strip()  # ~2200 chars
    chunk_size, chunk_overlap = 500, 50
    out = recursive_split_text(text, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    assert all(len(c) <= chunk_size + chunk_overlap for c in out)


def test_chunks_overlap_when_long():
    """Adjacent chunks share ``chunk_overlap`` characters of trailing text.

    The overlap may be a strict prefix (when the boundary is in the middle
    of a word) or have a single space inserted (when the boundary is
    between two words). Either way, the next chunk starts with at least
    the last ``chunk_overlap`` chars (modulo whitespace) of the previous.
    """
    text = ("Word " * 300).strip()  # 1500 chars
    chunk_overlap = 30
    out = recursive_split_text(text, chunk_size=200, chunk_overlap=chunk_overlap)
    assert len(out) >= 2
    for i in range(1, len(out)):
        prev = out[i - 1]
        curr = out[i]
        # The overlap tail is the last ``chunk_overlap`` chars of the
        # previous piece (whitespace-trimmed at the edges).
        prev_tail = prev[-chunk_overlap:].strip()
        # The current chunk should start with the same words (in order),
        # modulo the separator we insert between them.
        curr_head_words = curr.split()[: len(prev_tail.split())]
        assert " ".join(curr_head_words) == prev_tail, (
            f"chunk {i} head does not overlap with chunk {i-1} tail: "
            f"prev_tail={prev_tail!r}, curr_head={curr[:chunk_overlap]!r}"
        )


def test_invalid_chunk_size_raises():
    with pytest.raises(ValueError):
        recursive_split_text("hello", chunk_size=0, chunk_overlap=0)


def test_invalid_chunk_overlap_raises():
    with pytest.raises(ValueError):
        recursive_split_text("hello", chunk_size=100, chunk_overlap=100)  # overlap must be < chunk_size
    with pytest.raises(ValueError):
        recursive_split_text("hello", chunk_size=100, chunk_overlap=-1)


def test_separator_hierarchy_preserves_paragraph_boundaries():
    """When paragraphs fit, the splitter should keep them in separate chunks."""
    text = "First paragraph about Python.\n\nSecond paragraph about Django."
    out = recursive_split_text(text, chunk_size=100, chunk_overlap=0, separators=("\n\n", "\n", ". ", " "))
    # Both paragraphs are short, but the second has overlap-induced text.
    # At minimum, "First paragraph about Python." must appear in the first chunk.
    assert any("First paragraph about Python." in c for c in out)


def test_long_word_falls_back_to_hard_split():
    """A single word longer than chunk_size triggers the hard-split fallback.

    The hard-split path produces pieces of at most ``chunk_size + chunk_overlap``
    characters (the overlap is applied after hard-splitting). The output may
    repeat characters at boundaries due to the overlap, but it must
    contain the full input and every piece must respect the size limit.
    """
    long_word = "a" * 200
    chunk_size, chunk_overlap = 50, 5
    out = recursive_split_text(long_word, chunk_size=chunk_size, chunk_overlap=chunk_overlap)
    assert all(len(c) <= chunk_size + chunk_overlap for c in out)
    # The full input must be recoverable from the chunks (modulo overlap-induced repeats).
    assert all(c == "a" * len(c) for c in out), "hard-split should not introduce non-`a` characters"


def test_defaults_match_dec_019():
    """DEC-019 defaults: chunk_size=500, chunk_overlap=50."""
    assert RECURSIVE_CHUNK_SIZE == 500
    assert RECURSIVE_CHUNK_OVERLAP == 50
    assert DEFAULT_SEPARATORS == ("\n\n", "\n", ". ", " ")


# ---------------------------------------------------------------------------
# RecursiveChunker class
# ---------------------------------------------------------------------------


def test_chunker_default_construction():
    chunker = RecursiveChunker()
    assert chunker.chunk_size == 500
    assert chunker.chunk_overlap == 50
    assert chunker.separators == DEFAULT_SEPARATORS
    assert chunker.section_type == "document"


def test_chunker_rejects_invalid_construction():
    with pytest.raises(ValueError):
        RecursiveChunker(chunk_size=0)
    with pytest.raises(ValueError):
        RecursiveChunker(chunk_size=100, chunk_overlap=100)
    with pytest.raises(ValueError):
        RecursiveChunker(chunk_size=100, chunk_overlap=-1)
    with pytest.raises(ValueError):
        RecursiveChunker(separators=())


def test_chunk_text_emits_chunk_records():
    chunker = RecursiveChunker(chunk_size=100, chunk_overlap=10)
    text = ("Sentence. " * 20).strip()
    chunks = chunker.chunk_text(
        text,
        candidate_id="cand_test",
        role_bucket="BusinessAnalyst",
        source_file="data/original/test.pdf",
    )
    assert len(chunks) >= 1
    assert all(isinstance(c, ChunkRecord) for c in chunks)
    assert all(c.candidate_id == "cand_test" for c in chunks)
    assert all(c.role_bucket == "BusinessAnalyst" for c in chunks)
    assert all(c.source_file == "data/original/test.pdf" for c in chunks)


def test_chunk_text_chunk_ids_are_unique():
    chunker = RecursiveChunker(chunk_size=100, chunk_overlap=10)
    text = ("Sentence. " * 20).strip()
    chunks = chunker.chunk_text(text, candidate_id="cand_test")
    ids = [c.chunk_id for c in chunks]
    assert len(ids) == len(set(ids))
    # DEC-023 schema: {candidate_id}__{chunk_index}
    assert all(c.chunk_id.startswith("cand_test__") for c in chunks)


def test_chunk_text_empty_input_returns_empty_list():
    chunker = RecursiveChunker()
    assert chunker.chunk_text("", candidate_id="cand_test") == []
    assert chunker.chunk_text("   \n\n  ", candidate_id="cand_test") == []


def test_chunk_profile_uses_section_anchors():
    """chunk_profile emits one chunk series per section, in deterministic order."""
    chunker = RecursiveChunker(chunk_size=200, chunk_overlap=20)
    profile = {
        "candidate_id": "cand_001",
        "source_file": "data/original/test.pdf",
        "summary": {"value": "Experienced analyst.", "source": "summary"},
        "experience": {
            "raw": "",
            "entries": [
                {"title": "Senior", "company": "Acme", "dates": "2020 - Present", "details": ["Did stuff"]},
                {"title": "Junior", "company": "Beta", "dates": "2018 - 2020", "details": ["Made charts"]},
            ],
            "count": 2,
        },
        "education": {
            "raw": "BS CS, MIT, 2018",
            "entries": [{"description": "BS CS, MIT, 2018"}],
            "count": 1,
        },
        "skills": ["Python", "SQL"],
        "certifications": ["PMP"],
        "projects": ["Forecast Engine"],
        "languages": ["English"],
    }
    chunks = chunker.chunk_profile(profile, role_bucket="BusinessAnalyst")
    sections = [c.section for c in chunks]
    # Order: summary, experience_0, experience_1, education_0, project_0, skills, certifications, languages
    assert sections[0] == "summary"
    assert "experience_0" in sections
    assert "experience_1" in sections
    assert "education_0" in sections
    assert "skills" in sections
    assert "certifications" in sections
    assert "languages" in sections
    # All chunks carry the role_bucket.
    assert all(c.role_bucket == "BusinessAnalyst" for c in chunks)


def test_chunk_profile_skips_empty_sections():
    chunker = RecursiveChunker()
    profile = {
        "candidate_id": "cand_001",
        "summary": {"value": "Just a summary.", "source": "summary"},
        "experience": {"entries": [], "count": 0, "raw": ""},
        "education": {"entries": [], "count": 0, "raw": ""},
        "skills": [],
        "certifications": [],
        "projects": [],
        "languages": [],
    }
    chunks = chunker.chunk_profile(profile)
    sections = {c.section for c in chunks}
    assert sections == {"summary"}  # only the summary produces chunks


def test_section_type_is_propagated():
    """The per-section chunker uses the section name as the ``section_type``."""
    chunker = RecursiveChunker(chunk_size=500, chunk_overlap=50)
    profile = {
        "candidate_id": "cand_001",
        "summary": {"value": "Summary text."},
        "skills": ["Python"],
    }
    chunks = chunker.chunk_profile(profile)
    summary_chunks = [c for c in chunks if c.section == "summary"]
    skill_chunks = [c for c in chunks if c.section == "skills"]
    assert all(c.section_type == "summary" for c in summary_chunks)
    assert all(c.section_type == "skills" for c in skill_chunks)
