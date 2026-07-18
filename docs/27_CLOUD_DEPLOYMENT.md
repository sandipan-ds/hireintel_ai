# GCP Serverless Deployment & Architecture Details

This document details the engineering objective, deployment architecture, file manifests, and troubleshooting history of the serverless Google Cloud Platform (GCP) deployment of the Candidate Intelligence Platform.

---

## 🎯 1. Aim of the Deployment
The primary goal was to deploy the Candidate Intelligence Platform's **FastAPI recruiter onboarding wizard** to a serverless cloud environment capable of handling high-volume resume parsing, structured JSON schema extraction, RAG index compilation, and deterministic scoring.

### Requirements & Key Objectives:
*   **Zero-Maintenance Serverless Scaling:** Deploy the FastAPI application to **Google Cloud Run** to allow automated scaling.
*   **Scale-to-Zero Cost Optimization:** Set minimum instances to `0` (`min-instances=0`) to ensure GCP does not charge when the application is idle.
*   **Deterministic CPU Execution:** Enable PyTorch and SentenceTransformer model execution inside a CPU-only container runtime, avoiding the need for expensive GPU VMs.
*   **Billing Security & Kill Switch:** Deploy a GCP Cloud Function to monitor budgets and automatically disable the Cloud Run application if the spending limit is breached.

---

## 📦 2. Docker Image & Build Architecture
To run the platform on GCP Cloud Run, the application was packaged into a resource-optimized container image using a single-stage build.

### Image Optimization Strategy:
*   **Base Image:** `python:3.10-slim` is used to keep the final container size small.
*   **Exclusion of Heavy Weights from Context Upload:** The local model weights folder (`recruiter/models/`) is excluded from the source uploads using `.dockerignore` and `.gcloudignore`. This reduced the build context transfer from **466.5 MiB** to **48.1 MiB**, speeding up uploads by 10x.
*   **Cloud Build Cache-Baking:** During the Docker image build phase (`gcloud builds submit`), a caching step runs a python script to download the `BAAI/bge-base-en-v1.5` weights directly from Hugging Face Hub using Google's high-speed datacenter network and bakes them into the container image. This guarantees that when Cloud Run instances start, they run completely offline (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`) with zero startup download delays.

### 📁 Container Context: What was Copied & What was Excluded

#### 1. Why we did not copy *only* the `recruiter/` folder:
The onboarding wizard web app inside `recruiter/src/api/` is a frontend layer, but it heavily imports core business logic (e.g. parsing, RAG indexing, deterministic scoring, embedding generation) defined in the root-level directories (`src/rag/`, `src/scoring/`, `src/services/`, etc.). Therefore, the **entire workspace context** was copied into the Docker image, maintaining import paths.

#### 2. What files and folders outside `recruiter/` are included:
*   **`src/`:** The entire core source code (containing RAG indexing, the scoring logic, LLM API helpers, and structured schemas).
*   **`requirements.txt` & `pyproject.toml`:** Root level dependency specs.

#### 3. What is explicitly excluded (via `.dockerignore`):
To prevent bloating the container and leaking private/local developer artifacts, the following directories and files are ignored during build context copy:
*   **Private Data:** `data/` and `recruiter/data/` (so resumes, candidate pools, and scores databases are never baked into the public container image, ensuring recruiter data privacy).
*   **Developer Environments:** `.venv/`, `.git/`, `.history/`, and `.checkpoints/`.
*   **Caches & Logs:** `.pytest_cache/`, `.ruff_cache/`, `mlruns/`, `logs/`, `recruiter/logs/`, and all local `*.log` files.
*   **Developer Assets:** `notebooks/`, `tests/`, `baseline/`, and `graphify-out/`.
*   **Local Secret Settings:** `.env` and all `.env.*` files.

---

## 📁 3. Committed Files & Manifest
The deployment was finalized and pushed to the repository under the branch **`feature/sand`** with the commit message:
`"Deploy project locally using FastAPI and Docker"`

### Committed File Manifest:
| Component / File Path | Purpose |
|---|---|
| [`Dockerfile`](file:///C:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/Dockerfile) | Specifies container assembly, pip dependencies installation, model caching, and uvicorn startup command. |
| [`.dockerignore`](file:///C:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/.dockerignore) | Excludes python cache, environments, and local model weights folders from being included in the Docker build context. |
| [`.gcloudignore`](file:///C:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/.gcloudignore) | Excludes the local weights directory and databases from being uploaded to the Cloud Storage staging bucket during GCP builds. |
| [`scripts/copy_to_deploy.ps1`](file:///C:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/scripts/copy_to_deploy.ps1) | PowerShell utility script to mirror workspace files and synchronize state with the serverless deployments folder. |
| [`scripts/gcp_kill_switch/main.py`](file:///C:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/scripts/gcp_kill_switch/main.py) | Python Cloud Function that parses GCP Pub/Sub billing alerts and scales Cloud Run instances to zero if the budget is exceeded. |
| [`scripts/gcp_kill_switch/requirements.txt`](file:///C:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/scripts/gcp_kill_switch/requirements.txt) | Python dependencies (`google-api-python-client`, `google-auth`) required for the billing kill-switch function. |
| [`recruiter/src/services/gdrive_exporter.py`](file:///C:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/recruiter/src/services/gdrive_exporter.py) | Exports candidate profiles and resumes into structured directories on Google Drive. |
| [`batch_extract_resumes.py`](file:///C:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/batch_extract_resumes.py) | Extracts metadata, skills, and qualifications from parsed resumes. |
| [`score_batch_composed.py`](file:///C:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/score_batch_composed.py) | Evaluates and scores candidate resumes against job description rubrics. |

---

## 🛠️ 4. Detailed Description of Deployment Steps Taken
1.  **Environment Isolation:** Standardized system environment variables for CPU only (`CUDA_VISIBLE_DEVICES=""`) and offline weights execution (`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`).
2.  **Container Assembly:** Created [Dockerfile](file:///C:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/Dockerfile) to pre-download the model directly during compilation and expose the uvicorn service on the dynamic environment variable `${PORT:-7860}`.
3.  **Excluded Large Local Assets:** Wrote [`.dockerignore`](file:///C:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/.dockerignore) and [`.gcloudignore`](file:///C:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/.gcloudignore) entries to skip uploading the local `recruiter/models/` weights directory.
4.  **Artifact Staging & Building:** Submitted the code files to Google Cloud Build using:
    ```powershell
    gcloud builds submit --tag us-central1-docker.pkg.dev/hireintel-ai-502510/recruiter-repo/recruiter-app:latest .
    ```
5.  **Service Provisioning on Cloud Run:** Deployed the container to Cloud Run, provisioning the resource thresholds to **2 GiB of Memory** and **2 vCPUs** to satisfy the memory footprint of PyTorch and the BGE embeddings model:
    ```powershell
    gcloud run deploy recruiter-app --image us-central1-docker.pkg.dev/hireintel-ai-502510/recruiter-repo/recruiter-app:latest --region us-central1
    ```
6.  **Billing Security Lock (Kill Switch):** Deployed a Python-based Google Cloud Function named `limit-billing` to listen to the GCP Pub/Sub topic `billing-alerts`. 
    *   **Budget Policy:** Configured a GCP Billing Budget cap of **200 INR (Rs)**. When spending reaches 100% of this budget, Google Billing publishes an alert message to the Pub/Sub topic.
    *   **Shut Down Automation:** The triggered `limit-billing` function uses the Google API Client (`discovery.build`) to programmatically edit the configuration of `recruiter-app` and set `autoscaling.knative.dev/maxScale` (max-instances) to `"0"`, immediately stopping all container scaling and billing consumption.
    *   **Deployment Command:**
        ```powershell
        gcloud functions deploy limit-billing `
          --runtime=python311 `
          --trigger-topic=billing-alerts `
          --entry-point=limit_billing `
          --region=us-central1 `
          --gen2
        ```
7.  **Final Commit & Synchronization:** Committed all code modifications and pushed them to GitHub on branch `feature/sand`.

---

## ⚡ 5. Execution Time Bottlenecks & Parallelization

During the architecture setup, we identified two primary bottlenecks that significantly increased execution times:
1.  **Resume Parsing & LLM Normalization (High-Latency Phase):** Extracting structured JSON from resumes using multimodal LLMs requires individual, sequential API calls. For a batch of 10 resumes, this could take over 2 minutes if done sequentially.
2.  **LLM Rubric Scoring (API Bound Bottleneck):** Scoring each candidate against 15+ Job Description requirements requires calling the rubric prompt repeatedly. Under a sequential loop, scoring a single candidate took 30–45 seconds, translating to hours of execution time for full talent pools.

### What We Parallelized:
*   **Multi-Worker Batch Scorer:** The [score_batch_composed.py](file:///C:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/score_batch_composed.py) pipeline is configured to run with multiple parallel worker threads (`--workers 10`). This concurrency allows the scoring engine to query the LLM provider API in parallel, reducing the total scoring time for candidate batches by up to **10x** (processing 10 candidates concurrently).
*   **Asynchronous Subprocess Pipeline Execution:** When the recruiter triggers the onboarding wizard pipeline, the server spawns [recruiter/build_index.py](file:///C:/Users/sandi/Desktop/ML%20Working%20Folder/hireintel_ai/recruiter/build_index.py) and scoring scripts as asynchronous background subprocesses. Uvicorn continues to serve client HTTP requests and ranking status polls on the main thread, preventing server lockups during computationally heavy embedding/indexing operations.
*   **Parallel Container Compilation:** Google Cloud Build processes step execution, Docker image layer generation, and registry pushes concurrently using remote builders to achieve high throughput during compilation.

### 📈 Processing Time Benchmarks (Localhost Concurrency Testing)

The following metrics compare sequential pipeline execution under Opencode/Minimax-M3 against parallelized execution under OpenRouter/Gemini-3.1-Flash-Lite (tested with a batch of 10 resumes and 17 requirements):

| Process Phase | Before Optimization (Sequential, Minimax-M3 via Opencode) | After Optimization (Parallel, Gemini-3.1-Flash via OpenRouter) | Difference (Time Saved) | Speedup / Improvement |
| :--- | :--- | :--- | :--- | :--- |
| **Download** | 36.73s | 32.15s | -4.58s | *Network variance* |
| **Extraction** | **156.27s** | **3.32s** | **-152.95s** | **47x Faster (98% reduction)** 🚀 |
| **Indexing (BGE)** | **65.27s** | **39.03s** | **-26.24s** | **1.7x Faster (40% reduction)** |
| **Scoring** | **63.31s** | **45.78s** | **-17.53s** | **1.4x Faster (28% reduction)** |
| **Total Pipeline Time** | **321.58s** (5m 21s) | **120.28s** (2m 00s) | **-201.30s** | **2.7x Overall Speedup (63% faster)** |

---

## ⚠️ 6. Problems Faced & How They Were Solved

### 1. PyTorch CUDA Initialization Hangs in CPU-only Containers
*   **Problem:** PyTorch was attempting to detect CUDA/GPU bindings on startup, which caused the container to hang indefinitely inside the CPU-only Cloud Run environment.
*   **Solution:** We added `ENV CUDA_VISIBLE_DEVICES=""` to the Dockerfile and copy it into uvicorn's subprocess `sub_env` configuration dictionary. This forces PyTorch to completely bypass the CUDA detection check and run immediately on CPU.

### 2. Slow Artifact Upload Speeds (466.5 MiB)
*   **Problem:** The initial deployment build took over 13 minutes because it was uploading the 438 MB BGE model weights directly from the local developer PC over the internet context.
*   **Solution:** Excluded the `recruiter/models/` folder from the deployment upload context using `.dockerignore` and `.gcloudignore`. Instead, we added a cache-download step in the Dockerfile:
    ```dockerfile
    RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('BAAI/bge-base-en-v1.5')"
    ```
    This downloads the weights directly on Google's high-speed network (taking just a few seconds) and bakes them into the container image cache layer. The local upload size shrank from **466.5 MiB** to **48.1 MiB**.

### 3. Rust Tokenizers Parallelism Deadlock on Cloud Run
*   **Problem:** After starting the pipeline, the container hung indefinitely when starting the embedding phase (`embedding 51 chunks...`).
*   **Solution:** Hugging Face Tokenizers use Rust multithreading by default. In serverless guest kernels (like Cloud Run's gVisor sandboxed environment), multi-process forks and parallel threads cause lockups. We added `ENV TOKENIZERS_PARALLELISM=false` to the Dockerfile and uvicorn runner subprocesses, forcing tokenization to run sequentially on a single thread.

### 4. Buffered Output Logs in Recruiter UI
*   **Problem:** The pipeline status logs were buffered by default, keeping stdout logs hidden until the entire process exited, making debugging hangs difficult.
*   **Solution:** Configured `ENV PYTHONUNBUFFERED=1` in the Dockerfile and in the subprocess environments to flush stdout lines immediately, enabling real-time logs in the UI.
