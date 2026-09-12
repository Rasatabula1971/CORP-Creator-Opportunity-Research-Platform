# CORP Search-Before-Build Checklist

**Rule:** Before writing any module tagged `Build` in the capability decomposition, run this checklist. The goal is to confirm that no public implementation already does what you're about to write.

## For each Build module:

1. **What capability does this module provide?** (one sentence)
2. **Search terms used:** (list)
3. **Repos/packages examined:** (list with links)
4. **Verdict:** Adopt / Adapt / Wrap / Reference / Reject / **Build confirmed**
5. **Rationale for Build:** (why nothing found fits)

---

## Current Build items (from capability decomposition)

### Normalized adapter output schema
- **Capability:** One pydantic model that both adapter families (creator-bound + niche-signal) emit, carrying `compliance_status` + `access_method`.
- **Search result:** No public schema does this for multi-source creator research with compliance fields. Standard social media schemas (e.g., social-media-toolkit, snscrape) normalize content but don't carry compliance/access-method metadata.
- **Verdict:** Build confirmed — it's a pydantic model, not a framework.

### Commercial-intent signal hierarchy (rules table)
- **Capability:** weak/moderate/strong/validation signal classification rules.
- **Search result:** Marketing-intent classifiers exist (e.g., intent-classifier on HuggingFace) but are model-based, not rules-table-based, and don't map to CORP's 4-level hierarchy tied to audience comments.
- **Verdict:** Build confirmed — it's a YAML rules file, not code.

### Dossier template
- **Capability:** CORP §13 decision-ready dossier format.
- **Search result:** No public template matches the specific structure (creator + audience problems + evidence + scoring + confidence). Generic research report templates exist but don't carry the evidence-chain semantics.
- **Verdict:** Build confirmed — it's a Jinja2 template.

---

## How to run this check for new modules

```bash
# 1. Search GitHub
# 2. Search PyPI
# 3. Search HuggingFace (for ML-related)
# 4. Check the 5 repos already evaluated (§3 of build design)
# 5. Document findings here before writing code
```
