# ShowSeat: concurrency-safe seat booking API

Two-phase booking (**hold -> book**) that never double-books, even under heavy concurrent load.

- **Atomic holds:** a single conditional `UPDATE ... WHERE status='AVAILABLE' OR hold expired`; the DB, not app code, decides the winner.
- **All-or-nothing multi-seat holds:** `rowcount` must equal seats requested, else the transaction rolls back.
- **Lazy hold expiry:** no cron/worker; expired holds are simply claimable.
- **Idempotent booking:** `Idempotency-Key` header + UNIQUE constraint makes client retries safe.
- **Testable core:** `booking/core.py` has no web dependency; `app.py` is a thin FastAPI layer.

## Run
    pip install -r requirements.txt
    uvicorn app:app --reload        # open http://localhost:8000/docs
    python -m unittest -v           # 6 tests incl. 30-thread race

## Deploy (Render)
Push to GitHub -> Render -> New -> Blueprint -> pick the repo (uses `render.yaml` + `Dockerfile`).
Free tier disk is ephemeral; use a persistent disk or move to Postgres for durable data.
