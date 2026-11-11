import os, sqlite3, secrets
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, session, flash
from werkzeug.security import generate_password_hash, check_password_hash

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "voron_service.db")
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "schimba-cheia-secreta-inainte-de-publicare")

TIERS = {"STANDARD": 5, "SILVER": 10, "GOLD": 15}

def connect():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    with connect() as c:
        c.executescript("""
        CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, username TEXT UNIQUE, password TEXT);
        CREATE TABLE IF NOT EXISTS clients(id INTEGER PRIMARY KEY, name TEXT NOT NULL, phone TEXT, notes TEXT);
        CREATE TABLE IF NOT EXISTS cars(id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL, plate TEXT NOT NULL, make TEXT, model TEXT, year TEXT, vin TEXT, mileage TEXT, FOREIGN KEY(client_id) REFERENCES clients(id));
        CREATE TABLE IF NOT EXISTS jobs(id INTEGER PRIMARY KEY, car_id INTEGER NOT NULL, description TEXT NOT NULL, mechanic TEXT, status TEXT DEFAULT 'Nouă', labor REAL DEFAULT 0, parts REAL DEFAULT 0, paid REAL DEFAULT 0, created_at TEXT, FOREIGN KEY(car_id) REFERENCES cars(id));
        CREATE TABLE IF NOT EXISTS cards(id INTEGER PRIMARY KEY, client_id INTEGER NOT NULL, code TEXT UNIQUE, tier TEXT DEFAULT 'STANDARD', active INTEGER DEFAULT 1, created_at TEXT, FOREIGN KEY(client_id) REFERENCES clients(id));
        """)
        if not c.execute("SELECT id FROM users WHERE username='admin'").fetchone():
            c.execute("INSERT INTO users(username,password) VALUES(?,?)",
                      ("admin", generate_password_hash("admin123")))
        c.commit()

def login_required(fn):
    @wraps(fn)
    def wrapper(*a, **kw):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return fn(*a, **kw)
    return wrapper

@app.context_processor
def common():
    return {"tiers": TIERS}

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        with connect() as c:
            user = c.execute("SELECT * FROM users WHERE username=?", (request.form.get("username",""),)).fetchone()
        if user and check_password_hash(user["password"], request.form.get("password","")):
            session["user_id"] = user["id"]
            return redirect(url_for("dashboard"))
        flash("Date de autentificare incorecte.")
    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/")
@login_required
def dashboard():
    with connect() as c:
        stats = {
            "clients": c.execute("SELECT COUNT(*) FROM clients").fetchone()[0],
            "cars": c.execute("SELECT COUNT(*) FROM cars").fetchone()[0],
            "active_jobs": c.execute("SELECT COUNT(*) FROM jobs WHERE status NOT IN ('Finalizată','Anulată')").fetchone()[0],
            "income": c.execute("SELECT COALESCE(SUM(paid),0) FROM jobs").fetchone()[0],
        }
        recent = c.execute("""SELECT jobs.*, cars.plate, cars.make, cars.model, clients.name client_name
            FROM jobs JOIN cars ON cars.id=jobs.car_id JOIN clients ON clients.id=cars.client_id
            ORDER BY jobs.id DESC LIMIT 6""").fetchall()
    return render_template("dashboard.html", stats=stats, recent=recent)

@app.route("/clients", methods=["GET","POST"])
@login_required
def clients():
    if request.method == "POST":
        name = request.form.get("name","").strip()
        if not name:
            flash("Introdu numele clientului.")
        else:
            with connect() as c:
                c.execute("INSERT INTO clients(name,phone,notes) VALUES(?,?,?)",
                          (name, request.form.get("phone","").strip(), request.form.get("notes","").strip()))
                c.commit()
            flash("Client adăugat.")
            return redirect(url_for("clients"))
    with connect() as c:
        rows = c.execute("SELECT * FROM clients ORDER BY id DESC").fetchall()
    return render_template("clients.html", rows=rows)

@app.route("/cars", methods=["GET","POST"])
@login_required
def cars():
    if request.method == "POST":
        try:
            with connect() as c:
                c.execute("""INSERT INTO cars(client_id,plate,make,model,year,vin,mileage)
                    VALUES(?,?,?,?,?,?,?)""", (
                    int(request.form["client_id"]), request.form["plate"].strip().upper(),
                    request.form.get("make","").strip(), request.form.get("model","").strip(),
                    request.form.get("year","").strip(), request.form.get("vin","").strip(),
                    request.form.get("mileage","").strip()))
                c.commit()
            flash("Automobil adăugat.")
            return redirect(url_for("cars"))
        except Exception:
            flash("Verifică datele introduse.")
    with connect() as c:
        owners = c.execute("SELECT * FROM clients ORDER BY name").fetchall()
        rows = c.execute("""SELECT cars.*, clients.name client_name FROM cars
            JOIN clients ON clients.id=cars.client_id ORDER BY cars.id DESC""").fetchall()
    return render_template("cars.html", owners=owners, rows=rows)

@app.route("/jobs", methods=["GET","POST"])
@login_required
def jobs():
    if request.method == "POST":
        try:
            with connect() as c:
                c.execute("""INSERT INTO jobs(car_id,description,mechanic,status,labor,parts,paid,created_at)
                    VALUES(?,?,?,?,?,?,?,?)""", (
                    int(request.form["car_id"]), request.form["description"].strip(),
                    request.form.get("mechanic","").strip(), request.form.get("status","Nouă"),
                    float(request.form.get("labor") or 0), float(request.form.get("parts") or 0),
                    float(request.form.get("paid") or 0), datetime.now().strftime("%d.%m.%Y %H:%M")))
                c.commit()
            flash("Comandă de reparație creată.")
            return redirect(url_for("jobs"))
        except Exception:
            flash("Verifică datele introduse.")
    with connect() as c:
        cars = c.execute("""SELECT cars.*, clients.name client_name FROM cars
            JOIN clients ON clients.id=cars.client_id ORDER BY cars.plate""").fetchall()
        rows = c.execute("""SELECT jobs.*, cars.plate,cars.make,cars.model,clients.name client_name
            FROM jobs JOIN cars ON cars.id=jobs.car_id JOIN clients ON clients.id=cars.client_id
            ORDER BY jobs.id DESC""").fetchall()
    return render_template("jobs.html", cars=cars, rows=rows)

@app.route("/jobs/<int:job_id>/status", methods=["POST"])
@login_required
def job_status(job_id):
    status = request.form.get("status","Nouă")
    if status not in ["Nouă","În lucru","Așteaptă piese","Finalizată","Anulată"]:
        status = "Nouă"
    with connect() as c:
        c.execute("UPDATE jobs SET status=? WHERE id=?", (status,job_id))
        c.commit()
    return redirect(url_for("jobs"))

@app.route("/jobs/<int:job_id>/payment", methods=["POST"])
@login_required
def job_payment(job_id):
    try:
        amount = float(request.form.get("amount") or 0)
        if amount < 0: raise ValueError()
        with connect() as c:
            c.execute("UPDATE jobs SET paid=paid+? WHERE id=?", (amount,job_id))
            c.commit()
        flash("Plata a fost înregistrată.")
    except Exception:
        flash("Suma introdusă nu este validă.")
    return redirect(url_for("jobs"))

@app.route("/cards", methods=["GET","POST"])
@login_required
def cards():
    if request.method == "POST":
        client_id = request.form.get("client_id")
        tier = request.form.get("tier","STANDARD")
        if tier not in TIERS:
            tier = "STANDARD"
        code = "VORON-" + secrets.token_hex(3).upper()
        try:
            with connect() as c:
                c.execute("INSERT INTO cards(client_id,code,tier,active,created_at) VALUES(?,?,?,?,?)",
                          (int(client_id),code,tier,1,datetime.now().strftime("%d.%m.%Y")))
                c.commit()
            flash("Card creat: " + code)
            return redirect(url_for("cards"))
        except Exception:
            flash("Nu s-a putut crea cardul. Verifică clientul.")
    with connect() as c:
        owners = c.execute("SELECT * FROM clients ORDER BY name").fetchall()
        rows = c.execute("""SELECT cards.*,clients.name,clients.phone FROM cards
            JOIN clients ON clients.id=cards.client_id ORDER BY cards.id DESC""").fetchall()
    return render_template("cards.html", owners=owners, rows=rows)

@app.route("/cards/<int:card_id>/toggle", methods=["POST"])
@login_required
def card_toggle(card_id):
    with connect() as c:
        c.execute("UPDATE cards SET active=CASE active WHEN 1 THEN 0 ELSE 1 END WHERE id=?", (card_id,))
        c.commit()
    return redirect(url_for("cards"))

@app.route("/cards/<int:card_id>/print")
@login_required
def print_card(card_id):
    with connect() as c:
        card = c.execute("""SELECT cards.*,clients.name,clients.phone FROM cards
            JOIN clients ON clients.id=cards.client_id WHERE cards.id=?""",(card_id,)).fetchone()
    if not card: return "Cardul nu există.", 404
    return render_template("print_card.html", card=card)

if __name__ == "__main__":
    init_db()
    app.run(host="127.0.0.1", port=5000, debug=True)
