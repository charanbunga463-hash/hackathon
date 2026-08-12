# Catalog API — response contract violation

> GET /books/{book_id} returns 500: the response is missing a field its response_model requires.

A deliberately broken FastAPI project used to demonstrate and test API Doctor's
detect → diagnose → repair → verify pipeline. **The defect is intentional.**

## The seeded defect

| | |
|---|---|
| Bug class | `ResponseValidationError` |
| Failing endpoint | `GET /books/{book_id}` |
| Expected error | `fastapi.exceptions.ResponseValidationError: isbn Field required` |
| Difficulty | medium |

get_book declares response_model=BookOut, which requires isbn, but the returned dict omits it.

## What a correct repair looks like

Include the isbn field, which the source record already carries, in the returned object.

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
python backend/tests/run_repair_matrix.py fastapi-contract
```
