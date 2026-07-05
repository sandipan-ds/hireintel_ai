"""Unit tests for the chunk report module (DEC-024)."""

import json
import tempfile
from pathlib import Path

import pytest

from src.reporting.chunk_report import (
    SCHEMA_VERSION,
    ChunkReport,
    ChunkStatistics,
    generate_chunk_report,
    write_json_report,
    write_markdown_report,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def toy_corpus(tmp_path: Path) -> Path:
    """A tiny 4-resume corpus with 2 roles and a known section_type mix.

    Resume 1 (role A): 3 chunks, all section_type="experience"
    Resume 2 (role A): 2 chunks, all section_type="education"
    Resume 3 (role B): 4 chunks, all section_type=""
    Resume 4 (role B): 1 chunk, section_type="skills"

    Total: 10 chunks across 4 resumes across 2 roles.
    Section_type empty rate: 4/10 = 0.4 (i.e. 40%).
    """
    root = tmp_path / "chunks"
    role_a = root / "RoleA"
    role_b = root / "RoleB"
    role_a.mkdir(parents=True)
    role_b.mkdir(parents=True)

    (role_a / "c1.jsonl").write_text(
        "\n".join(
            json.dumps({"chunk_id": f"c1__{i}", "section_type": "experience", "text": "x"})
            for i in range(3)
        )
    )
    (role_a / "c2.jsonl").write_text(
        "\n".join(
            json.dumps({"chunk_id": f"c2__{i}", "section_type": "education", "text": "x"})
            for i in range(2)
        )
    )
    (role_b / "c3.jsonl").write_text(
        "\n".join(
            json.dumps({"chunk_id": f"c3__{i}", "section_type": "", "text": "x"})
            for i in range(4)
        )
    )
    (role_b / "c4.jsonl").write_text(
        json.dumps({"chunk_id": "c4__0", "section_type": "skills", "text": "x"})
    )
    return root


# ---------------------------------------------------------------------------
# generate_chunk_report
# ---------------------------------------------------------------------------


def test_generate_chunk_report_basic(toy_corpus):
    report = generate_chunk_report(
        experiment_name="document_aware_chunking",
        chunks_root=str(toy_corpus),
        chunker="DocumentAwareChunker",
        source="test corpus",
        iso_now="2026-07-05T10:00:00Z",
    )
    assert isinstance(report, ChunkReport)
    assert report.schema_version == SCHEMA_VERSION
    assert report.experiment_name == "document_aware_chunking"
    assert report.chunker == "DocumentAwareChunker"
    assert report.source == "test corpus"
    assert report.created_at == "2026-07-05T10:00:00Z"


def test_generate_chunk_report_statistics(toy_corpus):
    report = generate_chunk_report(
        experiment_name="test",
        chunks_root=str(toy_corpus),
        chunker="TestChunker",
        iso_now="2026-07-05T10:00:00Z",
    )
    stats = report.chunk_statistics
    assert stats.total_chunks == 10
    assert stats.total_resumes == 4
    assert stats.chunks_per_role == {"RoleA": 5, "RoleB": 5}
    assert stats.chunks_with_section_type_empty == 4
    assert stats.section_type_empty_rate == pytest.approx(0.4)
    assert stats.chunks_per_resume["mean"] == 2.5
    assert stats.chunks_per_resume["min"] == 1
    assert stats.chunks_per_resume["max"] == 4
    assert stats.section_type_distribution == {
        "experience": 3,
        "education": 2,
        "": 4,
        "skills": 1,
    }


def test_generate_chunk_report_finds_dec_015_bug(toy_corpus):
    """A corpus with 40%+ missing section_type gets the DEC-015 finding."""
    report = generate_chunk_report(
        experiment_name="test",
        chunks_root=str(toy_corpus),
        chunker="DocumentAwareChunker",
        iso_now="2026-07-05T10:00:00Z",
    )
    assert any("DEC-015" in f for f in report.key_findings)
    assert "Retire DocumentAwareChunker" in report.recommendation


def test_generate_chunk_report_empty_corpus(tmp_path):
    """An empty corpus produces a 'no chunks found' finding."""
    empty = tmp_path / "empty"
    empty.mkdir()
    report = generate_chunk_report(
        experiment_name="empty",
        chunks_root=str(empty),
        chunker="TestChunker",
        iso_now="2026-07-05T10:00:00Z",
    )
    assert report.chunk_statistics.total_chunks == 0
    assert any("no chunks" in f.lower() for f in report.key_findings)


def test_generate_chunk_report_missing_root(tmp_path):
    with pytest.raises(FileNotFoundError):
        generate_chunk_report(
            experiment_name="missing",
            chunks_root=str(tmp_path / "does_not_exist"),
            chunker="TestChunker",
        )


def test_generate_chunk_report_skips_malformed_jsonl(tmp_path):
    """Malformed JSONL lines are skipped (with a warning), not crashed."""
    root = tmp_path / "chunks"
    role = root / "RoleA"
    role.mkdir(parents=True)
    (role / "c1.jsonl").write_text(
        '{"chunk_id": "c1__0", "section_type": "experience", "text": "x"}\n'
        "this is not json\n"
        '{"chunk_id": "c1__1", "section_type": "education", "text": "x"}\n'
    )
    report = generate_chunk_report(
        experiment_name="malformed",
        chunks_root=str(root),
        chunker="TestChunker",
        iso_now="2026-07-05T10:00:00Z",
    )
    assert report.chunk_statistics.total_chunks == 2  # malformed line skipped


def test_generate_chunk_report_config_recorded(toy_corpus):
    report = generate_chunk_report(
        experiment_name="test",
        chunks_root=str(toy_corpus),
        chunker="RecursiveChunker",
        config={"chunk_size": 500, "chunk_overlap": 50},
        iso_now="2026-07-05T10:00:00Z",
    )
    assert report.config == {"chunk_size": 500, "chunk_overlap": 50}


def test_chunks_per_resume_distribution(toy_corpus):
    report = generate_chunk_report(
        experiment_name="test",
        chunks_root=str(toy_corpus),
        chunker="TestChunker",
        iso_now="2026-07-05T10:00:00Z",
    )
    cpr = report.chunk_statistics.chunks_per_resume
    # 4 resumes with [3, 2, 4, 1] chunks -> mean=2.5, median=2.5
    assert cpr["mean"] == 2.5
    assert cpr["median"] == 2.5
    assert cpr["min"] == 1
    assert cpr["max"] == 4
    # 4 samples sorted = [1, 2, 3, 4]. p95 = values[0.95 * 3] = values[2.85].
    # Linear interp between values[2]=3 and values[3]=4 at frac=0.85: 3 + 0.85 = 3.85, rounds to 4.
    assert cpr["p95"] == 4


# ---------------------------------------------------------------------------
# write_json_report / write_markdown_report
# ---------------------------------------------------------------------------


def test_write_json_report_creates_file(toy_corpus):
    report = generate_chunk_report(
        experiment_name="test",
        chunks_root=str(toy_corpus),
        chunker="TestChunker",
        iso_now="2026-07-05T10:00:00Z",
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.json"
        write_json_report(report, str(out))
        assert out.exists()
        loaded = json.loads(out.read_text())
        assert loaded["experiment_name"] == "test"
        assert loaded["chunker"] == "TestChunker"
        assert loaded["chunk_statistics"]["total_chunks"] == 10


def test_write_json_report_creates_parent_dirs(toy_corpus):
    report = generate_chunk_report(
        experiment_name="test",
        chunks_root=str(toy_corpus),
        chunker="TestChunker",
        iso_now="2026-07-05T10:00:00Z",
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "deep" / "nested" / "report.json"
        write_json_report(report, str(out))
        assert out.exists()


def test_write_markdown_report_creates_file(toy_corpus):
    report = generate_chunk_report(
        experiment_name="document_aware_chunking",
        chunks_root=str(toy_corpus),
        chunker="DocumentAwareChunker",
        source="pre-DEC-019 production chunks",
        config={"max_chunk_chars": 1200, "split_overlap_chars": 120},
        iso_now="2026-07-05T10:00:00Z",
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.md"
        write_markdown_report(report, str(out))
        text = out.read_text()
        # Key sections must appear.
        assert "# Chunk Report" in text
        assert "document_aware_chunking" in text
        assert "## Chunk statistics" in text
        assert "## Key findings" in text
        assert "## Recommendation" in text
        assert "DocumentAwareChunker" in text
        assert "## Config" in text
        assert "1200" in text
        assert "DEC-015" in text or "Retire" in text


def test_write_markdown_report_includes_section_type_table(toy_corpus):
    report = generate_chunk_report(
        experiment_name="test",
        chunks_root=str(toy_corpus),
        chunker="TestChunker",
        iso_now="2026-07-05T10:00:00Z",
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.md"
        write_markdown_report(report, str(out))
        text = out.read_text()
        # Section-type distribution should be a markdown table.
        assert "### Section type distribution" in text
        assert "| Section type | Count |" in text
        assert "| (empty) | 4 |" in text


def test_write_markdown_report_includes_role_table(toy_corpus):
    report = generate_chunk_report(
        experiment_name="test",
        chunks_root=str(toy_corpus),
        chunker="TestChunker",
        iso_now="2026-07-05T10:00:00Z",
    )
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "report.md"
        write_markdown_report(report, str(out))
        text = out.read_text()
        assert "### Chunks per role" in text
        assert "| Role | Chunks |" in text
        assert "| RoleA | 5 |" in text
        assert "| RoleB | 5 |" in text


# ---------------------------------------------------------------------------
# Recommendation logic
# ---------------------------------------------------------------------------


def test_recommendation_for_healthy_corpus(tmp_path):
    """A corpus with low empty-rate and reasonable chunk counts is healthy."""
    root = tmp_path / "chunks"
    role = root / "RoleA"
    role.mkdir(parents=True)
    (role / "c1.jsonl").write_text(
        "\n".join(
            json.dumps({"chunk_id": f"c1__{i}", "section_type": "experience", "text": "x"})
            for i in range(5)
        )
    )
    report = generate_chunk_report(
        experiment_name="healthy",
        chunks_root=str(root),
        chunker="TestChunker",
        iso_now="2026-07-05T10:00:00Z",
    )
    assert "healthy" in report.recommendation.lower() or "no immediate action" in report.recommendation.lower()


def test_recommendation_for_corpus_with_too_many_chunks(tmp_path):
    """A single resume with > 50 chunks triggers a size warning."""
    root = tmp_path / "chunks"
    role = root / "RoleA"
    role.mkdir(parents=True)
    (role / "c1.jsonl").write_text(
        "\n".join(
            json.dumps({"chunk_id": f"c1__{i}", "section_type": "experience", "text": "x"})
            for i in range(60)
        )
    )
    report = generate_chunk_report(
        experiment_name="too_many",
        chunks_root=str(root),
        chunker="TestChunker",
        iso_now="2026-07-05T10:00:00Z",
    )
    assert "raising chunk_size" in report.recommendation.lower() or "per-resume cap" in report.recommendation.lower()


# ---------------------------------------------------------------------------
# Schema dataclasses
# ---------------------------------------------------------------------------


def test_chunk_statistics_to_dict():
    stats = ChunkStatistics(total_chunks=10, total_resumes=2)
    d = stats.to_dict()
    assert d["total_chunks"] == 10
    assert d["total_resumes"] == 2


def test_chunk_report_to_dict():
    report = ChunkReport(
        schema_version=SCHEMA_VERSION,
        experiment_name="x",
        experiment_folder="/x",
        created_at="2026-07-05T10:00:00Z",
        source="",
        chunker="TestChunker",
        config={},
        chunk_statistics=ChunkStatistics(),
    )
    d = report.to_dict()
    assert d["experiment_name"] == "x"
    assert d["chunk_statistics"]["total_chunks"] == 0
