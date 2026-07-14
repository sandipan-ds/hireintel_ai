import re
import urllib.request
import urllib.parse
from pathlib import Path

def get_folder_id(url):
    # Match drive.google.com/drive/folders/ID or drive.google.com/drive/u/0/folders/ID
    match = re.search(r'/folders/([a-zA-Z0-9-_]+)', url)
    if match:
        return match.group(1)
    return None

def download_public_gdrive_folder(url, dest_dir):
    folder_id = get_folder_id(url)
    if not folder_id:
        print("Invalid Google Drive folder URL")
        return False
    
    dest_path = Path(dest_dir)
    dest_path.mkdir(parents=True, exist_ok=True)
    
    # Google Drive folder page
    folder_url = f"https://drive.google.com/drive/folders/{folder_id}"
    req = urllib.request.Request(
        folder_url,
        headers={'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}
    )
    
    try:
        with urllib.request.urlopen(req) as response:
            html = response.read().decode('utf-8')
    except Exception as e:
        print(f"Error fetching folder page: {e}")
        return False
        
    # Search for file IDs and names in the HTML
    # Google Drive embedding JSON contains: [id, name, mimeType, ...]
    # Let's find patterns like: ["id", "name.extension"]
    # Usually: [[..., "id", "name", "mimeType", ...]]
    # Let's search for "[\"[a-zA-Z0-9-_]{25,}\",\"[^\"]+\\.[a-zA-Z0-9]{3,4}\""
    matches = re.findall(r'\["([a-zA-Z0-9-_]{28,})","([^"]+\.[a-zA-Z0-9]{3,4})"', html)
    if not matches:
        # Fallback: look for file/d/ links
        file_ids = re.findall(r'/file/d/([a-zA-Z0-9-_]+)', html)
        # remove duplicates
        file_ids = list(set(file_ids))
        matches = [(fid, f"resume_{idx+1}.pdf") for idx, fid in enumerate(file_ids)]
        
    print(f"Found {len(matches)} files in the folder")
    downloaded = 0
    for file_id, file_name in set(matches):
        # Only download PDF, DOCX, DOC files
        ext = Path(file_name).suffix.lower()
        if ext not in ['.pdf', '.docx', '.doc']:
            continue
            
        print(f"Downloading {file_name} (ID: {file_id})")
        download_url = f"https://drive.google.com/uc?export=download&id={file_id}"
        file_dest = dest_path / file_name
        
        try:
            # Handle Google Drive large file virus scan warning confirmation page
            urllib.request.urlretrieve(download_url, str(file_dest))
            # Check if we got a small HTML page instead of the actual file (warning page)
            if file_dest.stat().st_size < 10000:
                with open(file_dest, 'r', errors='ignore') as f:
                    content = f.read(500)
                    if 'confirm=' in content:
                        confirm_match = re.search(r'confirm=([a-zA-Z0-9-_]+)', content)
                        if confirm_match:
                            confirm_token = confirm_match.group(1)
                            confirm_url = f"{download_url}&confirm={confirm_token}"
                            urllib.request.urlretrieve(confirm_url, str(file_dest))
            
            print(f"Successfully downloaded {file_name}")
            downloaded += 1
        except Exception as e:
            print(f"Failed to download {file_name}: {e}")
            
    return downloaded > 0

if __name__ == "__main__":
    url = "https://drive.google.com/drive/folders/12X15tVvYtI4CigQ2C0nSjVz8G47YJ0N9" # Dummy/test URL
    download_public_gdrive_folder(url, "scratch/test_downloads")
