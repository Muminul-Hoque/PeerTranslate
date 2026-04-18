"""
End-to-end test that simulates exactly what the browser does:
1. Fetch the main page and check DOM structure
2. POST a URL-based translation request  
3. Parse the SSE stream exactly like app.js does
4. Report all events and final output
"""

import httpx
import asyncio
import json
import sys
import os

# Fix Windows terminal encoding
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
os.environ['PYTHONIOENCODING'] = 'utf-8'

async def main():
    print("=" * 60)
    print(" PeerTranslate — End-to-End DOM Simulation Test")
    print("=" * 60)

    async with httpx.AsyncClient(timeout=90.0) as client:

        # ── Step 1: Load the page ──
        print("\n[1/5] Loading http://127.0.0.1:8000 ...")
        r = await client.get("http://127.0.0.1:8000")
        assert r.status_code == 200, f"Page load failed: {r.status_code}"
        
        has_tabs = 'input-tab' in r.text
        has_url_input = 'url-input' in r.text
        has_translate_btn = 'translate-btn' in r.text
        has_results = 'results-section' in r.text
        has_output = 'output-body' in r.text
        
        print(f"  Page loaded: {r.status_code} OK ({len(r.text)} bytes)")
        print(f"  DOM: tabs={has_tabs}, url_input={has_url_input}, "
              f"translate_btn={has_translate_btn}, results={has_results}, output={has_output}")
        
        if not all([has_tabs, has_url_input, has_translate_btn, has_results, has_output]):
            print("  ERROR: Missing DOM elements!")
            return

        # ── Step 2: Fetch languages ──
        print("\n[2/5] Fetching /api/languages ...")
        r = await client.get("http://127.0.0.1:8000/api/languages")
        langs = r.json()
        print(f"  Languages: {langs}")

        # ── Step 3: Submit translation (URL mode) ──
        test_url = "https://www.w3.org/WAI/ER/tests/xhtml/testfiles/resources/pdf/dummy.pdf"
        print(f"\n[3/5] Submitting translation via URL mode...")
        print(f"  URL: {test_url}")
        print(f"  Language: bn (Bengali)")

        # Simulate exactly what app.js does in URL mode:
        # It sends FormData with 'url', a dummy 'file' blob, and 'language'
        files = {'file': ('dummy.pdf', b'dummy', 'application/pdf')}
        data = {'url': test_url, 'language': 'bn'}

        # ── Step 4: Read SSE stream ──
        print(f"\n[4/5] Reading SSE stream (this simulates the browser EventSource)...")
        print("-" * 50)

        translation_text = ""
        verification_data = None
        error_msg = None
        status_messages = []

        async with client.stream(
            'POST', 'http://127.0.0.1:8000/api/translate',
            files=files, data=data
        ) as response:
            print(f"  HTTP Status: {response.status_code}")
            
            if response.status_code != 200:
                body = await response.aread()
                print(f"  ERROR: {body.decode()}")
                return

            buffer = ""
            async for chunk in response.aiter_raw():
                buffer += chunk.decode('utf-8', errors='replace')
                lines = buffer.split('\n')
                buffer = lines.pop()  # keep incomplete line

                event_type = ""
                event_data = ""

                for raw_line in lines:
                    line = raw_line.replace('\r', '')
                    if line.startswith('event:'):
                        event_type = line[6:].strip()
                    elif line.startswith('data:'):
                        data_line = line[5:].strip()
                        event_data = event_data + '\n' + data_line if event_data else data_line
                    elif line.strip() == '' and event_type and event_data:
                        # Process event — exactly like handleSSEEvent in app.js
                        if event_type == 'status':
                            status_messages.append(event_data)
                            print(f"  STATUS: {event_data.encode('ascii', 'replace').decode()}")
                        elif event_type == 'translation':
                            translation_text = event_data
                            preview = event_data[:80].encode('ascii', 'replace').decode()
                            print(f"  TRANSLATION: {preview}...")
                        elif event_type == 'verification':
                            try:
                                verification_data = json.loads(event_data)
                            except:
                                verification_data = event_data
                            print(f"  VERIFICATION: {event_data[:100]}")
                        elif event_type == 'error':
                            error_msg = event_data
                            print(f"  ERROR: {event_data[:200]}")
                        elif event_type == 'complete':
                            print(f"  COMPLETE: {event_data}")
                        elif event_type == 'retranslation':
                            print(f"  RETRANSLATION: {event_data[:100].encode('ascii', 'replace').decode()}")
                        else:
                            print(f"  {event_type}: {event_data[:100]}")
                        
                        event_type = ""
                        event_data = ""

        # ── Step 5: Final Report ──
        print("-" * 50)
        print(f"\n[5/5] Final Report")
        print("=" * 60)
        print(f"  Status messages received: {len(status_messages)}")
        print(f"  Translation text length:  {len(translation_text)} chars")
        print(f"  Translation empty?        {len(translation_text) == 0}")
        
        if verification_data and isinstance(verification_data, dict):
            print(f"  Verification score:       {verification_data.get('overall_score', 'N/A')}")
            print(f"  Verification label:       {verification_data.get('overall_label', 'N/A')}")
            print(f"  Flagged sections:         {verification_data.get('flagged_sections', 'N/A')}/{verification_data.get('total_sections', 'N/A')}")
        
        if error_msg:
            print(f"\n  *** ERROR OCCURRED: {error_msg[:300]}")
        
        if translation_text:
            print(f"\n  --- Translation Preview (first 300 chars) ---")
            # Force print with replacement for non-ASCII
            sys.stdout.buffer.write(translation_text[:300].encode('utf-8', 'replace'))
            sys.stdout.buffer.write(b'\n')
            sys.stdout.buffer.flush()
        
        print("\n" + "=" * 60)
        if translation_text and not error_msg:
            print("  RESULT: PASS - Translation pipeline completed successfully!")
        elif error_msg:
            print(f"  RESULT: FAIL - Error encountered: {error_msg[:100]}")
        else:
            print("  RESULT: FAIL - No translation output received")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
