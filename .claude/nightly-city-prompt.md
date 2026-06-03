# LVTShift Nightly Automation

You are running the automated overnight LVTShift modeling pipeline on ${TODAY}.

## City to model: ${CITY}

This is an unattended CI run. **Do not ask any clarifying questions.** Use the defaults below and proceed directly through all steps.

## Pre-answered modeling parameters

| Question | Answer |
|---|---|
| Scope | City levy only |
| Reform | 4:1 split-rate (`LAND_IMPROVEMENT_RATIO = 4.0`, `MODEL_TYPE = 'split_rate:4.0'`) |
| Exemptions | Preserve all existing exemptions unchanged |
| Revenue validation | Use the best official figure you can find; ±10% is acceptable for an initial nightly model |

## Steps — execute in order, no confirmation needed

### 1. Model the city

Invoke the `model-city` skill for **${CITY}**.

Important CI overrides:
- Use kernel `python3` for all `nbconvert --execute` calls (not `cle-venv-new`)
- Do **not** push yet — hold the push until after political viability
- If the county GIS endpoint is unreachable, parcel-level land values are unavailable, or the data source requires a manual download, write a brief explanation to `cities/${CITY}/BLOCKED.md` (one paragraph: what was needed, where to find it) and skip to Step 3

### 2. Political viability

Invoke the `political-viability` skill for **${CITY}**.

### 3. Commit and push everything

```bash
git add cities/${CITY}/ analysis/
git commit -m "nightly: Add ${CITY} LVT model — split_rate:4.0"
git push
```

---

That is the complete task. Do not do anything beyond these three steps.
