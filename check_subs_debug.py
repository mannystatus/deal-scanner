from db import SessionLocal, init_db
from models import EmailSubscription

init_db()
with SessionLocal() as s:
    row = s.query(EmailSubscription).filter_by(email="mannydotco@gmail.com").first()
    if row:
        print("TOKEN:" + row.token)
    else:
        print("NOT FOUND")
