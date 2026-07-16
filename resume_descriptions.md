# Resume Formatting Options for HireIntel.AI

Below are curated resume blocks tailored for different resume formats (Detailed Project/Portfolio Section vs. Bullet Points under Professional Experience). These descriptions incorporate the exact architectural definitions (separating vector retrieval from rubric-bound LLM grading, JSON audits, and thread-safe concurrency).

---

## Option 1: Detailed Project Entry (Recommended for Portfolio/Projects Section)

### **HireIntel.AI — Lead AI Architect & Developer** | *Python, FastAPI, HTMX, SQLite, BAAI/bge-base-en-v1.5, Threading, Docker*
Developed an enterprise-grade Candidate Intelligence Platform featuring explainable, multi-role screening, ranking, and interactive resume chatting powered by a custom Hybrid RAG pipeline.

* **Two-Stage Hybrid RAG Engine:** Architected a search-evaluation split pipeline that uses BGE-v1.5 embeddings for document-aware evidence retrieval and routes evidence chunks to a rubric-bound LLM Judge for multi-band grading, keeping final scoring math deterministic and transparent.
* **Five-Layer JSON Quality Audit & Vision Gap-Filling:** Designed a schema completeness audit (schema, data types, evidence tracing, Levenshtein consistency) paired with a multimodal vision recovery pipeline that renders PDF pages to images to salvage missing fields from scanned documents.
* **High-Throughput Parallel Evaluator:** Built an asynchronous scoring scheduler (`ThreadPoolExecutor`) enabling concurrent requirement evaluation across 700+ candidate resumes, achieving high scoring throughput under strict LLM API rate limits.
* **Secure BYOK & Sandbox Architecture:** Engineered a stateless 6-step recruiter onboarding board and a dashboard that decouples analytics from cloud credentials, persisting OpenRouter/Gemini API inputs strictly in browser localStorage to prevent server-side key leaks.

---

## Option 2: Concise Bullet Points (For Chronological Experience Section)

* Engineered **HireIntel.AI**, an explainable candidate screening platform separating BGE-v1.5 vector retrieval (evidence collection) from a rubric-bound LLM Judge and a deterministic Python scoring engine.
* Built a **five-layer JSON Quality Audit** and a **multimodal vision gap-fill pipeline** that renders resume PDFs to base64 images to re-extract missing credentials from scanned or OCR-failed profiles.
* Implemented a **concurrent scoring engine** using a Python `ThreadPoolExecutor` to parallelize requirement scoring across candidates, reducing scoring latency.
* Designed a **privacy-first BYOK (Bring Your Own Key) dashboard** using local-storage synchronization to enforce credential containment, allowing secure external runs with zero cloud-key exposure.
