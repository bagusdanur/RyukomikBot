import sqlite3
import os

wrong_id = '296524083951042560'
wrong_id_int = int(wrong_id)
correct_id = '296524083951042570'

db_ryu_path = os.path.join(os.path.dirname(__file__), "data", "ryukomik.db")
if os.path.exists(db_ryu_path):
    db2 = sqlite3.connect(db_ryu_path)
    # ryukomik.db tables
    db2.execute("UPDATE assignments SET staff_id=? WHERE staff_id=? OR staff_id=?", (correct_id, wrong_id, wrong_id_int))
    db2.execute("UPDATE dashboard_staff_cache SET staff_id=? WHERE staff_id=? OR staff_id=?", (correct_id, wrong_id, wrong_id_int))
    db2.execute("UPDATE manual_bonuses SET staff_id=? WHERE staff_id=? OR staff_id=?", (correct_id, wrong_id, wrong_id_int))
    db2.execute("UPDATE performance_bonuses SET staff_id=? WHERE staff_id=? OR staff_id=?", (correct_id, wrong_id, wrong_id_int))
    db2.execute("UPDATE assignment_submissions SET staff_id=? WHERE staff_id=? OR staff_id=?", (correct_id, wrong_id, wrong_id_int))
    db2.execute("UPDATE dashboard_invoices SET staff_id=? WHERE staff_id=? OR staff_id=?", (correct_id, wrong_id, wrong_id_int))
    rows = db2.execute("SELECT id, invoice_number FROM dashboard_invoices WHERE invoice_number LIKE ?", (f"%{wrong_id}%",)).fetchall()
    for r in rows:
        new_number = r[1].replace(wrong_id, correct_id)
        db2.execute("UPDATE dashboard_invoices SET invoice_number=? WHERE id=?", (new_number, r[0]))

    db2.commit()
    print("ryukomik.db updated")
