# -*- coding: utf-8 -*-
"""Tampilkan direktori instalasi PostgreSQL dari server + cek akses tulis."""
import os
import psycopg

conn = psycopg.connect(host="localhost", port=5432, user="postgres",
                       password="dicky", dbname="postgres")
cur = conn.cursor()
cur.execute("SELECT setting FROM pg_settings WHERE name='data_directory'")
data_dir = cur.fetchone()[0]
print("data_dir:", data_dir)
install_dir = os.path.dirname(data_dir)
print("install_dir:", install_dir)
print("install_dir ada:", os.path.isdir(install_dir))
test_file = os.path.join(install_dir, ".write_test")
try:
    with open(test_file, "w") as f:
        f.write("ok")
    os.remove(test_file)
    print("akses tulis install_dir: YA")
except Exception as e:
    print("akses tulis install_dir: TIDAK ->", str(e)[:120])
conn.close()
