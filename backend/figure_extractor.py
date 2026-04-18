"""
PeerTranslate — Figure Extractor module

Uses PyMuPDF (fitz) to extract images and figures from academic
research papers, allowing the platform to re-insert them into the
translated markdown.
"""

import fitz  # PyMuPDF
import base64
import logging
from typing import Dict, List, Tuple
import re

logger = logging.getLogger(__name__)

def extract_images_from_pdf(pdf_bytes: bytes) -> Dict[int, str]:
    """
    Extract images from a PDF and heuristicly determine their original
    reading order or approximate figure numbers.
    Returns a dictionary of roughly estimated figure numbers mapping to base64 images.
    """
    try:
        doc = fitz.open("pdf", pdf_bytes)
    except Exception as e:
        logger.error(f"Failed to open PDF for image extraction: {e}")
        return {}

    figures: Dict[int, str] = {}
    figure_counter = 1

    for page_num in range(len(doc)):
        page = doc[page_num]
        image_list = page.get_images(full=True)
        
        # Sort images on page by their vertical position (y0)
        # This is a heuristic to order them top-to-bottom
        try:
            # get_image_info() gives bounding boxes
            image_info = page.get_image_info()
            # Sort by y0 (top coordinate)
            image_info.sort(key=lambda img: img['bbox'][1])
            
            # Map xref to sorted order
            sorted_xrefs = [img['xref'] for img in image_info]
        except Exception:
            sorted_xrefs = [img[0] for img in image_list]

        for xref in sorted_xrefs:
            try:
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
                image_ext = base_image["ext"]
                
                # Skip tiny images (like logos or icons)
                if len(image_bytes) < 5000:  
                    continue
                    
                b64_image = base64.b64encode(image_bytes).decode("utf-8")
                
                # We simply index them sequentially as they appear in the PDF.
                # More advanced heuristics would map them to "Figure X" captions.
                figures[figure_counter] = f"data:image/{image_ext};base64,{b64_image}"
                figure_counter += 1
            except Exception as e:
                logger.warning(f"Error extracting image xref {xref} on page {page_num}: {e}")

    logger.info(f"Extracted {len(figures)} figures from PDF.")
    return figures


def reinsert_figures(translated_markdown: str, figures: Dict[int, str]) -> str:
    """
    Attempt to inject the extracted figures back into the translated markdown.
    It looks for patterns like:
    "চিত্র 1", "Figure 1", "Fig. 1" 
    or simply inserts them linearly if it can't find direct caption matches.
    """
    if not figures:
        return translated_markdown

    lines = translated_markdown.split("\n")
    processed_lines = []
    
    # We will inject figure N when we see the Nth generic figure reference,
    # or just spread them out.
    figure_index = 1
    
    for line in lines:
        processed_lines.append(line)
        
        # Look for translated "Figure X" captions at the start of lines or standalone
        # This is a simple heuristic.
        lower_line = line.lower()
        if (
            "figure" in lower_line or 
            "fig." in lower_line or 
            "চিত্র" in lower_line or 
            "चित्र" in lower_line
        ):
            # Check if there is a number
            match = re.search(r'\d+', line)
            if match:
                num = int(match.group())
                if num in figures:
                    # Inject the image right BEFORE the caption line
                    img_md = f"\n![Figure {num}]({figures[num]})\n"
                    
                    # Pop the caption, append the image, then append the caption
                    cap = processed_lines.pop()
                    processed_lines.append(img_md)
                    processed_lines.append(cap)
                    
                    # Remove from dict so we don't inject it twice
                    del figures[num]

    # If there are left over figures, we'll just append them at the end
    result = "\n".join(processed_lines)
    
    if figures:
        result += "\n\n## Extracted Figures\n\n"
        for num, b64_str in sorted(figures.items()):
            result += f"![Figure {num}]({b64_str})\n\n"
            
    return result
