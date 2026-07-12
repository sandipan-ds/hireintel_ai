# Task Checklist - Gap-Fill Re-Extraction

- [ ] Create `scripts/gap_fill_extraction.py`
  - [ ] Implement `.env.audit` key and provider configuration loader
  - [ ] Implement PDF page to base64 image converter using `pdf2image` (with fallback if missing/fails)
  - [ ] Implement OpenAI-compatible multimodal LLM caller
  - [ ] Implement gap-fill schema prompts and candidate profile merger logic
  - [ ] Implement command line argument parser and progress ledger
- [ ] Add `RESUME-GAPFILL-001` to `docs/15_PROMPT_LIBRARY.md`
- [ ] Smoke test with `--dry-run` to verify setup
- [ ] Run gap-filler script on the 12 flagged candidates
- [ ] Rebuild RAG index
- [ ] Re-run scoring script to update candidate scores
- [ ] Regenerate run report to verify the gaps are filled and candidates scored
- [ ] Update `docs/03_CURRENT_PROGRESS.md` and write `walkthrough.md`
