# Users API — KeyError

> GET /users/{user_id} returns 500 because the handler reads a key the data does not have.

A deliberately broken FastAPI project used to demonstrate and test API Doctor's
detect → diagnose → repair → verify pipeline. **The defect is intentional.**

## The seeded defect

| | |
|---|---|
| Bug class | `KeyError` |
| Failing endpoint | `GET /users/{user_id}` |
| Expected error | `KeyError: 'username'` |
| Difficulty | easy |

main.py builds the response with user["username"], but USERS records store the key "name".

## What a correct repair looks like

Read user["name"] instead of user["username"]; the response key "username" stays as the API contract requires.

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
python backend/tests/run_repair_matrix.py fastapi-keyerror
```
