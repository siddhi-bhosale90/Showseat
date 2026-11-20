import os, tempfile, threading, unittest

from booking.core import BookingService, Conflict


class BookingTests(unittest.TestCase):
    def setUp(self):
        self.t = [1000.0]
        self.db = os.path.join(tempfile.mkdtemp(), "t.db")
        self.svc = BookingService(self.db, hold_seconds=60, clock=lambda: self.t[0])
        self.sid = self.svc.create_show("Demo", 2, 5)["show_id"]

    def status(self, label):
        return next(s["status"] for s in self.svc.seats(self.sid) if s["seat"] == label)

    def test_only_one_winner_under_contention(self):
        out = []

        def worker(i):
            try:
                self.svc.hold(self.sid, f"user{i}", ["A1"])
                out.append("ok")
            except Conflict:
                out.append("conflict")

        ts = [threading.Thread(target=worker, args=(i,)) for i in range(30)]
        [t.start() for t in ts]
        [t.join() for t in ts]
        self.assertEqual((out.count("ok"), out.count("conflict")), (1, 29))

    def test_hold_is_all_or_nothing(self):
        self.svc.hold(self.sid, "u1", ["A1"])
        with self.assertRaises(Conflict):
            self.svc.hold(self.sid, "u2", ["A1", "A2"])
        self.assertEqual(self.status("A2"), "AVAILABLE")

    def test_expired_hold_can_be_reclaimed(self):
        self.svc.hold(self.sid, "u1", ["A1"])
        self.t[0] += 61
        self.assertEqual(self.status("A1"), "AVAILABLE")
        self.svc.hold(self.sid, "u2", ["A1"])

    def test_cannot_book_without_or_after_hold(self):
        with self.assertRaises(Conflict):
            self.svc.book(self.sid, "u1", ["A1"], "k0")
        self.svc.hold(self.sid, "u1", ["A1"])
        self.t[0] += 61
        with self.assertRaises(Conflict):
            self.svc.book(self.sid, "u1", ["A1"], "k1")

    def test_other_user_cannot_book_my_hold(self):
        self.svc.hold(self.sid, "u1", ["A1"])
        with self.assertRaises(Conflict):
            self.svc.book(self.sid, "u2", ["A1"], "k2")

    def test_booking_is_idempotent(self):
        self.svc.hold(self.sid, "u1", ["A1", "A2"])
        a = self.svc.book(self.sid, "u1", ["A1", "A2"], "same-key")
        b = self.svc.book(self.sid, "u1", ["A1", "A2"], "same-key")
        self.assertEqual(a["booking_id"], b["booking_id"])
        self.assertTrue(b["replayed"])
        self.assertEqual(self.status("A1"), "BOOKED")


if __name__ == "__main__":
    unittest.main()
