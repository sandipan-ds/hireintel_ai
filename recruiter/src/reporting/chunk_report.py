"""Per-experiment chunk diagnostic reports (DEC-024, M0.5f-a/b).

Generates a structured report for a chunking experiment — Document-Aware
historical or any Recursive ``data/recursive_chunking_<params>/`` folder.
The report captures chunk statistics, the ``section_type=""`` rate (the
DEC-015 bug), and a human-readable summary.

The reports are committed to git (small text files) so the historical
record of every chunking experiment is preserved. Binaries (chunks,
index, caches) stay in ``.gitignore``; reports do not.

Output paths:
    ``reports/chunk_reports/<experiment_name>_report.json`` — structured
    ``reports/chunk_reports/<experiment_name>_report.md``   — human-readable
"""

from __future__ import annotations

import json
import logging
import statistics
from collections import Counter
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

#: Current schema version. Bump on any breaking change to the report shape.
SCHEMA_VERSION: str = "1.0"


@dataclass
class ChunkStatistics:
    """Aggregate statistics about a chunked corpus."""

    total_chunks: int = 0
    total_resumes: int = 0
    chunks_per_role: Dict[str, int] = field(default_factory=dict)
    chunks_per_resume: Dict[str, float] = field(
        default_factory=dict
    )  # mean, median, min, max, p95
    section_type_distribution: Dict[str, int] = field(default_factory=dict)
    chunks_with_section_type_empty: int = 0
    section_type_empty_rate: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChunkReport:
    """A per-experiment chunk diagnostic report."""

    schema_version: str
    experiment_name: str
    experiment_folder: str
    created_at: str
    source: str
    chunker: str
    config: Dict[str, Any]
    chunk_statistics: ChunkStatistics
    key_findings: List[str] = field(default_factory=list)
    recommendation: str = ""

    def to_dict(self) -> Dict[str, Any]:
        out = asdict(self)
        # ``chunk_statistics`` is itself a dataclass — ``asdict`` flattens
        # it one level. Keep that for JSON readability.
        return out


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------


def generate_chunk_report(
    experiment_name: str,
    chunks_root: str,
    *,
    chunker: str = "Unknown",
    config: Optional[Dict[str, Any]] = None,
    source: str = "",
    iso_now: Optional[str] = None,
) -> ChunkReport:
    """Walk a chunked corpus and produce a :class:`ChunkReport`.

    Args:
        experiment_name:
            The experiment identifier, e.g. ``"document_aware_chunking"``
            or ``"recursive_chunking_500_50_x_70"``. Mirrors the
            experiment folder name.
        chunks_root:
            Path to the root of the chunked corpus. Expected layout:
            ``<chunks_root>/<role>/<candidate_id>.jsonl``. The
            ``Document-Aware`` corpus lives at
            ``data/document_aware_chunking/``; a Recursive
            experiment lives at
            ``data/recursive_chunking_<params>/``.
        chunker:
            Name of the chunker that produced the corpus. Recorded in
            the report. Default ``"Unknown"``.
        config:
            Optional chunker config to record. For Recursive: ``{
            "chunk_size": 500, "chunk_overlap": 50, ... }``. For
            Document-Aware: ``{"max_chunk_chars": 1200,
            "split_overlap_chars": 120}``.
        source:
            Free-form description of where the corpus came from. E.g.
            ``"pre-DEC-019 production chunks"``.
        iso_now:
            ISO 8601 timestamp to record in ``created_at``. If not
            provided, the caller is expected to inject the value
            (e.g. via ``datetime.utcnow().isoformat() + "Z"``) so that
            test code can pin it.

    Returns:
        A populated :class:`ChunkReport`. The report is not written
        to disk by this function; use :func:`write_json_report` and
        :func:`write_markdown_report` to persist it.

    Raises:
        FileNotFoundError:
            If ``chunks_root`` does not exist.
    """
    chunks_root_path = Path(chunks_root)
    if not chunks_root_path.exists():
        raise FileNotFoundError(f"chunks root not found: {chunks_root}")

    stats = _compute_statistics(chunks_root_path)

    return ChunkReport(
        schema_version=SCHEMA_VERSION,
        experiment_name=experiment_name,
        experiment_folder=str(chunks_root_path),
        created_at=iso_now or _now_iso(),
        source=source,
        chunker=chunker,
        config=dict(config or {}),
        chunk_statistics=stats,
        key_findings=_derive_findings(stats, chunker=chunker),
        recommendation=_derive_recommendation(stats, chunker=chunker),
    )


def _now_iso() -> str:
    """Return the current UTC timestamp as an ISO 8601 string."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _compute_statistics(chunks_root: Path) -> ChunkStatistics:
    """Walk a chunked corpus and compute aggregate statistics."""
    stats = ChunkStatistics()
    chunks_per_resume_counts: List[int] = []

    if not chunks_root.is_dir():
        return stats

    role_dirs = sorted([p for p in chunks_root.iterdir() if p.is_dir()])
    for role_dir in role_dirs:
        role_name = role_dir.name
        per_role_count = 0
        for chunk_file in sorted(role_dir.glob("*.jsonl")):
            # ``_iter_jsonl`` skips malformed lines internally (logs a
            # warning per file); ``chunk_records`` is the list of
            # well-formed records. We do NOT skip the whole file on a
            # single bad line.
            chunk_records = list(_iter_jsonl(chunk_file))
            stats.total_chunks += len(chunk_records)
            per_role_count += len(chunk_records)
            chunks_per_resume_counts.append(len(chunk_records))
            for rec in chunk_records:
                st = rec.get("section_type", "")
                stats.section_type_distribution[st] = (
                    stats.section_type_distribution.get(st, 0) + 1
                )
                if not st:
                    stats.chunks_with_section_type_empty += 1
        if per_role_count:
            stats.chunks_per_role[role_name] = per_role_count

    stats.total_resumes = len(chunks_per_resume_counts)
    if chunks_per_resume_counts:
        sorted_counts = sorted(chunks_per_resume_counts)
        stats.chunks_per_resume = {
            "mean": round(statistics.fmean(chunks_per_resume_counts), 2),
            "median": float(statistics.median(chunks_per_resume_counts)),
            "min": int(min(chunks_per_resume_counts)),
            "max": int(max(chunks_per_resume_counts)),
            "p95": _percentile(sorted_counts, 0.95),
        }
    if stats.total_chunks:
        stats.section_type_empty_rate = round(
            stats.chunks_with_section_type_empty / stats.total_chunks, 4
        )

    return stats


def _percentile(sorted_values: List[int], p: float) -> int:
    """Return the p-th percentile of a pre-sorted list of ints (linear interp).."""
    if not sorted_values:
        return 0
    n = len(sorted_values)
    if n == 1:
        return int(sorted_values[0])
    pos = p * (n - 1)
    lo = int(pos)
    hi = min(lo + 1, n - 1)
    frac = pos - lo
    return int(round(sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * frac))


def _iter_jsonl(path: Path) -> Iterable[Dict[str, Any]]:
    """Yield one JSON object per non-empty, well-formed line of a JSONL file.

    Malformed lines are skipped with a warning (one warning per file).
    The iterator never raises on per-line errors so a single bad line
    does not invalidate the rest of the file.
    """
    warned = False
    with path.open("r", encoding="utf-8") as f:
        for line_no, raw in enumerate(f, start=1):
            line = raw.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except json.JSONDecodeError as exc:
                if not warned:
                    logger.warning(
                        "skipping malformed JSONL in %s (line %d): %s",
                        path, line_no, exc,
                    )
                    warned = True


def _derive_findings(stats: ChunkStatistics, *, chunker: str) -> List[str]:
    """Build a list of key findings from the chunk statistics."""
    findings: List[str] = []
    if stats.total_chunks == 0:
        return ["No chunks found in the corpus."]

    if stats.section_type_empty_rate >= 0.40:
        findings.append(
            f"{stats.section_type_empty_rate:.1%} of chunks have section_type='' and "
            f"are invisible to Section-Routed retrieval (DEC-015 finding). "
            f"This is the empirical justification for retiring the {chunker}."
        )
    elif stats.section_type_empty_rate >= 0.10:
        findings.append(
            f"{stats.section_type_empty_rate:.1%} of chunks have empty section_type — "
            f"a meaningful fraction but not as severe as the DEC-015 corpus."
        )

    if stats.chunks_per_resume:
        cpr = stats.chunks_per_resume
        findings.append(
            f"Chunks per resume: mean={cpr['mean']}, median={cpr['median']}, "
            f"min={cpr['min']}, max={cpr['max']}, p95={cpr['p95']}."
        )

    if stats.chunks_per_role:
        top_role = max(stats.chunks_per_role.items(), key=lambda x: x[1])
        findings.append(
            f"Largest role bucket: {top_role[0]} with {top_role[1]} chunks."
        )

    return findings


def _derive_recommendation(stats: ChunkStatistics, *, chunker: str) -> str:
    """Build a one-line recommendation string."""
    if stats.total_chunks == 0:
        return "Investigate why the corpus is empty."

    if stats.section_type_empty_rate >= 0.40:
        return (
            f"Retire {chunker} as the active strategy. "
            "The 40%+ missing-section_type rate makes Section-Routed retrieval "
            "unreliable (DEC-019, DEC-015)."
        )
    if stats.chunks_per_resume and stats.chunks_per_resume["max"] > 50:
        return (
            f"{chunker} produces up to {stats.chunks_per_resume['max']} chunks per resume. "
            "Consider raising chunk_size or adding per-resume cap."
        )
    return f"{chunker} corpus looks healthy; no immediate action needed."


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def write_json_report(report: ChunkReport, path: str) -> None:
    """Serialize ``report`` to JSON at ``path``. Creates parent dirs."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as f:
        json.dump(report.to_dict(), f, indent=2, ensure_ascii=False)
        f.write("\n")


def write_markdown_report(report: ChunkReport, path: str) -> None:
    """Serialize ``report`` to Markdown at ``path``. Creates parent dirs."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    lines: List[str] = []
    lines.append(f"# Chunk Report — {report.experiment_name}")
    lines.append("")
    lines.append(f"- **Schema version:** {report.schema_version}")
    lines.append(f"- **Created at:** {report.created_at}")
    lines.append(f"- **Source:** {report.source or '(unspecified)'}")
    lines.append(f"- **Chunker:** {report.chunker}")
    lines.append(f"- **Folder:** `{report.experiment_folder}`")
    if report.config:
        lines.append("")
        lines.append("## Config")
        lines.append("")
        for k, v in report.config.items():
            lines.append(f"- **{k}:** `{v}`")
    lines.append("")
    lines.append("## Chunk statistics")
    lines.append("")
    s = report.chunk_statistics
    lines.append(f"- **Total chunks:** {s.total_chunks}")
    lines.append(f"- **Total resumes:** {s.total_resumes}")
    if s.chunks_per_resume:
        cpr = s.chunks_per_resume
        lines.append(
            f"- **Chunks per resume:** mean={cpr['mean']}, "
            f"median={cpr['median']}, min={cpr['min']}, "
            f"max={cpr['max']}, p95={cpr['p95']}"
        )
    if s.chunks_per_role:
        lines.append("")
        lines.append("### Chunks per role")
        lines.append("")
        lines.append("| Role | Chunks |")
        lines.append("| --- | ---: |")
        for role, count in sorted(s.chunks_per_role.items(), key=lambda x: -x[1]):
            lines.append(f"| {role} | {count} |")
    lines.append("")
    lines.append(f"- **Chunks with `section_type=''`:** {s.chunks_with_section_type_empty}")
    lines.append(f"- **`section_type=''` rate:** {s.section_type_empty_rate:.1%}")
    if s.section_type_distribution:
        lines.append("")
        lines.append("### Section type distribution")
        lines.append("")
        lines.append("| Section type | Count |")
        lines.append("| --- | ---: |")
        for st, count in sorted(
            s.section_type_distribution.items(), key=lambda x: -x[1]
        ):
            label = st or "(empty)"
            lines.append(f"| {label} | {count} |")
    if report.key_findings:
        lines.append("")
        lines.append("## Key findings")
        lines.append("")
        for f in report.key_findings:
            lines.append(f"- {f}")
    if report.recommendation:
        lines.append("")
        lines.append("## Recommendation")
        lines.append("")
        lines.append(report.recommendation)
    lines.append("")
    with p.open("w", encoding="utf-8") as f:
        f.write("\n".join(lines))


__all__ = [
    "SCHEMA_VERSION",
    "ChunkStatistics",
    "ChunkReport",
    "generate_chunk_report",
    "write_json_report",
    "write_markdown_report",
]
