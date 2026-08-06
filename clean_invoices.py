import sqlite3
import os

db_ryu_path = os.path.join(os.path.dirname(__file__), "data", "ryukomik.db")
db = sqlite3.connect(db_ryu_path)

# Find all invoices with 0 chapters and 4000 amount
invoices = db.execute("SELECT id FROM dashboard_invoices WHERE chapter_count=0 AND total_amount=4000").fetchall()
for inv in invoices:
    inv_id = inv[0]
    db.execute("DELETE FROM payout_requests WHERE invoice_id=?", (inv_id,))
    db.execute("DELETE FROM dashboard_invoice_manual_bonus_items WHERE invoice_id=?", (inv_id,))
    db.execute("DELETE FROM dashboard_invoice_items WHERE invoice_id=?", (inv_id,))
    db.execute("DELETE FROM dashboard_invoices WHERE id=?", (inv_id,))

db.commit()
print(f"Deleted {len(invoices)} test invoices and their payouts.")

# Also delete any manual bonus that's 4000 amount for Void just in case
db.execute("DELETE FROM manual_bonuses WHERE amount=4000 AND reason='target'")
db.commit()
print("Cleaned up manual_bonuses.")
