import os, re
from collections import Counter, defaultdict
D="/Users/chaseeasterling/Dev/KitchenOS/vault/KitchenOS/Recipes"
files=sorted(f for f in os.listdir(D) if f.endswith(".md"))
rows=[]
for f in files:
    txt=open(os.path.join(D,f),encoding="utf-8").read()
    end=txt.find("\n---",3); fm=txt[3:end]; body=txt[end+4:]
    kv={}
    for line in fm.splitlines():
        m=re.match(r"^([A-Za-z_][\w\-]*):\s*(.*)$",line)
        if m: kv[m.group(1)]=m.group(2).strip()
    hs=[re.match(r"^#{1,4}\s+(.+?)\s*$",l).group(1) for l in body.splitlines() if re.match(r"^#{1,4}\s+",l)]
    rows.append(dict(f=f,kv=kv,hs=hs,body=body))

both=[r for r in rows if "Nutrition (per serving)" in r["hs"] and "Nutritional Info" in r["hs"]]
print(f"=== FILES WITH *TWO* NUTRITION SECTIONS: {len(both)} ===")
for r in both[:25]: print("   ", r["f"])

def shape(v):
    if v=="" : return "block/list (value on next lines)"
    if v=="null": return "null"
    if re.match(r'^".*"$',v): return "quoted"
    if re.match(r'^\[.*\]$',v): return "inline-list"
    if re.match(r'^-?\d+(\.\d+)?$',v): return "number"
    if v in ("true","false"): return "bool"
    return "bare"
print("\n=== KEYS WITH MIXED VALUE SHAPES (quoting/type drift) ===")
by=defaultdict(Counter)
for r in rows:
    for k,v in r["kv"].items(): by[k][shape(v)]+=1
for k,c in sorted(by.items()):
    if len(c)>1: print(f"  {k:26} {dict(c)}")

print("\n=== TIME FIELD VALUE FORMATS (prep_time) ===")
print(Counter(r["kv"].get("prep_time","-") for r in rows).most_common(12))
print("\n=== servings VALUE FORMATS ===")
print(Counter(r["kv"].get("servings","-") for r in rows).most_common(10))
print("\n=== serving_size VALUE FORMATS (top) ===")
print(Counter(r["kv"].get("serving_size","-") for r in rows).most_common(8))
print("\n=== banner / cssclasses ===")
print("banner:", Counter(shape(r['kv'].get('banner','')) for r in rows).most_common())
print("cssclasses:", Counter(shape(r['kv'].get('cssclasses','')) for r in rows).most_common())
