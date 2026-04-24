"""Quick script to inspect both PDFs and compare them."""
import fitz
import os

base = os.path.dirname(os.path.abspath(__file__))

# 1. Read the original
orig_path = os.path.join(base, "2407.12826v1.pdf")
doc_orig = fitz.open(orig_path)
print(f"ORIGINAL: {len(doc_orig)} pages")
print("--- FIRST 400 chars of page 1 ---")
print(doc_orig[0].get_text()[:400])
print()

# 2. Read the translated
trans_path = os.path.join(base, "peertranslate_bn_preserved.pdf")
doc_trans = fitz.open(trans_path)
print(f"TRANSLATED: {len(doc_trans)} pages")
print("--- FIRST 400 chars of page 1 ---")
print(doc_trans[0].get_text()[:400])
print()

# 3. Check if texts are the same
orig_text = "".join([p.get_text() for p in doc_orig])
trans_text = "".join([p.get_text() for p in doc_trans])

# Count Bengali unicode chars (U+0980 to U+09FF)
bengali_chars = sum(1 for c in trans_text if '\u0980' <= c <= '\u09FF')
total_chars = len(trans_text)

print(f"Original total chars: {len(orig_text)}")
print(f"Translated total chars: {total_chars}")
print(f"Bengali chars in translated: {bengali_chars} ({bengali_chars/max(total_chars,1)*100:.1f}%)")
print(f"Texts identical: {orig_text == trans_text}")

# Show a sample from middle of translated
mid = total_chars // 2
print(f"\n--- SAMPLE from middle of translated (chars {mid} to {mid+400}) ---")
print(trans_text[mid:mid+400])
