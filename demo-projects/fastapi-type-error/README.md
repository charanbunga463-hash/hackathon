# Inventory API — TypeError

> GET /products/{sku}/gross-price returns 500: a CSV-imported price is a string.

A deliberately broken FastAPI project used to demonstrate and test API Doctor's
detect → diagnose → repair → verify pipeline. **The defect is intentional.**

## The seeded defect

| | |
|---|---|
| Bug class | `TypeError` |
| Failing endpoint | `GET /products/{sku}/gross-price` |
| Expected error | `TypeError: can't multiply sequence by non-int of type 'float'` |
| Difficulty | easy |

PRODUCTS stores price as a string, and gross_price multiplies it by a float tax multiplier.

## What a correct repair looks like

Coerce the price to float at the point of use.

The tests in `tests/` encode the intended behaviour and are the arbiter: a
repair is only accepted when they actually pass. API Doctor will not edit them —
patches that touch a test file are rejected with `modifies_tests`, because a
suite that goes green by being rewritten proves nothing.

## Run it yourself

```bash
pip install -r requirements.txt
pytest                                   # fails, by design
uvicorn main:app --reload                # then call the endpoint above
```

## Repair it with API Doctor

Open the **Demo Lab**, load this project, click **Run tests**, then **Repair**.
Loading copies the project into an isolated workspace, so this directory is
never modified and the demo can be run repeatedly.

Or drive the whole pipeline from the command line:

```bash
python backend/tests/run_repair_matrix.py fastapi-type-error
```
