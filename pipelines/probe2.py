# -*- coding: utf-8 -*-
"""Probe: nama persis halte BRT utk kasus uji Pulogadung."""
import sys

from db import connect

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
conn = connect()
cur = conn.cursor()
cur.execute("""
    SELECT stop_id_internal, canonical_name FROM stops
    WHERE mode_id='BRT' AND canonical_name LIKE 'Pulo%'
    ORDER BY canonical_name LIMIT 30
""")
for r in cur.fetchall():
    print(r)
conn.close()
