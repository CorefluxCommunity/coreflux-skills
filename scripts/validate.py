#!/usr/bin/env python3
"""Check every skills/<name>/SKILL.md against the Agent Skills frontmatter rules and skills.json."""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
ALLOWED = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}

errors: list[str] = []
found: set[str] = set()
for skill in sorted((ROOT / "skills").glob("*/SKILL.md")):
    text = skill.read_text(encoding="utf-8")
    end = text.find("\n---\n", 4)
    if not text.startswith("---\n") or end < 0:
        errors.append(f"{skill}: missing frontmatter")
        continue
    fields = dict(line.split(":", 1) for line in text[4:end].splitlines() if ":" in line)
    fields = {k.strip(): v.strip() for k, v in fields.items()}
    name = fields.get("name", "")
    found.add(name)
    if name != skill.parent.name or not NAME_RE.match(name):
        errors.append(f"{skill}: name '{name}' must be kebab-case and match its folder")
    if not 0 < len(fields.get("description", "")) <= 1024:
        errors.append(f"{skill}: description must be 1-1024 characters")
    if extra := set(fields) - ALLOWED:
        errors.append(f"{skill}: unknown frontmatter keys {sorted(extra)}")

listed = {s["name"] for s in json.loads((ROOT / "skills.json").read_text())["skills"]}
if listed != found:
    errors.append(f"skills.json lists {sorted(listed ^ found)} out of step with skills/")

print("\n".join(errors) or f"{len(found)} skills OK")
sys.exit(1 if errors else 0)
