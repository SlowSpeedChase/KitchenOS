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
    heads=[re.match(r"^(#{1,4})\s+(.+?)\s*$",l).groups() for l in body.splitlines() if re.match(r"^#{1,4}\s+",l)]
    rows.append(dict(f=f, kv=kv, heads=heads, body=body))

def era(r): return (r["kv"].get("date_added") or "?")[:7]

print("=== VARIANT A: legacy flat nutrition keys (calories/fat/carbs) ===")
legacy=[r for r in rows if "calories" in r["kv"]]
print(f"{len(legacy)} files, date_added months: {Counter(era(r) for r in legacy).most_common()}")
for r in legacy[:15]: print("   ", r["f"], "| src:", r["kv"].get("recipe_source","-"))

print("\n=== VARIANT B: nutrition section heading style ===")
def nutstyle(r):
    hs=[h[1] for h in r["heads"]]
    if "Nutrition (per serving)" in hs: return "Nutrition (per serving)"
    if "Nutritional Info" in hs: return "Nutritional Info"
    return "(no nutrition section)"
c=defaultdict(Counter)
for r in rows: c[nutstyle(r)][era(r)]+=1
for style,months in c.items(): print(f"  {style:28} n={sum(months.values()):4}  by month: {sorted(months.items())}")

print("\n=== VARIANT C: H1 recipe-title heading inside body ===")
h1=[r for r in rows if any(h[0]=="#" for h in r["heads"])]
print(f"{len(h1)} files have an H1 in the body (title duplicated as heading)")
print("  months:", sorted(Counter(era(r) for r in h1).items()))
noh1=[r for r in rows if not any(h[0]=="#" for h in r["heads"])]
print(f"{len(noh1)} files have NO H1 (start at ##)")
print("  months:", sorted(Counter(era(r) for r in noh1).items()))

print("\n=== VARIANT D: heading LEVEL used for the standard sections ===")
lvl=defaultdict(Counter)
for r in rows:
    for h,t in r["heads"]:
        if t in ("Ingredients","Instructions","Equipment","My Notes"): lvl[t][h]+=1
for t,cc in lvl.items(): print(f"  {t:14} {dict(cc)}")

print("\n=== VARIANT E: missing fit_* block ===")
nofit=[r for r in rows if "fit_steady" not in r["kv"]]
for r in nofit: print("   ", r["f"], "| date_added:", r["kv"].get("date_added","-"))

print("\n=== VARIANT F: short_title present ===")
st=[r for r in rows if "short_title" in r["kv"]]
print(f"{len(st)} have short_title; months: {sorted(Counter(era(r) for r in st).items())}")

print("\n=== recipe_source values ===")
print(Counter(r["kv"].get("recipe_source","(none)") for r in rows).most_common())
print("\n=== nutrition_source values ===")
print(Counter(r["kv"].get("nutrition_source","(none)") for r in rows).most_common())
