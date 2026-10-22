"""Dev DB kopyası üzerinde v3 migration'ın zararsız olduğunu doğrula."""
import sys, os, sqlite3, shutil, tempfile

sys.path.insert(0, 'src')
tmp = os.path.join(tempfile.gettempdir(), 'devdb_migration_test.db')
shutil.copyfile('database/glove_test.db', tmp)

from core.database import Database
Database(tmp)  # açılışta migration çalışır

conn = sqlite3.connect(tmp)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

cur.execute('SELECT host, input_count, di_words, ai_words, ao_words, do_words FROM weidmuller_modules')
m = dict(cur.fetchone())
print('modul:', m)
assert (m['input_count'], m['di_words'], m['ai_words']) == (32, 2, 0), 'dev haritasi bozuldu!'

cur.execute('SELECT COUNT(*) FROM weidmuller_io_points WHERE link_type IS NOT NULL')
n_link = cur.fetchone()[0]
print('linkli nokta:', n_link)
assert n_link == 21, f'link kaybi! {n_link} != 21'

cur.execute("SELECT name FROM weidmuller_io_points WHERE point_type='DI' AND channel=0")
print('DI0 adi:', cur.fetchone()[0])

cur.execute("SELECT setting_value FROM system_settings WHERE setting_key='weidmuller_schema_version'")
print('versiyon:', cur.fetchone()[0])

cur.execute("SELECT setting_value FROM system_settings WHERE setting_key='oraps_weidmuller_ip'")
print('ip:', cur.fetchone()[0])

conn.close()
os.remove(tmp)
print('DEV DB KORUNDU - OK')
