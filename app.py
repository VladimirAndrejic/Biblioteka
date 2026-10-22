"""
Biblioteka — aplikacija za evidenciju knjiga, članova i pozajmica.
Projekat za predmet Razvoj softvera.
"""
from datetime import date, timedelta
from pathlib import Path
import csv
import io
import sqlite3
from functools import wraps

from flask import Flask, render_template, request, redirect, url_for, flash, session, abort, make_response

ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "biblioteka.db"

app = Flask(__name__)
app.config["SECRET_KEY"] = "promeniti-za-stvarnu-upotrebu"


def get_db():
    """Otvara vezu sa SQLite bazom."""
    db = sqlite3.connect(DB_PATH)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    return db


def table_columns(db, table):
    """Vraća nazive kolona u zadatoj tabeli."""
    return {row["name"] for row in db.execute(f"PRAGMA table_info({table})")}


def init_db():
    """Kreira tabele i dopunjava šemu ako je ostala baza iz ranije verzije."""
    with get_db() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS books (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            author TEXT NOT NULL,
            isbn TEXT UNIQUE,
            year INTEGER,
            total_copies INTEGER NOT NULL DEFAULT 1 CHECK(total_copies > 0),
            category TEXT NOT NULL DEFAULT 'Ostalo'
        );
        CREATE TABLE IF NOT EXISTS members (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            phone TEXT DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS loans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            book_id INTEGER NOT NULL REFERENCES books(id),
            member_id INTEGER NOT NULL REFERENCES members(id),
            loan_date TEXT NOT NULL,
            due_date TEXT,
            return_date TEXT,
            returned INTEGER NOT NULL DEFAULT 0 CHECK(returned IN (0,1))
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """)
        migrations = {
            "books": {"category": "TEXT NOT NULL DEFAULT 'Ostalo'"},
            "members": {"phone": "TEXT DEFAULT ''"},
            "loans": {"due_date": "TEXT", "return_date": "TEXT"},
        }
        for table, wanted in migrations.items():
            present = table_columns(db, table)
            for name, definition in wanted.items():
                if name not in present:
                    db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")
        db.execute("""UPDATE loans SET due_date=date(loan_date,'+14 days')
                      WHERE due_date IS NULL OR due_date=''""")
        if db.execute("SELECT COUNT(*) FROM books").fetchone()[0] == 0:
            db.executemany(
                "INSERT INTO books(title,author,isbn,year,total_copies,category) VALUES(?,?,?,?,?,?)",
                [
                    ("Na Drini ćuprija", "Ivo Andrić", "9780000000011", 1945, 3, "Roman"),
                    ("Prokleta avlija", "Ivo Andrić", "9780000000012", 1954, 2, "Roman"),
                    ("Mali princ", "Antoan de Sent Egziperi", "9780000000013", 1943, 4, "Klasik"),
                ],
            )
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('loan_days','14')")
        db.execute("INSERT OR IGNORE INTO settings(key,value) VALUES('library_name','Biblioteka')")
        db.execute("""UPDATE settings SET value='Biblioteka' WHERE key='library_name' AND value IN ('Biblioteka Plus Pro', 'Biblioteka Plus')""")


def setting(key, default):
    with get_db() as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return row["value"] if row else default


def login_required(view):
    """Dozvoljava pristup stranicama tek nakon prijave bibliotekara."""
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("logged_in"):
            return redirect(url_for("login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def available_copies(db, book_id):
    """Računa broj primeraka koji nisu trenutno izdati."""
    row = db.execute("""
        SELECT b.total_copies - COUNT(l.id) AS available
        FROM books b
        LEFT JOIN loans l ON l.book_id=b.id AND l.returned=0
        WHERE b.id=?
        GROUP BY b.id
    """, (book_id,)).fetchone()
    return row["available"] if row else 0


@app.context_processor
def common_values():
    return {"library_name": setting("library_name", "Biblioteka"),
            "today": date.today().isoformat()}


@app.route("/login", methods=["GET", "POST"])
def login():
    """Prijava za demo nalog bibliotekara."""
    if session.get("logged_in"):
        return redirect(url_for("index"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        # Demo nalog je namenjen isključivo lokalnom školskom projektu.
        if username == "bibliotekar" and password == "Biblioteka123!":
            session.clear()
            session["logged_in"] = True
            session["staff_name"] = "Bibliotekar"
            session.permanent = True
            flash("Uspešno ste se prijavili.", "success")
            return redirect(request.args.get("next") or url_for("index"))
        flash("Korisničko ime ili lozinka nisu ispravni.", "error")
    return render_template("login.html")


@app.post("/logout")
@login_required
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/")
@login_required
def index():
    today = date.today().isoformat()
    with get_db() as db:
        book_count = db.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        copies_count = db.execute("SELECT COALESCE(SUM(total_copies),0) FROM books").fetchone()[0]
        member_count = db.execute("SELECT COUNT(*) FROM members").fetchone()[0]
        active_count = db.execute("SELECT COUNT(*) FROM loans WHERE returned=0").fetchone()[0]
        overdue_count = db.execute(
            "SELECT COUNT(*) FROM loans WHERE returned=0 AND due_date < ?", (today,)
        ).fetchone()[0]
        recent = db.execute("""
            SELECT l.id,b.title,m.name,l.loan_date,l.due_date,
                   CASE WHEN l.due_date < ? THEN 1 ELSE 0 END AS overdue
            FROM loans l JOIN books b ON b.id=l.book_id
            JOIN members m ON m.id=l.member_id
            WHERE l.returned=0 ORDER BY l.due_date LIMIT 8
        """, (today,)).fetchall()
    return render_template("index.html", book_count=book_count, copies_count=copies_count,
                           member_count=member_count, active_count=active_count,
                           overdue_count=overdue_count, recent=recent)


@app.route("/books", methods=["GET", "POST"])
@login_required
def books_page():
    with get_db() as db:
        if request.method == "POST":
            title = request.form.get("title", "").strip()
            author = request.form.get("author", "").strip()
            isbn = request.form.get("isbn", "").strip() or None
            category = request.form.get("category", "Ostalo").strip() or "Ostalo"
            year_text = request.form.get("year", "").strip()
            copies_text = request.form.get("total_copies", "1").strip()
            if not title or not author:
                flash("Unesite naslov i autora.", "error")
            else:
                try:
                    year = int(year_text) if year_text else None
                    copies = int(copies_text)
                    if copies < 1 or (year is not None and not 1 <= year <= date.today().year):
                        raise ValueError
                    db.execute("""INSERT INTO books(title,author,isbn,year,total_copies,category)
                                  VALUES(?,?,?,?,?,?)""",
                               (title,author,isbn,year,copies,category))
                    db.commit()
                    flash("Knjiga je dodata.", "success")
                    return redirect(url_for("books_page"))
                except ValueError:
                    flash("Proverite godinu izdanja i broj primeraka.", "error")
                except sqlite3.IntegrityError:
                    flash("ISBN već postoji u evidenciji.", "error")
        q = request.args.get("q", "").strip()
        category_filter = request.args.get("category", "").strip()
        sql = """SELECT b.*,
                 b.total_copies-(SELECT COUNT(*) FROM loans l WHERE l.book_id=b.id AND l.returned=0) AS available
                 FROM books b WHERE (b.title LIKE ? OR b.author LIKE ? OR COALESCE(b.isbn,'') LIKE ?)"""
        args = [f"%{q}%", f"%{q}%", f"%{q}%"]
        if category_filter:
            sql += " AND b.category=?"
            args.append(category_filter)
        sql += " ORDER BY b.title"
        books = db.execute(sql, args).fetchall()
        categories = db.execute("SELECT DISTINCT category FROM books ORDER BY category").fetchall()
    return render_template("books.html", books=books, q=q, categories=categories,
                           selected_category=category_filter)


@app.post("/books/<int:book_id>/delete")
@login_required
def delete_book(book_id):
    with get_db() as db:
        if not db.execute("SELECT id FROM books WHERE id=?", (book_id,)).fetchone():
            abort(404)
        if db.execute("SELECT 1 FROM loans WHERE book_id=? LIMIT 1", (book_id,)).fetchone():
            flash("Knjiga se ne može obrisati jer postoji istorija pozajmica.", "error")
        else:
            db.execute("DELETE FROM books WHERE id=?", (book_id,))
            db.commit()
            flash("Knjiga je obrisana.", "success")
    return redirect(url_for("books_page"))


@app.route("/members", methods=["GET", "POST"])
@login_required
def members_page():
    with get_db() as db:
        if request.method == "POST":
            name = request.form.get("name", "").strip()
            email = request.form.get("email", "").strip().lower()
            phone = request.form.get("phone", "").strip()
            if not name or not email or "@" not in email or "." not in email.split("@")[-1]:
                flash("Unesite ime i ispravnu imejl adresu.", "error")
            else:
                try:
                    db.execute("INSERT INTO members(name,email,phone) VALUES(?,?,?)",
                               (name,email,phone))
                    db.commit()
                    flash("Član je dodat.", "success")
                    return redirect(url_for("members_page"))
                except sqlite3.IntegrityError:
                    flash("Ova imejl adresa već postoji.", "error")
        q = request.args.get("q", "").strip()
        members = db.execute("""
            SELECT m.*,(SELECT COUNT(*) FROM loans l
            WHERE l.member_id=m.id AND l.returned=0) AS active_loans
            FROM members m WHERE m.name LIKE ? OR m.email LIKE ? ORDER BY m.name
        """, (f"%{q}%", f"%{q}%")).fetchall()
    return render_template("members.html", members=members, q=q)


@app.post("/members/<int:member_id>/delete")
@login_required
def delete_member(member_id):
    with get_db() as db:
        if not db.execute("SELECT id FROM members WHERE id=?", (member_id,)).fetchone():
            abort(404)
        if db.execute("SELECT 1 FROM loans WHERE member_id=? LIMIT 1", (member_id,)).fetchone():
            flash("Član se ne može obrisati jer postoji istorija pozajmica.", "error")
        else:
            db.execute("DELETE FROM members WHERE id=?", (member_id,))
            db.commit()
            flash("Član je obrisan.", "success")
    return redirect(url_for("members_page"))


@app.route("/loans", methods=["GET", "POST"])
@login_required
def loans_page():
    with get_db() as db:
        if request.method == "POST":
            try:
                book_id = int(request.form.get("book_id", ""))
                member_id = int(request.form.get("member_id", ""))
                due_raw = request.form.get("due_date", "")
                loan_days = int(setting("loan_days", "14"))
                due = date.fromisoformat(due_raw) if due_raw else date.today()+timedelta(days=loan_days)
                if due < date.today():
                    flash("Rok vraćanja ne može biti u prošlosti.", "error")
                elif not db.execute("SELECT id FROM books WHERE id=?", (book_id,)).fetchone():
                    flash("Izabrana knjiga ne postoji.", "error")
                elif not db.execute("SELECT id FROM members WHERE id=?", (member_id,)).fetchone():
                    flash("Izabrani član ne postoji.", "error")
                elif available_copies(db, book_id) < 1:
                    flash("Nema dostupnih primeraka izabrane knjige.", "error")
                else:
                    db.execute("INSERT INTO loans(book_id,member_id,loan_date,due_date) VALUES(?,?,?,?)",
                               (book_id,member_id,date.today().isoformat(),due.isoformat()))
                    db.commit()
                    flash("Knjiga je izdata.", "success")
                    return redirect(url_for("loans_page"))
            except (ValueError, TypeError):
                flash("Izaberite knjigu, člana i ispravan datum.", "error")
        books = db.execute("SELECT id,title FROM books ORDER BY title").fetchall()
        members = db.execute("SELECT id,name FROM members ORDER BY name").fetchall()
        q = request.args.get("q", "").strip()
        status = request.args.get("status", "all")
        sql = """SELECT l.*,b.title,m.name,
                 CASE WHEN l.returned=0 AND l.due_date < ? THEN 1 ELSE 0 END AS overdue
                 FROM loans l JOIN books b ON b.id=l.book_id
                 JOIN members m ON m.id=l.member_id
                 WHERE (b.title LIKE ? OR m.name LIKE ?)"""
        args = [date.today().isoformat(), f"%{q}%", f"%{q}%"]
        if status == "active":
            sql += " AND l.returned=0"
        elif status == "returned":
            sql += " AND l.returned=1"
        elif status == "overdue":
            sql += " AND l.returned=0 AND l.due_date < ?"
            args.append(date.today().isoformat())
        sql += " ORDER BY l.id DESC"
        loans = db.execute(sql, args).fetchall()
    return render_template("loans.html", books=books, members=members, loans=loans,
                           q=q, selected_status=status,
                           default_due=(date.today()+timedelta(days=int(setting("loan_days","14")))).isoformat())


@app.post("/loans/<int:loan_id>/return")
@login_required
def return_book(loan_id):
    with get_db() as db:
        loan = db.execute("SELECT returned FROM loans WHERE id=?", (loan_id,)).fetchone()
        if not loan:
            abort(404)
        if loan["returned"]:
            flash("Knjiga je već vraćena.", "error")
        else:
            db.execute("UPDATE loans SET returned=1,return_date=? WHERE id=?",
                       (date.today().isoformat(), loan_id))
            db.commit()
            flash("Vraćanje knjige je evidentirano.", "success")
    return redirect(url_for("loans_page"))


@app.route("/reports")
@login_required
def reports():
    today = date.today().isoformat()
    with get_db() as db:
        summary = db.execute("""
            SELECT COUNT(*) AS total,
              SUM(CASE WHEN returned=0 THEN 1 ELSE 0 END) AS active,
              SUM(CASE WHEN returned=1 THEN 1 ELSE 0 END) AS returned,
              SUM(CASE WHEN returned=0 AND due_date < ? THEN 1 ELSE 0 END) AS overdue
            FROM loans
        """, (today,)).fetchone()
        popular = db.execute("""
            SELECT b.title,COUNT(l.id) AS loan_count FROM books b
            LEFT JOIN loans l ON b.id=l.book_id GROUP BY b.id
            ORDER BY loan_count DESC,b.title LIMIT 10
        """).fetchall()
        monthly = db.execute("""SELECT substr(loan_date,1,7) AS month,COUNT(*) AS count
                                FROM loans GROUP BY substr(loan_date,1,7)
                                ORDER BY month DESC LIMIT 12""").fetchall()
    return render_template("reports.html", summary=summary, popular=popular, monthly=list(reversed(monthly)))


@app.route("/reports/export.csv")
@login_required
def export_csv():
    """Pravi CSV izveštaj koji može da se otvori u programu Excel."""
    with get_db() as db:
        rows = db.execute("""
            SELECT b.title,m.name,l.loan_date,l.due_date,l.return_date,
                   CASE WHEN l.returned=1 THEN 'Vraćena' ELSE 'Izdato' END AS status
            FROM loans l JOIN books b ON b.id=l.book_id JOIN members m ON m.id=l.member_id
            ORDER BY l.id DESC
        """).fetchall()
    output = io.StringIO()
    writer = csv.writer(output, delimiter=";")
    writer.writerow(["Knjiga","Član","Datum izdavanja","Rok vraćanja","Datum vraćanja","Status"])
    writer.writerows([tuple(row) for row in rows])
    response = make_response("\\ufeff" + output.getvalue())
    response.headers["Content-Type"] = "text/csv; charset=utf-8"
    response.headers["Content-Disposition"] = "attachment; filename=pozajmice.csv"
    return response


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings_page():
    with get_db() as db:
        if request.method == "POST":
            name = request.form.get("library_name", "").strip()
            try:
                days = int(request.form.get("loan_days", "14"))
                if not name or not 1 <= days <= 90:
                    raise ValueError
                db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('library_name',?)", (name,))
                db.execute("INSERT OR REPLACE INTO settings(key,value) VALUES('loan_days',?)", (str(days),))
                db.commit()
                flash("Podešavanja su sačuvana.", "success")
                return redirect(url_for("settings_page"))
            except ValueError:
                flash("Unesite naziv i rok između 1 i 90 dana.", "error")
    return render_template("settings.html", library_name=setting("library_name","Biblioteka"),
                           loan_days=setting("loan_days","14"))


@app.route("/help")
@login_required
def help_page():
    return render_template("help.html")


@app.errorhandler(404)
def page_not_found(_error):
    return render_template("error.html", code=404, message="Tražena stranica nije pronađena."), 404


@app.errorhandler(500)
def server_error(_error):
    return render_template("error.html", code=500, message="Došlo je do greške. Proverite podatke i terminal."), 500


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
