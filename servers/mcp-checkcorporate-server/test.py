import sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))
from checkcorporate_server.db_tools import DbTools

db = DbTools()  # default: use_db=False -> simulazione

print("== piano dei conti (ACME) ==")
print(json.dumps(db.get_piano_dei_conti("ACME"), indent=2, ensure_ascii=False))

print("== bilancio Economico (ACME,2024) ==")
print(json.dumps(db.get_bilancio("ACME", 2024, "Economico"), indent=2, ensure_ascii=False))

print("== bilancio Patrimoniale (ACME,2024) ==")
print(json.dumps(db.get_bilancio("ACME", 2024, "Patrimoniale"), indent=2, ensure_ascii=False))