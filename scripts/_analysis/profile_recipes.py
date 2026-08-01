import os, re, json
from collections import Counter, defaultdict

D = "/Users/chaseeasterling/Dev/KitchenOS/vault/KitchenOS/Recipes"
files = sorted(f for f in os.listdir(D) if f.endswith(".md"))

key_counts = Counter()
heading_counts = Counter()
per_file = {}
no_fm = []
fm_shapes = Counter()

for f in files:
    p = os.path.join(D, f)
    try:
        txt = open(p, encoding="utf-8").read()
    except Exception as e:
        print("ERR", f, e); continue
    keys, headings = [], []
    if txt.startswith("---"):
        end = txt.find("\n---", 3)
        fm = txt[3:end] if end != -1 else ""
        body = txt[end+4:] if end != -1 else ""
        for line in fm.splitlines():
            m = re.match(r"^([A-Za-z_][A-Za-z0-9_\-]*):", line)
            if m: keys.append(m.group(1))
    else:
        no_fm.append(f); body = txt
    for line in body.splitlines():
        m = re.match(r"^(#{1,4})\s+(.+?)\s*$", line)
        if m: headings.append(m.group(2))
    key_counts.update(set(keys))
    heading_counts.update(set(headings))
    per_file[f] = {"keys": keys, "headings": headings, "bytes": len(txt)}
    fm_shapes[tuple(sorted(set(keys)))] += 1

print(f"TOTAL FILES: {len(files)}   no frontmatter: {len(no_fm)}")
print(f"DISTINCT frontmatter key-sets: {len(fm_shapes)}")
print("\n=== FRONTMATTER KEYS (count / %) ===")
for k, c in key_counts.most_common():
    print(f"{c:4}  {100*c//len(files):3}%  {k}")
print("\n=== HEADINGS (count / %) ===")
for h, c in heading_counts.most_common(40):
    print(f"{c:4}  {100*c//len(files):3}%  {h}")
print("\n=== FILES WITHOUT FRONTMATTER ===")
for f in no_fm[:30]: print("   ", f)
json.dump(per_file, open("/private/tmp/claude-501/-Users-chaseeasterling-Dev/1bf52a58-c19a-4d07-8909-968586c04da9/scratchpad/recipe_profile.json","w"), indent=1)
