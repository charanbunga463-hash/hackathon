# Signup API — Pydantic ValidationError

> GET /accounts/{username}/profile returns 500: a required model field is never supplied.

A deliberately broken FastAPI project used to demonstrate and test API Doctor's
detect → diagnose → repair → verify pipeline. **The defect is intentional.**

## The seeded defect

| | |
|---|---|
| Bug class | `ValidationError` |
| Failing endpoint | `GET /accounts/{username}/profile` |
| Expected error | `ValidationError: 1 validation error for Profile — plan Field required` |
| Difficulty | medium |

account_profile constructs Profile(...) without the required `plan` field, which the account record does carry.

## What a correct repair looks like

Pass plan=account["plan"] when constructing the Profile.

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
python backend/tests/run_repair_matrix.py fastapi-validation
```
