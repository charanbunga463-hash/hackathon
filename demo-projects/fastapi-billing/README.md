# Billing API — ZeroDivisionError

> GET /carts/{cart_id}/average returns 500 for an empty cart.

A deliberately broken FastAPI project used to demonstrate and test API Doctor's
detect → diagnose → repair → verify pipeline. **The defect is intentional.**

## The seeded defect

| | |
|---|---|
| Bug class | `ZeroDivisionError` |
| Failing endpoint | `GET /carts/{cart_id}/average` |
| Expected error | `ZeroDivisionError: division by zero` |
| Difficulty | easy |

cart_average divides the total by len(items) without checking that the cart has items.

## What a correct repair looks like

Guard the division so an empty cart yields an average of 0 instead of crashing.

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
python backend/tests/run_repair_matrix.py fastapi-billing
```
