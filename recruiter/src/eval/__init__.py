"""Evaluation utilities: ranking comparison, per-candidate diff, and (later)
aggregate metrics like NDCG@k and MAP@k.

The first tool shipped here is the ranking diff (DEC-026): given two
rankings of the same role, surface the candidates that moved, by how
much, and why (via versioned reasoning + chunks from each experiment's
per-resume tree).

Other prongs of the multi-pronged ranking-evaluation methodology
(DEC-024) — counterfactual tests, synthetic labeled set, recruiter
agreement, behavioral signals — are added incrementally in
``IMPLEMENTATION_ROADMAP.md`` M0.5f.
"""
