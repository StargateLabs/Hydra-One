"""Compile read-only skill catalog data; never install or run imported instructions."""
import hashlib,json
from datetime import datetime,timezone
from pathlib import Path

def compile_skills(rows,texts,revision):
    output=[]
    for row in rows:
        path=row["path"]
        if not path.startswith("skills/") or ".." in path or path not in texts:
            raise ValueError("Missing or invalid skill path: "+path)
        identity=row["id"]
        output.append({"id":identity,"title":row.get("name") or identity,
          "description":row.get("description") or "", "category":row.get("category") or "general",
          "type":"SKILL","source":"skills","chunk":len(output)//100,
          "url":"https://github.com/sickn33/agentic-awesome-skills/blob/"+revision+"/"+path+"/SKILL.md",
          "risk":row.get("risk"),"origin":row.get("source"),"plugin":row.get("plugin"),
          "sha256":hashlib.sha256(texts[path].encode()).hexdigest()})
    return output

if __name__=="__main__":
    source=Path("output/catalog-sources/agentic-awesome-skills")
    provenance=json.loads((source/"provenance.json").read_text())
    rows=json.loads((source/"skills_index.json").read_text(encoding="utf-8"))
    texts=json.loads((source/"skill-texts.json").read_text(encoding="utf-8"))
    items=compile_skills(rows,texts,provenance["revision"])
    target=Path("serve/web")
    for chunk in range((len(items)+99)//100):
        content={row["id"]:texts[rows[i]["path"]] for i,row in enumerate(items) if row["chunk"]==chunk}
        (target/f"skill-catalog-text-{chunk}.js").write_text(
          "window.StrataSkillTexts=window.StrataSkillTexts||{};Object.assign(window.StrataSkillTexts,"+json.dumps(content,ensure_ascii=True)+");\n",encoding="utf-8")
    data={**provenance,"importedAt":datetime.now(timezone.utc).isoformat(),"items":items,
      "license":"CC BY 4.0; third-party exceptions apply", "attribution":"Agentic Awesome Skills contributors",
      "licenseText":(source/"LICENSE-CONTENT").read_text(encoding="utf-8"),
      "codeLicense":(source/"LICENSE").read_text(encoding="utf-8"),
      "sourceNotices":(source/"docs/sources/sources.md").read_text(encoding="utf-8")}
    (target/"skill-catalog-data.js").write_text("window.StrataSkillCatalog="+json.dumps(data,ensure_ascii=True)+";\n",encoding="utf-8")
    print(f"Compiled {len(items)} skill entries, {(len(items)+99)//100} text chunks")
