# -*- coding: utf-8 -*-
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
h = Path(r"D:\Porto\analisis_mrt_jakarta\.work\mrt_index.js").read_text(encoding="utf-8")

for pat in (r'pagination', r'\bstart:', r'filters'):
    print(f"===== {pat} =====")
    for m in list(re.finditer(pat, h))[:8]:
        s = h[max(0, m.start() - 260): m.end() + 260]
        print("---", re.sub(r"\s+", " ", s))
    print()
