# -*- coding: utf-8 -*-
import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
d = json.loads(Path(r"D:\Porto\analisis_mrt_jakarta\.work\mrt_datum_stasiun.json").read_text(encoding="utf-8"))
rows = d.get("data", [])
print(f"total stasiun di datum: {len(rows)}\n")
for i, r in enumerate(rows):
    print(f"{i+1:>2}. {r.get('name')}  (id={r.get('id')})")
