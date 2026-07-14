import gdown
from pathlib import Path

dest = Path("scratch/test_gdown_dest")
dest.mkdir(parents=True, exist_ok=True)

url = "https://drive.google.com/drive/folders/1M7lX-_nbVnpjl-c7zyY0j6FLcswFRksY?usp=sharing"

try:
    print("Starting download via gdown...")
    files = gdown.download_folder(url=url, output=str(dest), quiet=False)
    print("Files downloaded:", files)
except Exception as e:
    print("Error:", e)
