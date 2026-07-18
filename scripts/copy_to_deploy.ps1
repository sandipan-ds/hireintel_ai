# Script to copy updated files from local development workspace to GCP/HuggingFace deployment directory.

$src = "c:\Users\sandi\Desktop\ML Working Folder\hireintel_ai"
$dest = "C:\Users\sandi\Desktop\HF_Deployments\hireintel_ai"

Write-Host "Copying modified scorer files..."
Copy-Item -Force "$src\recruiter\src\scoring\unified_scorer.py" "$dest\recruiter\src\scoring\unified_scorer.py"
Copy-Item -Force "$src\recruiter\score_batch_composed.py" "$dest\recruiter\score_batch_composed.py"
Copy-Item -Force "$src\src\scoring\unified_scorer.py" "$dest\src\scoring\unified_scorer.py"
Copy-Item -Force "$src\score_batch_composed.py" "$dest\score_batch_composed.py"

Write-Host "Copying modified api files..."
Copy-Item -Force "$src\recruiter\src\api\recruiter.py" "$dest\recruiter\src\api\recruiter.py"
Copy-Item -Force "$src\recruiter\src\api\dashboard.py" "$dest\recruiter\src\api\dashboard.py"
Copy-Item -Force "$src\src\api\recruiter.py" "$dest\src\api\recruiter.py"
Copy-Item -Force "$src\src\api\dashboard.py" "$dest\src\api\dashboard.py"

Write-Host "Copying build index logic..."
Copy-Item -Force "$src\recruiter\build_index.py" "$dest\recruiter\build_index.py"
Copy-Item -Force "$src\recruiter\src\rag\build_index.py" "$dest\recruiter\src\rag\build_index.py"

Write-Host "Copying LLM services..."
Copy-Item -Force "$src\recruiter\src\services\llm_caller.py" "$dest\recruiter\src\services\llm_caller.py"
Copy-Item -Force "$src\src\services\llm_caller.py" "$dest\src\services\llm_caller.py"

Write-Host "Copying templates..."
Copy-Item -Force "$src\recruiter\src\templates\recruiter.html" "$dest\recruiter\src\templates\recruiter.html"
Copy-Item -Force "$src\recruiter\src\templates\dashboard.html" "$dest\recruiter\src\templates\dashboard.html"

Write-Host "Copying Docker and ignore configs..."
Copy-Item -Force "$src\Dockerfile" "$dest\Dockerfile"
Copy-Item -Force "$src\.dockerignore" "$dest\.dockerignore"
Copy-Item -Force "$src\.gcloudignore" "$dest\.gcloudignore"

Write-Host "Copying exporter service..."
Copy-Item -Force "$src\recruiter\src\services\gdrive_exporter.py" "$dest\recruiter\src\services\gdrive_exporter.py"

Write-Host "Copying env.example..."
Copy-Item -Force "$src\.env.example" "$dest\.env.example"

Write-Host "Copying GCP kill switch files..."
$kill_dest = "$dest\gcp_kill_switch"
if (!(Test-Path -Path $kill_dest)) {
    New-Item -ItemType Directory -Force -Path $kill_dest
}
Copy-Item -Force "$src\scripts\gcp_kill_switch\main.py" "$kill_dest\main.py"
Copy-Item -Force "$src\scripts\gcp_kill_switch\requirements.txt" "$kill_dest\requirements.txt"

Write-Host "Done!"
