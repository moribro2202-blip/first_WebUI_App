# -*- coding: utf-8 -*-
"""SEレコード1件をダンプして構造を解析
py -3.12-32 scripts/jravan/dump_se_record.py
"""
import os, sys, time
sys.stdout.reconfigure(encoding='utf-8')

def create_jv():
    import win32com.client
    jv = win32com.client.Dispatch('JVDTLab.JVLink')
    ret = jv.JVInit('UNKNOWN')
    if ret != 0: raise RuntimeError(f'JVInit failed: {ret}')
    return jv

jv = create_jv()
ret = jv.JVOpen('RACE', '20250101000000', 4, 0, 0, '')
if isinstance(ret, tuple):
    code = ret[0]
    print(f'JVOpen code: {code}')
    if ret[2] > 0:
        print(f'Downloading {ret[2]} files...')
        t0 = time.time()
        while jv.JVStatus() < ret[2]:
            if time.time() - t0 > 120: break
            time.sleep(0.5)

# Find first SE record
found = 0
for _ in range(500000):
    try:
        r = jv.JVRead(bytearray(200000), 200000, '')
        if isinstance(r, tuple) and len(r) >= 2:
            rc = r[0]
            if rc == 0: break
            if rc == -1: continue
            if rc > 0:
                d = r[1]
                if len(d) > 2 and d[:2] == 'SE':
                    found += 1
                    if found > 3: break  # Skip first few, get a good one

                    print(f'\n=== SE Record #{found} (len={len(d)}) ===')
                    key16 = d[11:27]
                    print(f'Race key: {key16}')

                    # Dump in 50-char chunks
                    for start in range(0, min(len(d), 2000), 50):
                        chunk = d[start:start+50]
                        # Show printable chars
                        printable = ''.join(c if 32 <= ord(c) < 127 else '.' for c in chunk)
                        print(f'  {start:>4}: {printable}')

                    # Also look for specific patterns
                    # Horse number pattern: look for "01" to "18" followed by data
                    print(f'\n  Searching for horse block pattern...')
                    for pos in range(27, min(len(d), 3000)):
                        # Look for 2-digit horse numbers followed by consistent spacing
                        chunk = d[pos:pos+2]
                        try:
                            hn = int(chunk)
                            if 1 <= hn <= 18:
                                # Look ahead for last_3f candidate
                                context = d[pos:pos+200]
                                printable = ''.join(c if 32 <= ord(c) < 127 else '.' for c in context[:100])
                                # Check specific offsets for 3-digit numbers in 320-420 range
                                for off in range(2, 100):
                                    try:
                                        val = int(d[pos+off:pos+off+3])
                                        if 320 <= val <= 420:
                                            print(f'    pos={pos} hn={hn:02d} off={off} l3f={val/10:.1f}s ctx="{printable[:60]}"')
                                            break
                                    except: pass
                        except: pass
        else:
            break
    except: break

try: jv.JVClose()
except: pass
print('\nDone!')
