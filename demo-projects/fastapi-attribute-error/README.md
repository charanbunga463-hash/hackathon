# Sessions API — AttributeError

> GET /sessions/{token}/expiry returns 500: the handler reads an attribute the model does not define.

A deliberately broken FastAPI project used to demonstrate and test API Doctor's
detect → diagnose → repair → verify pipeline. **The defect is intentional.**

## The seeded defect

| | |
|---|---|
| Bug class | `AttributeError` |
| Failing endpoint | `GET /sessions/{token}/expiry` |
| Expected error | `AttributeError: 'Session' object has no attribute 'expiry'` |
| Difficulty | easy |

session_expiry reads session.expiry, but the Session dataclass defines expires_at.

## What a correct repair looks like

Read session.expires_at instead of session.expiry.

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
python backend/tests/run_repair_matrix.py fastapi-attribute-error
```
