# -*- coding: utf-8 -*-
"""Probe: stop ambiguous + status cabang Bogor + nama BRT utk kasus uji."""
import sys

from db import connect

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
conn = connect()
cur = conn.cursor()

print("== stop bernama Bogor/Cilebut/Bojonggede/Cibinong/Nambo:")
cur.execute("""
    SELECT stop_id_internal, canonical_name, mode_id FROM stops
    WHERE canonical_name ILIKE ANY (%s) ORDER BY mode_id, canonical_name
""", (["%bogor%", "%cilebut%", "%bojonggede%", "%cibinong%", "%nambo%"],))
for r in cur.fetchall():
    print("  ", r)

print("\n== 'Dukuh Atas' (semua moda):")
cur.execute("""
    SELECT stop_id_internal, canonical_name, mode_id FROM stops
    WHERE canonical_name ILIKE 'dukuh atas%' ORDER BY mode_id
""")
for r in cur.fetchall():
    print("  ", r)

print("\n== BRT nama mengandung 'gadung' / 'kota' (eksklusif jakarta kota):")
cur.execute("""
    SELECT stop_id_internal, canonical_name FROM stops
    WHERE mode_id='BRT' AND (canonical_name ILIKE '%gadung%'
        OR canonical_name ILIKE '%kota')
    ORDER BY canonical_name LIMIT 20
""")
for r in cur.fetchall():
    print("  ", r)

print("\n== total stop per moda:")
cur.execute("SELECT mode_id, COUNT(*) FROM stops GROUP BY mode_id ORDER BY 2 DESC")
for r in cur.fetchall():
    print("  ", r)
conn.close()
