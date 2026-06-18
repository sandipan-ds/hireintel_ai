import os
from PIL import Image
from pathlib import Path
import pytesseract
from pytesseract import Output
from reportlab.lib.pagesizes import letter, A4
from reportlab.pdfgen import canvas
from reportlab.lib.utils import ImageReader
from reportlab.platypus import SimpleDocTemplate, Image as PlImage, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from io import BytesIO
import io

def extract_text_from_image(image_path):
    """
    Extract text from image using OCR.
    
    Args:
        image_path (str): Path to the image file
        
    Returns:
        dict: Contains extracted text and status
    """
    try:
        # Extract full text with layout
        full_text = pytesseract.image_to_string(Image.open(image_path))
        
        return {
            'full_text': full_text,
            'success': True
        }
    except Exception as e:
        return {
            'full_text': '',
            'success': False,
            'error': str(e)
        }

def create_searchable_pdf(image_path, output_pdf_path, ocr_text):
    """
    Create a searchable PDF with the original resume image and OCR-extracted text.
    
    Args:
        image_path (str): Path to the image file
        output_pdf_path (str): Path where PDF will be saved
        ocr_text (str): Extracted OCR text
    """
    try:
        # Open image to get dimensions
        pil_image = Image.open(image_path)
        img_width, img_height = pil_image.size
        
        # Convert image to RGB if necessary (for PDF compatibility)
        if pil_image.mode in ('RGBA', 'LA', 'P'):
            rgb_image = Image.new('RGB', pil_image.size, (255, 255, 255))
            rgb_image.paste(pil_image, mask=pil_image.split()[-1] if pil_image.mode == 'RGBA' else None)
            pil_image = rgb_image
        
        # Calculate PDF page size to fit image
        aspect_ratio = img_width / img_height
        pdf_height = A4[1]  # Use A4 height
        pdf_width = pdf_height * aspect_ratio
        
        # Create canvas for PDF
        c = canvas.Canvas(output_pdf_path, pagesize=(pdf_width, pdf_height))
        
        # Draw the original image
        img_reader = ImageReader(image_path)
        c.drawImage(img_reader, 0, 0, width=pdf_width, height=pdf_height)
        
        # Embed OCR text as invisible text layer for searchability
        # This makes the PDF searchable and extractable for RAG/chunking
        if ocr_text.strip():
            # Set very small, transparent font
            c.setFont("Helvetica", 1)
            c.setFillAlpha(0.0)  # Completely transparent
            
            # Add text layer
            text_y = pdf_height - 20
            for line in ocr_text.split('\n'):
                if line.strip():
                    # Split long lines to fit page width
                    for sub_line in [line[i:i+100] for i in range(0, len(line), 100)]:
                        if text_y > 0:
                            c.drawString(10, text_y, sub_line)
                            text_y -= 10
        
        c.save()
        return True
        
    except Exception as e:
        raise Exception(f"Error creating searchable PDF: {str(e)}")

def convert_images_to_pdf(source_dir="data/original", output_dir="data/processed"):
    """
    Convert all image files (JPG, JPEG, PNG) to searchable PDF format using OCR.
    Creates PDFs with the original resume image and embedded OCR text.
    Perfect for RAG/chunking - shows real resumes while being extractable/searchable.
    
    Args:
        source_dir (str): Path to the source directory containing original images
        output_dir (str): Path to the output directory where PDFs will be saved
    """
    
    # Image extensions to process
    image_extensions = {'.jpg', '.jpeg', '.png'}
    
    # Statistics
    stats = {
        'total': 0,
        'success': 0,
        'failed': 0,
        'errors': []
    }
    
    # Walk through all directories in source_dir
    for root, dirs, files in os.walk(source_dir):
        for file in files:
            file_lower = file.lower()
            
            # Check if file is an image
            if any(file_lower.endswith(ext) for ext in image_extensions):
                input_path = os.path.join(root, file)
                stats['total'] += 1
                
                # Create relative path from source_dir to maintain structure
                relative_path = os.path.relpath(root, source_dir)
                
                # Create output directory path
                if relative_path == ".":
                    output_folder = output_dir
                else:
                    output_folder = os.path.join(output_dir, relative_path)
                
                # Create output folder if it doesn't exist
                os.makedirs(output_folder, exist_ok=True)
                
                # Generate output file path with .pdf extension
                filename_without_ext = os.path.splitext(file)[0]
                output_pdf_path = os.path.join(output_folder, f"{filename_without_ext}.pdf")
                
                try:
                    # Check if file is blank (0 bytes)
                    if os.path.getsize(input_path) == 0:
                        print(f"⚠ Skipped (blank file): {input_path}")
                        stats['failed'] += 1
                        continue
                    
                    # Try to open and validate image
                    try:
                        image = Image.open(input_path)
                        image.load()  # Force load to verify image integrity
                    except IOError as io_err:
                        print(f"⚠ Skipped (corrupt/invalid image): {input_path} - {str(io_err)}")
                        stats['failed'] += 1
                        continue
                    except Exception as img_err:
                        print(f"⚠ Skipped (unable to read image): {input_path} - {str(img_err)}")
                        stats['failed'] += 1
                        continue
                    
                    # Validate image has dimensions
                    if image.size[0] <= 0 or image.size[1] <= 0:
                        print(f"⚠ Skipped (invalid dimensions): {input_path}")
                        stats['failed'] += 1
                        continue
                    
                    # Extract text using OCR
                    print(f"🔍 Scanning OCR: {input_path}")
                    ocr_result = extract_text_from_image(input_path)
                    
                    if not ocr_result['success']:
                        print(f"✗ Skipped (OCR failed): {input_path} - {ocr_result.get('error', 'Unknown error')}")
                        stats['failed'] += 1
                        stats['errors'].append(f"{input_path}: {ocr_result.get('error', 'OCR failed')}")
                        continue
                    
                    # Create searchable PDF with original image and OCR text layer
                    create_searchable_pdf(input_path, output_pdf_path, ocr_result['full_text'])
                    
                    print(f"✓ Converted with OCR: {input_path} → {output_pdf_path}")
                    stats['success'] += 1
                
                except PermissionError:
                    print(f"✗ Skipped (permission denied): {input_path}")
                    stats['failed'] += 1
                    stats['errors'].append(f"{input_path}: Permission denied")
                except IOError as e:
                    print(f"✗ Skipped (IO error): {input_path} - {str(e)}")
                    stats['failed'] += 1
                    stats['errors'].append(f"{input_path}: {str(e)}")
                except MemoryError:
                    print(f"✗ Skipped (image too large/insufficient memory): {input_path}")
                    stats['failed'] += 1
                    stats['errors'].append(f"{input_path}: Insufficient memory")
                except Exception as e:
                    print(f"✗ Skipped (unexpected error): {input_path} - {str(e)}")
                    stats['failed'] += 1
                    stats['errors'].append(f"{input_path}: {str(e)}")
    
    # Print summary
    print("\n" + "="*60)
    print("OCR TO PDF CONVERSION SUMMARY")
    print("="*60)
    print(f"Total files processed: {stats['total']}")
    print(f"Successfully converted: {stats['success']}")
    print(f"Failed: {stats['failed']}")
    
    if stats['errors']:
        print("\nErrors encountered:")
        for error in stats['errors']:
            print(f"  - {error}")
    
    print(f"\nSearchable PDF files saved to: {output_dir}")
    print("PDFs are ready for RAG chunking and extraction")
    print("Each PDF contains: original resume image + searchable OCR text layer")
    print("="*60)

if __name__ == "__main__":
    print("Starting OCR-based searchable PDF creation...")
    print("This may take a while depending on the number and size of images.\n")
    convert_images_to_pdf()
    print("\nOCR conversion to searchable PDF documents complete!")
