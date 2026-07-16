# Script to copy updated files from local development workspace to GCP/HuggingFace deployment directory.

$src = "c:\Users\sandi\Desktop\ML Working Folder\hireintel_ai"
$dest = "C:\Users\sandi\Desktop\HF_Deployments\recruiter"

Write-Host "Copying modified scorer files..."
Copy-Item -Force "$src\recruiter\src\scoring\unified_scorer.py" "$dest\recruiter\src\scoring\unified_scorer.py"
Copy-Item -Force "$src\recruiter\score_batch_composed.py" "$dest\score_batch_composed.py"

Write-Host "Copying modified api files..."
Copy-Item -Force "$src\recruiter\src\api\recruiter.py" "$dest\recruiter\src\api\recruiter.py"

Write-Host "Copying exporter service..."
Copy-Item -Force "$src\recruiter\src\services\gdrive_exporter.py" "$dest\recruiter\src\services\gdrive_exporter.py"

Write-Host "Copying env.example..."
Copy-Item -Force "$src\.env.example" "$dest\.env.example"

Write-Host "Copying GCP kill switch files..."
$kill_dest = "$dest\gcp_kill_switch"
New-Item -ItemType Directory -Force -Path $kill_dest
Copy-Item -Force "$src\scripts\gcp_kill_switch\main.py" "$kill_dest\main.py"
Copy-Item -Force "$src\scripts\gcp_kill_switch\requirements.txt" "$kill_dest\requirements.txt"

Write-Host "Done!"
