# Resume Formatting Options for HireIntel.AI

Below are curated resume blocks tailored for different resume formats (Detailed Project/Portfolio Section vs. Bullet Points under Professional Experience).

---

## Option 1: Detailed Project Entry (Recommended for Portfolio/Projects Section)

### **HireIntel.AI — Lead Architect / Developer** | *Python, FastAPI, RAG, Vector Databases, Async/Parallel Computing*
Developed an enterprise-grade Candidate Intelligence Platform featuring explainable, multi-role screening, ranking, and interactive resume chatting powered by a custom Hybrid RAG pipeline.

* **Hybrid RAG Retrieval Engine:** Designed and implemented a two-stage evaluation engine separating factual lookup queries (e.g., degrees, institutions, specific experience) from semantic capability checks (e.g., context-aware technical expertise, leadership scope) using BGE embeddings and similarity thresholds.
* **High-Throughput Parallel Evaluator:** Built an async scoring scheduler (`ThreadPoolExecutor`) enabling concurrent requirement evaluation across multiple candidate resumes, achieving high throughput (20+ concurrent workers) under strict LLM API rate limits.
* **Privacy-First Sandbox Architecture:** Engineered a secure, air-gapped recruiter sandbox environment supporting live job description parsing, requirements extraction, Google Drive/Dropbox validation, and automated 30-second background cleanup loops to safeguard candidate data.
* **Interactive Resume Chat Bot:** Constructed an interactive resume-chat interface utilizing local-storage synchronized API slots (BYOK drawer/sidebar config) enabling demo viewers and recruiters to query resumes directly with full evidence-traceability.

---

## Option 2: Concise Bullet Points (For Chronological Experience Section)

* Designed and built **HireIntel.AI**, an explainable candidate screening platform utilizing a two-stage **Hybrid RAG** engine to score resumes against multi-role job descriptions.
* Engineered a **multicall parallel scoring scheduler** in Python, utilizing asynchronous execution and concurrency controls to scale to 20+ parallel LLM workers for real-time candidate ranking.
* Implemented a **privacy-first data lifecycle** featuring automated document parsing, external drive folder link validators, and a background thread-based **silent data auto-cleanup (30-second deletion)** loop.
* Developed a responsive web interface utilizing modern CSS glassmorphism, dynamic scoring gauges, and a client-side **BYOK (Bring Your Own Key)** settings drawer to completely decouple local server API expenses from external testers.

---

## 💡 Key Technical Buzzwords to Highlight
* **Systems & Architecture:** Hybrid Retrieval-Augmented Generation (RAG), Thread-Safe Concurrency, Async Event-Driven Automation, API Key Decoupling (BYOK), SQLite/PostgreSQL Database schemas.
* **AI & Search:** BGE Vector Embeddings, Cosine Similarity Thresholding, Multimodal Parsing, Natural Language Requirements Extraction.
* **Backend:** FastAPI, Python, Uvicorn, Subprocess Pipelines, File System Air-gapping.
