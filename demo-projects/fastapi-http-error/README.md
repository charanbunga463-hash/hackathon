# Orders API — wrong HTTP status

> GET /orders/{order_id} answers 200 with a null body for an order that does not exist.

A deliberately broken FastAPI project used to demonstrate and test API Doctor's
detect → diagnose → repair → verify pipeline. **The defect is intentional.**

## The seeded defect

| | |
|---|---|
| Bug class | `HTTPStatus` |
| Failing endpoint | `GET /orders/{order_id}` |
| Expected error | `AssertionError: assert 200 == 404` |
| Difficulty | medium |

get_order returns None on the missing-order path, which FastAPI serialises as a 200 with a null body.

## What a correct repair looks like

Raise HTTPException(status_code=404) instead of returning None.

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
python backend/tests/run_repair_matrix.py fastapi-http-error
```
