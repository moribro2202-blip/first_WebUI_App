# -*- coding: utf-8 -*-
"""SE record を複数馬ダンプして上がり3Fの位置を確定
py -3.12-32 scripts/jravan/dump_se_v2.py
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
ret = jv.JVOpen('RACE', '20250901000000', 4, 0, 0, '')
if isinstance(ret, tuple) and ret[2] > 0:
    t0 = time.time()
    while jv.JVStatus() < ret[2]:
        if time.time() - t0 > 120: break
        time.sleep(0.5)

# Collect multiple SE records for the same race to compare
race_records = {}
count = 0
for _ in range(1000000):
    try:
        r = jv.JVRead(bytearray(200000), 200000, '')
        if isinstance(r, tuple) and len(r) >= 2:
            rc = r[0]
            if rc == 0: break
            if rc == -1: continue
            if rc > 0:
                d = r[1]
                if len(d) > 2 and d[:2] == 'SE':
                    key16 = d[11:27]
                    if key16 not in race_records:
                        race_records[key16] = []
                    race_records[key16].append(d)
                    count += 1
                    if count >= 200: break
        else: break
    except: break

try: jv.JVClose()
except: pass

# Analyze one full race
print(f'Collected {count} SE records from {len(race_records)} races\n')

for key16, records in sorted(race_records.items())[:2]:
    print(f'=== Race {key16} ({len(records)} horses) ===')
    for d in records[:18]:
        # Key fields we can identify:
        # pos 27-36: horse_id area
        # Let me dump specific positions
        raw = d

        # Try to find: horse_number, finish_position, finish_time, last_3f
        # by comparing across horses in the same race

        # Dump pos 27-50 (likely horse identification)
        id_area = raw[27:50]
        # Dump pos 55-75 (likely race result data)
        r1 = raw[55:75]
        # Dump pos 150-210 (likely timing data)
        t1 = raw[150:210]
        # Dump pos 260-290
        t2 = raw[260:290]
        # Dump pos 340-379
        t3 = raw[340:min(len(raw),379)]

        print(f'  27-50: "{id_area}"')
        print(f'  55-75: "{r1}"')
        print(f'  150-210: "{t1}"')
        print(f'  260-290: "{t2}"')
        print(f'  340-end: "{t3}"')
        print()

print('Done!')
