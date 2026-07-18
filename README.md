# HireIntel.AI — Candidate Intelligence Platform

An explainable candidate intelligence platform for recruiter-controlled screening, ranking, and interactive resume chatting. Powered by a sandboxed Hybrid RAG (Mode1 × Mode2) evaluation engine.

---

## 🧭 End-to-End System Walkthrough (Steps 1–10)

Here is a step-by-step guide through the platform's primary workflows, using the matching dashboard screenshots.

### Phase 1: Candidate Review & Interactive Resume Chat (Steps 1–4)

#### Step 1: My Project Ranking Dashboard
View the overall ranked list of candidates with detailed requirement compliance scores, categories, and zero-evidence warning flags for missing qualifications.
![Step 1: Candidate Rankings Dashboard](data/dashboard/1_Candidate_Ranking.png)

#### Step 2: Open Resume Chat (Loading State)
Click on a candidate to start an interactive chat session. The RAG system loads and prepares the candidate's parsed resume text chunks.
![Step 2: Resume Chat Loading](data/dashboard/2_Chat_with_pdf_loading.png)

#### Step 3: Interactive Resume Chatting
Ask natural language questions about the candidate's experience, skills, or projects. The assistant answers based strictly on resume evidence.
![Step 3: Resume Chatting](data/dashboard/3_Chatting_with_candidate_pdf.png)

#### Step 4: Evidence Highlighting & Verification
The chat displays direct references and source-attribute verification from the candidate's resume, highlighting matching text.
![Step 4: Evidence Verification](data/dashboard/4_Chatting_with_candidate_pdf.png)

---

### Phase 2: The Recruiter Onboarding Wizard (Steps 5–10)

Create custom roles, extract requirements, configure scoring weights, and score resumes on the fly inside a sandboxed session.

#### Step 5: Upload Job Description
Enter a role title and paste or upload the raw Job Description text to define the position.
![Step 5: Job Description Upload](data/dashboard/5_The_Job_Description_Uploaded.png)

#### Step 6: Requirement Extraction
AI models automatically extract core requirements, classifying them into Green (Factual), Yellow (Core skills), and Red (Preferred skills).
![Step 6: Requirement Extraction](data/dashboard/6_The_REQs_are_extracted.png)

#### Step 7: Edit Requirements
Refine requirement names, details, categories, and types before locking them down.
![Step 7: Edit Requirements](data/dashboard/7_The_REQs_being_edited.png)

#### Step 8: Weight Adjustment
Allocate importance percentages (totalling 100%) and specify target years of experience for each requirement using sliders.
![Step 8: Weight Adjustment](data/dashboard/8_The_Weight_Adjustment.png)

#### Step 9: Shared Resume Folder Link
Submit a shared Google Drive or Dropbox link containing candidate resumes. An active validation utility checks the URL for public access.
![Step 9: Shared Resume Folder Link](data/dashboard/9_Sharing_The_Resume_Folder_Link.png)

#### Step 10: View Scored Rankings
The background runner downloads the resumes, parses them, builds a vector index, scores the candidates using the Mode1 × Mode2 engine, and shows the ranked dashboard.
*(🔒 Note: Exactly 30 seconds after completion, all original resumes, processed JSONs, indexes, and manifests under `recruiter/data/` are automatically deleted to ensure privacy.)*
![Step 10: Recruiter Sandbox Rankings](data/dashboard/10_Candidate_Ranking_ReactDeveloper.png)

---

## 🌐 Live GCP Deployments

The platform is deployed and hosted on Google Cloud Run:
* **Live Recruiter Onboarding Board:** [https://recruiter-app-632852742603.us-central1.run.app/recruiter](https://recruiter-app-632852742603.us-central1.run.app/recruiter)
* **Live Main Projects Dashboard:** [https://recruiter-app-632852742603.us-central1.run.app/](https://recruiter-app-632852742603.us-central1.run.app/)

To re-deploy the backend container to Google Cloud Run:
```powershell
gcloud run deploy recruiter-app --source . --region us-central1 --quiet
```

---

## 🚀 Running the Local Server

To launch and test the local web application server using Python:

### 1. Run the FastAPI Servers Locally

* **Start the Recruiter Sandbox Server:**
  ```powershell
  .venv\Scripts\python -m uvicorn recruiter.src.api.app:app --host 127.0.0.1 --port 8000 --reload --reload-dir recruiter/src
  ```
  *(Note: The `--reload-dir recruiter/src` constraint is crucial to prevent WatchFiles from restarting the server mid-run when background processes write temporary evaluation files to `recruiter/data/`.)*

* **Or, Start the Main Project Server:**
  ```powershell
  .venv\Scripts\python -m uvicorn src.api.app:app --host 127.0.0.1 --port 8000 --reload
  ```

* **Verify / Test Locally:**
  * Open the **Recruiter Board UI:** [http://localhost:8000/recruiter](http://localhost:8000/recruiter)
  * Open the **Interactive Dashboard UI:** [http://localhost:8000/](http://localhost:8000/)
  * Test APIs via curl:
    ```bash
    curl http://localhost:8000/api/recruiter/health
    ```

---

### 2. Run the Docker Container Locally

To run the application inside a container matching the production Cloud Run environment:

* **Build the Docker Image:**
  ```bash
  docker build -t recruiter-app .
  ```

* **Run the Container (with local port mapping):**
  ```bash
  docker run -p 8000:7860 -e PORT=7860 recruiter-app
  ```

* **Test the Local Container:**
  * Access the Web UI at: [http://localhost:8000/recruiter](http://localhost:8000/recruiter)
  * Send a health check request:
    ```bash
    curl http://localhost:8000/api/recruiter/health
    ```

---

## 📊 RAG Parameter Sensitivity & Rank Stability Findings from the Recursive Chunker experiment (deprecated)

A structured grid search sweep (45 configurations × 8 roles = 360 runs) was executed against all candidate pools to analyze rank sensitivity across variations in similarity threshold (`theta`), chunk size, and top-k retrieval cap.

All stability metrics below are computed relative to the locked baseline configuration:
* `chunk_size = 1000`, `chunk_overlap = 500`, `top_k = 20`, `theta = 0.35`

### 1. Cross-Role Stability Summary (`grid_sweep_20260712`)

| Role | Jaccard @10 | Max Shift | Mean Abs Shift | Kendall Tau | Spearman Rho | Primary Sensitivity | Verdict |
| :--- | ---: | ---: | ---: | ---: | ---: | :--- | :---: |
| **ReactDeveloper** | 0.6723 | 13.0 | 2.8106 | 0.5829 | 0.6955 | `theta` (R²=0.246) | 🟢 PASS |
| **JavaDeveloper** | 0.5472 | 38.0 | 6.3068 | 0.7634 | 0.9045 | `theta` (R²=0.336) | 🟡 REVIEW |
| **WebDesigning** | 0.4856 | 101.0 | 12.1826 | 0.6893 | 0.8308 | `theta` (R²=0.198) | 🟡 REVIEW |
| **DataScience** | 0.4476 | 34.0 | 6.4935 | 0.5686 | 0.6990 | `theta` (R²=0.194) | 🟡 REVIEW |
| **SQLDeveloper** | 0.4399 | 67.0 | 10.0394 | 0.6660 | 0.7997 | `theta` (R²=0.135) | 🟡 REVIEW |
| **SrPythonDeveloper** | 0.4252 | 89.0 | 9.4467 | 0.7322 | 0.8760 | `theta` (R²=0.282) | 🟡 REVIEW |
| **BusinessAnalyst** | 0.4103 | 112.0 | 16.7040 | 0.6467 | 0.7902 | `theta` (R²=0.177) | 🟡 REVIEW |
| **SalesManager** | 0.3839 | 118.0 | 16.3478 | 0.7198 | 0.8590 | `theta` (R²=0.119) | 🟡 REVIEW |
| **Global Average / Max** | **0.4765** | **118.0** | **10.0414** | **0.6711** | **0.8068** | — | — |

---

## ⚙️ Technical Architecture Overview

HireIntel.AI implements a multi-layer design to ensure extreme performance and safety:
* **Relational Store (SQLite):** Sandboxed database tracking recruiters, saved roles, requirements, and weight configuration records.
* **Vector Store & Indexing (BGE-768):** Document-aware segment retrieval mapped by section type (experience, skills, education) to align sub-queries with candidate qualifications. *Note: BGE-768 is used only locally. For GCP deployment, we use `gemini-embedding-001` as BGE took a very long time to load, embed, and index.*
* **Composed Scorer:** Computes factual compliance (e.g. CGPA, institution tiers, degree tiers, years of experience) combined with LLM-evaluated criteria (skill depth and context).
* **Thread-Safe Parallel Scorer (Multicall Parallelization):** Evaluates all requirements (e.g. 10 REQs) for a candidate concurrently using a `ThreadPoolExecutor`. Fast factual checks run locally, while slower LLM rubric evaluations are dispatched in parallel to OpenRouter, reducing scoring time per candidate from minutes to a few seconds.
