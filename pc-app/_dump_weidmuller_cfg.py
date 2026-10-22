import sqlite3, json, sys

DB = sys.argv[1] if len(sys.argv) > 1 else 'database/glove_test.db'
conn = sqlite3.connect(DB)
conn.row_factory = sqlite3.Row
cur = conn.cursor()

print('=== MODULES ===')
cur.execute('SELECT * FROM weidmuller_modules')
for r in cur.fetchall():
    print(json.dumps(dict(r), ensure_ascii=False))

print('=== POINT COUNTS ===')
cur.execute('SELECT module_id, point_type, COUNT(*) n FROM weidmuller_io_points GROUP BY module_id, point_type')
for r in cur.fetchall():
    print(dict(r))

print('=== ALL POINTS (custom name / linked / hidden / scaled) ===')
cur.execute('''SELECT id,module_id,point_type,channel,name,unit,scale,offset,is_visible,
               sort_order,link_type,link_id,link_role,low_alarm,high_alarm
               FROM weidmuller_io_points ORDER BY module_id,point_type,channel''')
for r in cur.fetchall():
    d = dict(r)
    default_name = f"{d['point_type']}{d['channel']+1}"
    interesting = (d['name'] != default_name or d['link_type'] is not None
                   or d['is_visible'] != 1 or d['scale'] != 1.0 or d['offset'] != 0.0
                   or d['low_alarm'] is not None or d['high_alarm'] is not None)
    tag = '*' if interesting else ' '
    print(tag, json.dumps(d, ensure_ascii=False))

print('=== RELATED SETTINGS ===')
cur.execute("""SELECT setting_key,setting_value FROM system_settings
               WHERE setting_key LIKE '%weidmuller%' OR setting_key LIKE 'oraps_poll%'
               OR setting_key LIKE 'oraps_di%' OR setting_key='oraps_schema_version'""")
for r in cur.fetchall():
    print(dict(r))

print('=== DOOR GROUPS ===')
try:
    cur.execute("SELECT * FROM oraps_door_groups")
    for r in cur.fetchall():
        print(dict(r))
except Exception as e:
    print('yok:', e)

print('=== DOOR LABELS (group_id dolu olanlar) ===')
try:
    cur.execute("SELECT door_index,label,group_id FROM oraps_door_labels WHERE group_id IS NOT NULL OR label!=''")
    for r in cur.fetchall():
        print(dict(r))
except Exception as e:
    print('yok:', e)

conn.close()
