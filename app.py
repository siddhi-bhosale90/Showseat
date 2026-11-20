import os

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from booking.core import BookingService, Conflict

svc = BookingService(os.getenv("DB_PATH", "bookings.db"), int(os.getenv("HOLD_SECONDS", "300")))
app = FastAPI(title="ShowSeat", description="Concurrency-safe seat booking with expiring holds")


class NewShow(BaseModel):
    name: str
    rows: int = Field(5, ge=1, le=26)
    cols: int = Field(10, ge=1, le=50)


class SeatRequest(BaseModel):
    user: str
    seats: list[str] = Field(min_length=1, max_length=10)


@app.get("/health")
def health():
    return {"ok": True}


@app.post("/shows", status_code=201)
def create_show(body: NewShow):
    return svc.create_show(body.name, body.rows, body.cols)


@app.get("/shows/{show_id}/seats")
def seats(show_id: int):
    return svc.seats(show_id)


@app.post("/shows/{show_id}/hold")
def hold(show_id: int, body: SeatRequest):
    try:
        return svc.hold(show_id, body.user, body.seats)
    except Conflict as e:
        raise HTTPException(409, str(e))


@app.post("/shows/{show_id}/book", status_code=201)
def book(show_id: int, body: SeatRequest, idempotency_key: str = Header(...)):
    try:
        return svc.book(show_id, body.user, body.seats, idempotency_key)
    except Conflict as e:
        raise HTTPException(409, str(e))
