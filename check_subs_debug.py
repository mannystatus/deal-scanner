from db import SessionLocal, init_db
from models import EmailSubscription

init_db()
with SessionLocal() as s:
    rows = s.query(EmailSubscription).all()
    print(f"{len(rows)} total rows")
    for r in rows:
        print(r.id, r.email, "confirmed=" + str(r.confirmed), "categories=" + r.categories, r.created_at)
