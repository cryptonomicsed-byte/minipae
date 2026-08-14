#!/usr/bin/env python3
"""de_verify_skill's actual checker — structural validation of
skills/catalog.yaml and its skill entries. See SKILL.md for the contract.
"""
from __future__ import annotations

import json
import re
import sys

import yaml

REQUIRED_FRONTMATTER_FIELDS = {
    "id", "verb", "name", "description", "version", "status", "trigger",
    "inputs", "outputs", "verification", "runtimes", "memory", "owner",
}


def load_catalog(repo_root: str) -> dict:
    with open(f"{repo_root}/skills/catalog.yaml") as f:
        return yaml.safe_load(f)


def load_frontmatter(path: str) -> dict:
    with open(path) as f:
        text = f.read()
    m = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    if not m:
        raise ValueError(f"{path}: no YAML frontmatter block found")
    return yaml.safe_load(m.group(1))


def registered_namespaces(repo_root: str) -> set[str]:
    with open(f"{repo_root}/NAMESPACES.md") as f:
        text = f.read()
    return set(re.findall(r"`(mem/[a-z0-9_]+/\*)`", text))


def verify_catalog(repo_root: str, only_skill_id: str | None = None) -> dict:
    catalog = load_catalog(repo_root)
    failures: list[str] = []
    checked = 0
    passed = 0

    if catalog.get("schema") != "skill-catalog/v1":
        failures.append(f"catalog schema is {catalog.get('schema')!r}, expected 'skill-catalog/v1'")

    verb_names = {v["verb"] for v in catalog.get("verbs", [])}
    namespaces = registered_namespaces(repo_root)

    for entry in catalog.get("skills", []):
        if only_skill_id and entry["id"] != only_skill_id:
            continue
        checked += 1
        entry_ok = True

        try:
            fm = load_frontmatter(f"{repo_root}/{entry['file']}")
        except Exception as e:
            failures.append(f"{entry['id']}: failed to load frontmatter ({e})")
            continue

        if fm.get("id") != entry["id"]:
            failures.append(f"{entry['id']}: catalog id != frontmatter id ({fm.get('id')!r})")
            entry_ok = False

        if fm.get("verb") not in verb_names:
            failures.append(f"{entry['id']}: verb {fm.get('verb')!r} not in catalog verbs")
            entry_ok = False

        missing = REQUIRED_FRONTMATTER_FIELDS - fm.keys()
        if missing:
            failures.append(f"{entry['id']}: missing frontmatter fields {sorted(missing)}")
            entry_ok = False

        mem = fm.get("memory", {}) or {}
        for ns in list(mem.get("reads", [])) + list(mem.get("writes", [])):
            # namespaces may be wildcard slugs like "mem/values/*" — normalize
            ns_prefix = "/".join(ns.split("/")[:2]) + "/*"
            if ns_prefix not in namespaces:
                failures.append(f"{entry['id']}: namespace {ns!r} (prefix {ns_prefix}) not in NAMESPACES.md")
                entry_ok = False

        if entry_ok:
            passed += 1

    return {"checked": checked, "passed": passed, "failures": failures}


if __name__ == "__main__":
    repo_root = sys.argv[1] if len(sys.argv) > 1 else "."
    only = sys.argv[2] if len(sys.argv) > 2 and sys.argv[2] else None
    result = verify_catalog(repo_root, only)
    print(json.dumps(result, indent=2))
    sys.exit(0 if not result["failures"] else 1)
