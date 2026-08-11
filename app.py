import calendar
import os
import re
from datetime import datetime, date, timedelta
from decimal import Decimal, InvalidOperation
from functools import wraps
from urllib.parse import quote

from flask import Flask, flash, redirect, render_template, request, session, url_for, Response
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import or_, func
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-jvs-secret")
db_url = os.getenv("DATABASE_URL", "sqlite:///jvs.db")
if db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql+psycopg://", 1)
elif db_url.startswith("postgresql://") and "+psycopg" not in db_url:
    db_url = db_url.replace("postgresql://", "postgresql+psycopg://", 1)
app.config["SQLALCHEMY_DATABASE_URI"] = db_url
app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
db = SQLAlchemy(app)


def money(v):
    try:
        if isinstance(v, str):
            v = v.strip().replace("R$", "").replace(" ", "")
            if "," in v and "." in v:
                v = v.replace(".", "").replace(",", ".")
            elif "," in v:
                v = v.replace(",", ".")
        return Decimal(str(v or 0)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return Decimal("0.00")


def parse_date(value, default=None):
    if not value:
        return default
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return default


def add_months(d, months):
    if not d or not months:
        return d
    months = int(months)
    new_month_index = d.month - 1 + months
    year = d.year + new_month_index // 12
    month = new_month_index % 12 + 1
    day = min(d.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def whatsapp_phone(phone):
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) in (10, 11):
        digits = "55" + digits
    return digits


def month_bounds(month_text):
    try:
        first = datetime.strptime(month_text, "%Y-%m").date().replace(day=1)
    except (ValueError, TypeError):
        first = date.today().replace(day=1)
    if first.month == 12:
        next_first = date(first.year + 1, 1, 1)
    else:
        next_first = date(first.year, first.month + 1, 1)
    return first, next_first


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(160), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)


class Company(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), default="JVS Mecânica")
    phone = db.Column(db.String(60), default="32999599434")
    instagram = db.Column(db.String(120), default="@mecanica_jvs")
    pix_key = db.Column(db.String(180), default="")
    address = db.Column(db.String(255), default="")


class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(180), nullable=False)
    phone = db.Column(db.String(60), default="")
    cpf_cnpj = db.Column(db.String(40), default="")
    email = db.Column(db.String(160), default="")
    address = db.Column(db.String(255), default="")
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    vehicles = db.relationship("Vehicle", backref="client", cascade="all, delete-orphan")


class Vehicle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    plate = db.Column(db.String(20), default="")
    brand = db.Column(db.String(80), default="")
    model = db.Column(db.String(100), nullable=False)
    year = db.Column(db.String(20), default="")
    color = db.Column(db.String(40), default="")
    km = db.Column(db.Integer, nullable=True)
    notes = db.Column(db.Text, default="")

    @property
    def label(self):
        p = f" • {self.plate}" if self.plate else ""
        return f"{self.brand} {self.model}{p}".strip()


class InventoryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(60), default="")
    name = db.Column(db.String(180), nullable=False)
    unit = db.Column(db.String(20), default="UN")
    qty = db.Column(db.Numeric(12, 3), default=0)
    min_qty = db.Column(db.Numeric(12, 3), default=0)
    cost = db.Column(db.Numeric(12, 2), default=0)
    price = db.Column(db.Numeric(12, 2), default=0)


class Budget(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=True)
    status = db.Column(db.String(30), default="Pendente")
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    client = db.relationship("Client")
    vehicle = db.relationship("Vehicle")
    lines = db.relationship("BudgetLine", backref="budget", cascade="all, delete-orphan")

    @property
    def total(self):
        return sum((money(x.qty) * money(x.unit_price) for x in self.lines), Decimal("0.00"))


class BudgetLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    budget_id = db.Column(db.Integer, db.ForeignKey("budget.id"), nullable=False)
    kind = db.Column(db.String(20), default="Serviço")
    description = db.Column(db.String(255), nullable=False)
    qty = db.Column(db.Numeric(12, 3), default=1)
    unit_price = db.Column(db.Numeric(12, 2), default=0)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey("inventory_item.id"), nullable=True)
    inventory_item = db.relationship("InventoryItem")


class ServiceOrder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=True)
    status = db.Column(db.String(30), default="Aberta")
    payment_status = db.Column(db.String(30), default="A receber")
    problem = db.Column(db.Text, default="")
    diagnosis = db.Column(db.Text, default="")
    notes = db.Column(db.Text, default="")
    stock_applied = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    finished_at = db.Column(db.DateTime, nullable=True)
    client = db.relationship("Client")
    vehicle = db.relationship("Vehicle")
    lines = db.relationship("ServiceOrderLine", backref="order", cascade="all, delete-orphan")

    @property
    def total(self):
        return sum((money(x.qty) * money(x.unit_price) for x in self.lines), Decimal("0.00"))


class ServiceOrderLine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.Integer, db.ForeignKey("service_order.id"), nullable=False)
    kind = db.Column(db.String(20), default="Serviço")
    description = db.Column(db.String(255), nullable=False)
    qty = db.Column(db.Numeric(12, 3), default=1)
    unit_price = db.Column(db.Numeric(12, 2), default=0)
    inventory_item_id = db.Column(db.Integer, db.ForeignKey("inventory_item.id"), nullable=True)
    inventory_item = db.relationship("InventoryItem")


class FinanceEntry(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    kind = db.Column(db.String(20), nullable=False)  # Receita/Despesa
    description = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    due_date = db.Column(db.Date, default=date.today)
    paid = db.Column(db.Boolean, default=True)
    order_id = db.Column(db.Integer, db.ForeignKey("service_order.id"), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class Receivable(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey("client.id"), nullable=False)
    order_id = db.Column(db.Integer, db.ForeignKey("service_order.id"), nullable=True, unique=True)
    description = db.Column(db.String(255), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    paid_amount = db.Column(db.Numeric(12, 2), default=0)
    due_date = db.Column(db.Date, default=date.today)
    status = db.Column(db.String(30), default="Pendente")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    client = db.relationship("Client")
    order = db.relationship("ServiceOrder")
    payments = db.relationship("ReceivablePayment", backref="receivable", cascade="all, delete-orphan")

    @property
    def balance(self):
        return max(Decimal("0.00"), money(self.amount) - money(self.paid_amount))


class ReceivablePayment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    receivable_id = db.Column(db.Integer, db.ForeignKey("receivable.id"), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    paid_at = db.Column(db.Date, default=date.today)
    method = db.Column(db.String(50), default="PIX")
    note = db.Column(db.String(255), default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class MaintenanceReminder(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    vehicle_id = db.Column(db.Integer, db.ForeignKey("vehicle.id"), nullable=False)
    kind = db.Column(db.String(80), nullable=False)
    description = db.Column(db.String(255), default="")
    last_km = db.Column(db.Integer, nullable=True)
    due_km = db.Column(db.Integer, nullable=True)
    last_date = db.Column(db.Date, nullable=True)
    due_date = db.Column(db.Date, nullable=True)
    active = db.Column(db.Boolean, default=True)
    notes = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    vehicle = db.relationship("Vehicle")

    @property
    def state(self):
        if not self.active:
            return "Concluído"
        today = date.today()
        km_now = self.vehicle.km if self.vehicle else None
        overdue_date = self.due_date and self.due_date < today
        overdue_km = self.due_km is not None and km_now is not None and km_now >= self.due_km
        if overdue_date or overdue_km:
            return "Vencido"
        near_date = self.due_date and self.due_date <= today + timedelta(days=30)
        near_km = self.due_km is not None and km_now is not None and self.due_km - km_now <= 1000
        if near_date or near_km:
            return "Próximo"
        return "Em dia"


# ---------- inicialização ----------
def init_db():
    db.create_all()
    if not User.query.first():
        email = os.getenv("ADMIN_EMAIL", "admin@jvs.local").strip().lower()
        password = os.getenv("ADMIN_PASSWORD", "admin123")
        db.session.add(User(email=email, password_hash=generate_password_hash(password)))
    if not Company.query.first():
        db.session.add(Company())
    db.session.commit()


@app.before_request
def ensure_db():
    if not getattr(app, "_jvs_ready", False):
        init_db()
        app._jvs_ready = True


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


@app.template_filter("brl")
def brl(v):
    n = float(v or 0)
    s = f"{n:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {s}"


@app.template_filter("dt")
def dt(v):
    if not v:
        return "-"
    return v.strftime("%d/%m/%Y %H:%M") if isinstance(v, datetime) else v.strftime("%d/%m/%Y")


# ---------- autenticação ----------
@app.route("/healthz")
def healthz():
    return {"status": "ok", "service": "jvs-mecanica"}, 200


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = User.query.filter_by(email=request.form.get("email", "").strip().lower()).first()
        if user and check_password_hash(user.password_hash, request.form.get("password", "")):
            session["user_id"] = user.id
            return redirect(url_for("dashboard"))
        flash("E-mail ou senha inválidos.", "danger")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ---------- dashboard ----------
@app.route("/")
@login_required
def dashboard():
    today = date.today()
    month_start = today.replace(day=1)
    revenues = db.session.query(func.coalesce(func.sum(FinanceEntry.amount), 0)).filter(
        FinanceEntry.kind == "Receita", FinanceEntry.paid.is_(True), FinanceEntry.due_date >= month_start
    ).scalar()
    expenses = db.session.query(func.coalesce(func.sum(FinanceEntry.amount), 0)).filter(
        FinanceEntry.kind == "Despesa", FinanceEntry.paid.is_(True), FinanceEntry.due_date >= month_start
    ).scalar()
    receivables = Receivable.query.filter(Receivable.status != "Pago").all()
    receive_total = sum((r.balance for r in receivables), Decimal("0.00"))
    overdue_receivables = sum(1 for r in receivables if r.due_date and r.due_date < today)
    low_stock = InventoryItem.query.filter(InventoryItem.qty <= InventoryItem.min_qty).order_by(InventoryItem.name).limit(8).all()
    orders = ServiceOrder.query.order_by(ServiceOrder.created_at.desc()).limit(8).all()
    reminders = [r for r in MaintenanceReminder.query.filter_by(active=True).all() if r.state in ("Vencido", "Próximo")]
    reminders.sort(key=lambda r: (0 if r.state == "Vencido" else 1, r.due_date or date.max, r.due_km or 10**12))
    return render_template(
        "dashboard.html",
        clients_count=Client.query.count(),
        vehicles_count=Vehicle.query.count(),
        open_orders=ServiceOrder.query.filter(ServiceOrder.status != "Concluída").count(),
        revenues=revenues,
        expenses=expenses,
        balance=money(revenues) - money(expenses),
        receive_total=receive_total,
        overdue_receivables=overdue_receivables,
        low_stock=low_stock,
        orders=orders,
        reminders=reminders[:8],
    )


# ---------- clientes ----------
@app.route("/clientes", methods=["GET", "POST"])
@login_required
def clients():
    if request.method == "POST":
        c = Client(
            name=request.form["name"].strip(),
            phone=request.form.get("phone", "").strip(),
            cpf_cnpj=request.form.get("cpf_cnpj", "").strip(),
            email=request.form.get("email", "").strip(),
            address=request.form.get("address", "").strip(),
            notes=request.form.get("notes", "").strip(),
        )
        db.session.add(c)
        db.session.commit()
        flash("Cliente cadastrado.", "success")
        return redirect(url_for("clients"))
    q = request.args.get("q", "").strip()
    query = Client.query
    if q:
        query = query.filter(or_(Client.name.ilike(f"%{q}%"), Client.phone.ilike(f"%{q}%"), Client.cpf_cnpj.ilike(f"%{q}%")))
    return render_template("clients.html", clients=query.order_by(Client.name).all(), q=q)


@app.route("/clientes/<int:id>/editar", methods=["GET", "POST"])
@login_required
def client_edit(id):
    c = Client.query.get_or_404(id)
    if request.method == "POST":
        for field in ["name", "phone", "cpf_cnpj", "email", "address", "notes"]:
            setattr(c, field, request.form.get(field, "").strip())
        db.session.commit()
        flash("Cliente atualizado.", "success")
        return redirect(url_for("clients"))
    return render_template("client_edit.html", c=c)


# ---------- veículos e histórico ----------
@app.route("/veiculos", methods=["GET", "POST"])
@login_required
def vehicles():
    if request.method == "POST":
        v = Vehicle(
            client_id=int(request.form["client_id"]),
            plate=request.form.get("plate", "").upper().strip(),
            brand=request.form.get("brand", "").strip(),
            model=request.form["model"].strip(),
            year=request.form.get("year", "").strip(),
            color=request.form.get("color", "").strip(),
            km=int(request.form["km"]) if request.form.get("km") else None,
            notes=request.form.get("notes", "").strip(),
        )
        db.session.add(v)
        db.session.commit()
        flash("Veículo cadastrado.", "success")
        return redirect(url_for("vehicles"))
    q = request.args.get("q", "").strip()
    query = Vehicle.query.join(Client)
    if q:
        query = query.filter(or_(Vehicle.plate.ilike(f"%{q}%"), Vehicle.model.ilike(f"%{q}%"), Client.name.ilike(f"%{q}%")))
    return render_template("vehicles.html", vehicles=query.order_by(Vehicle.id.desc()).all(), clients=Client.query.order_by(Client.name).all(), q=q)


@app.route("/veiculos/<int:id>")
@login_required
def vehicle_detail(id):
    v = Vehicle.query.get_or_404(id)
    orders = ServiceOrder.query.filter_by(vehicle_id=id).order_by(ServiceOrder.created_at.desc()).all()
    budgets = Budget.query.filter_by(vehicle_id=id).order_by(Budget.created_at.desc()).all()
    reminders = MaintenanceReminder.query.filter_by(vehicle_id=id).order_by(MaintenanceReminder.active.desc(), MaintenanceReminder.created_at.desc()).all()
    total_spent = sum((o.total for o in orders if o.payment_status == "Pago"), Decimal("0.00"))
    return render_template("vehicle_detail.html", v=v, orders=orders, budgets=budgets, reminders=reminders, total_spent=total_spent)


@app.route("/veiculos/<int:id>/km", methods=["POST"])
@login_required
def vehicle_km(id):
    v = Vehicle.query.get_or_404(id)
    raw = request.form.get("km", "").strip()
    if not raw:
        flash("Informe o KM atual.", "danger")
    else:
        new_km = int(raw)
        if v.km is not None and new_km < v.km:
            flash("O KM informado é menor que o KM atual. Verifique o valor.", "danger")
        else:
            v.km = new_km
            db.session.commit()
            flash("KM atualizado.", "success")
    return redirect(url_for("vehicle_detail", id=id))


@app.route("/veiculos/<int:id>/lembrete", methods=["POST"])
@login_required
def reminder_add(id):
    v = Vehicle.query.get_or_404(id)
    kind = request.form.get("kind", "Troca de óleo").strip()
    last_km = int(request.form["last_km"]) if request.form.get("last_km") else v.km
    interval_km = int(request.form["interval_km"]) if request.form.get("interval_km") else None
    last_date = parse_date(request.form.get("last_date"), date.today())
    interval_months = int(request.form["interval_months"]) if request.form.get("interval_months") else None
    due_km = (last_km + interval_km) if last_km is not None and interval_km else None
    due_date = add_months(last_date, interval_months) if interval_months else None
    r = MaintenanceReminder(
        vehicle_id=id,
        kind=kind,
        description=request.form.get("description", "").strip(),
        last_km=last_km,
        due_km=due_km,
        last_date=last_date,
        due_date=due_date,
        notes=request.form.get("notes", "").strip(),
    )
    db.session.add(r)
    db.session.commit()
    flash("Lembrete de manutenção criado.", "success")
    return redirect(url_for("vehicle_detail", id=id))


@app.route("/lembretes/<int:id>/concluir", methods=["POST"])
@login_required
def reminder_done(id):
    r = MaintenanceReminder.query.get_or_404(id)
    r.active = False
    db.session.commit()
    flash("Lembrete marcado como concluído.", "success")
    return redirect(url_for("vehicle_detail", id=r.vehicle_id))


# ---------- estoque ----------
@app.route("/estoque", methods=["GET", "POST"])
@login_required
def inventory():
    if request.method == "POST":
        item = InventoryItem(
            code=request.form.get("code", "").strip(),
            name=request.form["name"].strip(),
            unit=request.form.get("unit", "UN").strip().upper(),
            qty=money(request.form.get("qty", 0)),
            min_qty=money(request.form.get("min_qty", 0)),
            cost=money(request.form.get("cost", 0)),
            price=money(request.form.get("price", 0)),
        )
        db.session.add(item)
        db.session.commit()
        flash("Item adicionado ao estoque.", "success")
        return redirect(url_for("inventory"))
    q = request.args.get("q", "").strip()
    query = InventoryItem.query
    if q:
        query = query.filter(or_(InventoryItem.name.ilike(f"%{q}%"), InventoryItem.code.ilike(f"%{q}%")))
    return render_template("inventory.html", items=query.order_by(InventoryItem.name).all(), q=q)


@app.route("/estoque/<int:id>/editar", methods=["GET", "POST"])
@login_required
def inventory_edit(id):
    item = InventoryItem.query.get_or_404(id)
    if request.method == "POST":
        item.code = request.form.get("code", "").strip()
        item.name = request.form["name"].strip()
        item.unit = request.form.get("unit", "UN").strip().upper()
        item.qty = money(request.form.get("qty", 0))
        item.min_qty = money(request.form.get("min_qty", 0))
        item.cost = money(request.form.get("cost", 0))
        item.price = money(request.form.get("price", 0))
        db.session.commit()
        flash("Estoque atualizado.", "success")
        return redirect(url_for("inventory"))
    return render_template("inventory_edit.html", item=item)


# ---------- orçamentos ----------
@app.route("/orcamentos", methods=["GET", "POST"])
@login_required
def budgets():
    if request.method == "POST":
        b = Budget(
            client_id=int(request.form["client_id"]),
            vehicle_id=int(request.form["vehicle_id"]) if request.form.get("vehicle_id") else None,
            notes=request.form.get("notes", "").strip(),
        )
        db.session.add(b)
        db.session.commit()
        return redirect(url_for("budget_detail", id=b.id))
    return render_template(
        "budgets.html",
        budgets=Budget.query.order_by(Budget.id.desc()).all(),
        clients=Client.query.order_by(Client.name).all(),
        vehicles=Vehicle.query.order_by(Vehicle.id.desc()).all(),
    )


@app.route("/orcamentos/<int:id>")
@login_required
def budget_detail(id):
    b = Budget.query.get_or_404(id)
    return render_template("budget_detail.html", b=b, items=InventoryItem.query.order_by(InventoryItem.name).all())


@app.route("/orcamentos/<int:id>/item", methods=["POST"])
@login_required
def budget_add_line(id):
    b = Budget.query.get_or_404(id)
    inv_id = int(request.form["inventory_item_id"]) if request.form.get("inventory_item_id") else None
    inv = InventoryItem.query.get(inv_id) if inv_id else None
    desc = request.form.get("description", "").strip() or (inv.name if inv else "")
    if not desc:
        flash("Informe a descrição.", "danger")
        return redirect(url_for("budget_detail", id=id))
    line = BudgetLine(
        budget_id=id,
        kind=request.form.get("kind", "Serviço"),
        description=desc,
        qty=money(request.form.get("qty", 1)),
        unit_price=money(request.form.get("unit_price") or (inv.price if inv else 0)),
        inventory_item_id=inv_id,
    )
    db.session.add(line)
    db.session.commit()
    return redirect(url_for("budget_detail", id=id))


@app.route("/orcamentos/<int:id>/aprovar", methods=["POST"])
@login_required
def budget_approve(id):
    b = Budget.query.get_or_404(id)
    order = ServiceOrder(client_id=b.client_id, vehicle_id=b.vehicle_id, problem=f"Orçamento #{b.id} aprovado", notes=b.notes)
    db.session.add(order)
    db.session.flush()
    for l in b.lines:
        db.session.add(ServiceOrderLine(order_id=order.id, kind=l.kind, description=l.description, qty=l.qty, unit_price=l.unit_price, inventory_item_id=l.inventory_item_id))
    b.status = "Aprovado"
    db.session.commit()
    flash(f"Orçamento aprovado e convertido na OS #{order.id}.", "success")
    return redirect(url_for("order_detail", id=order.id))


@app.route("/orcamentos/<int:id>/imprimir")
@login_required
def budget_print(id):
    return render_template("print_doc.html", doc=Budget.query.get_or_404(id), kind="ORÇAMENTO", company=Company.query.first())


@app.route("/orcamentos/<int:id>/whatsapp")
@login_required
def budget_whatsapp(id):
    b = Budget.query.get_or_404(id)
    phone = whatsapp_phone(b.client.phone)
    if not phone:
        flash("Cadastre o WhatsApp/telefone do cliente primeiro.", "danger")
        return redirect(url_for("budget_detail", id=id))
    vehicle = b.vehicle.label if b.vehicle else "veículo não informado"
    msg = f"Olá, {b.client.name}! Aqui é da JVS Mecânica. Seu orçamento #{b.id} para {vehicle} ficou em {brl(b.total)}. Status: {b.status}. Qualquer dúvida, estamos à disposição."
    return redirect(f"https://wa.me/{phone}?text={quote(msg)}")


# ---------- ordens de serviço ----------
@app.route("/os", methods=["GET", "POST"])
@login_required
def orders():
    if request.method == "POST":
        o = ServiceOrder(
            client_id=int(request.form["client_id"]),
            vehicle_id=int(request.form["vehicle_id"]) if request.form.get("vehicle_id") else None,
            problem=request.form.get("problem", "").strip(),
            diagnosis=request.form.get("diagnosis", "").strip(),
            notes=request.form.get("notes", "").strip(),
        )
        db.session.add(o)
        db.session.commit()
        return redirect(url_for("order_detail", id=o.id))
    return render_template(
        "orders.html",
        orders=ServiceOrder.query.order_by(ServiceOrder.id.desc()).all(),
        clients=Client.query.order_by(Client.name).all(),
        vehicles=Vehicle.query.order_by(Vehicle.id.desc()).all(),
    )


@app.route("/os/<int:id>")
@login_required
def order_detail(id):
    o = ServiceOrder.query.get_or_404(id)
    receivable = Receivable.query.filter_by(order_id=id).first()
    return render_template("order_detail.html", o=o, items=InventoryItem.query.order_by(InventoryItem.name).all(), receivable=receivable)


@app.route("/os/<int:id>/item", methods=["POST"])
@login_required
def order_add_line(id):
    o = ServiceOrder.query.get_or_404(id)
    inv_id = int(request.form["inventory_item_id"]) if request.form.get("inventory_item_id") else None
    inv = InventoryItem.query.get(inv_id) if inv_id else None
    desc = request.form.get("description", "").strip() or (inv.name if inv else "")
    if not desc:
        flash("Informe a descrição.", "danger")
        return redirect(url_for("order_detail", id=id))
    line = ServiceOrderLine(
        order_id=id,
        kind=request.form.get("kind", "Serviço"),
        description=desc,
        qty=money(request.form.get("qty", 1)),
        unit_price=money(request.form.get("unit_price") or (inv.price if inv else 0)),
        inventory_item_id=inv_id,
    )
    db.session.add(line)
    db.session.commit()
    return redirect(url_for("order_detail", id=id))


@app.route("/os/<int:id>/status", methods=["POST"])
@login_required
def order_status(id):
    o = ServiceOrder.query.get_or_404(id)
    new_status = request.form.get("status", o.status)
    if new_status == "Concluída" and not o.stock_applied:
        shortages = []
        for line in o.lines:
            if line.inventory_item_id:
                item = InventoryItem.query.get(line.inventory_item_id)
                if item and money(item.qty) < money(line.qty):
                    shortages.append(f"{item.name} (saldo {item.qty}, necessário {line.qty})")
        if shortages:
            flash("Estoque insuficiente: " + "; ".join(shortages), "danger")
            return redirect(url_for("order_detail", id=id))
        for line in o.lines:
            if line.inventory_item_id:
                item = InventoryItem.query.get(line.inventory_item_id)
                if item:
                    item.qty = money(item.qty) - money(line.qty)
        o.stock_applied = True
        o.finished_at = datetime.utcnow()
    o.status = new_status
    db.session.commit()
    flash("Status da OS atualizado.", "success")
    return redirect(url_for("order_detail", id=id))


def ensure_order_receivable(o, due_date=None):
    r = Receivable.query.filter_by(order_id=o.id).first()
    if not r:
        r = Receivable(
            client_id=o.client_id,
            order_id=o.id,
            description=f"OS #{o.id} - {o.client.name}",
            amount=o.total,
            paid_amount=0,
            due_date=due_date or date.today(),
            status="Pendente",
        )
        db.session.add(r)
        db.session.flush()
    return r


@app.route("/os/<int:id>/cobranca", methods=["POST"])
@login_required
def order_create_receivable(id):
    o = ServiceOrder.query.get_or_404(id)
    due = parse_date(request.form.get("due_date"), date.today())
    r = ensure_order_receivable(o, due)
    r.due_date = due
    r.amount = o.total
    if r.balance <= 0:
        r.status = "Pago"
    db.session.commit()
    flash("Conta a receber gerada/atualizada para esta OS.", "success")
    return redirect(url_for("order_detail", id=id))


@app.route("/os/<int:id>/pagar", methods=["POST"])
@login_required
def order_pay(id):
    o = ServiceOrder.query.get_or_404(id)
    r = ensure_order_receivable(o, date.today())
    if money(o.total) > money(r.paid_amount):
        r.amount = o.total
    remaining = r.balance
    if remaining > 0:
        p = ReceivablePayment(receivable_id=r.id, amount=remaining, paid_at=date.today(), method=request.form.get("method", "PIX"))
        db.session.add(p)
        r.paid_amount = money(r.paid_amount) + remaining
        r.status = "Pago"
        o.payment_status = "Pago"
        db.session.add(FinanceEntry(kind="Receita", description=f"Recebimento OS #{o.id} - {o.client.name}", amount=remaining, due_date=date.today(), paid=True, order_id=o.id))
        db.session.commit()
        flash("OS marcada como paga e recebimento lançado no financeiro.", "success")
    else:
        o.payment_status = "Pago"
        db.session.commit()
    return redirect(url_for("order_detail", id=id))


@app.route("/os/<int:id>/whatsapp")
@login_required
def order_whatsapp(id):
    o = ServiceOrder.query.get_or_404(id)
    phone = whatsapp_phone(o.client.phone)
    if not phone:
        flash("Cadastre o WhatsApp/telefone do cliente primeiro.", "danger")
        return redirect(url_for("order_detail", id=id))
    vehicle = o.vehicle.label if o.vehicle else "veículo não informado"
    msg = f"Olá, {o.client.name}! Aqui é da JVS Mecânica. A OS #{o.id} do {vehicle} está com status: {o.status}. Valor: {brl(o.total)}. Pagamento: {o.payment_status}."
    return redirect(f"https://wa.me/{phone}?text={quote(msg)}")


@app.route("/os/<int:id>/imprimir")
@login_required
def order_print(id):
    return render_template("print_doc.html", doc=ServiceOrder.query.get_or_404(id), kind="ORDEM DE SERVIÇO", company=Company.query.first())


@app.route("/os/<int:id>/termica")
@login_required
def order_thermal(id):
    return render_template("thermal_doc.html", doc=ServiceOrder.query.get_or_404(id), kind="ORDEM DE SERVIÇO", company=Company.query.first())


@app.route("/os/<int:id>/recibo")
@login_required
def order_receipt(id):
    o = ServiceOrder.query.get_or_404(id)
    if o.payment_status != "Pago":
        flash("O recibo de quitação fica disponível depois que a OS for paga.", "danger")
        return redirect(url_for("order_detail", id=id))
    r = Receivable.query.filter_by(order_id=id).first()
    return render_template("receipt.html", o=o, receivable=r, company=Company.query.first())


@app.route("/os/<int:id>/recibo-termico")
@login_required
def order_receipt_thermal(id):
    o = ServiceOrder.query.get_or_404(id)
    if o.payment_status != "Pago":
        flash("O recibo térmico fica disponível depois que a OS for paga.", "danger")
        return redirect(url_for("order_detail", id=id))
    r = Receivable.query.filter_by(order_id=id).first()
    return render_template("thermal_doc.html", doc=o, kind="RECIBO", company=Company.query.first(), receivable=r)


# ---------- contas a receber ----------
@app.route("/receber", methods=["GET", "POST"])
@login_required
def receivables():
    if request.method == "POST":
        amount = money(request.form.get("amount"))
        if amount <= 0:
            flash("Informe um valor maior que zero.", "danger")
            return redirect(url_for("receivables"))
        r = Receivable(
            client_id=int(request.form["client_id"]),
            description=request.form["description"].strip(),
            amount=amount,
            paid_amount=0,
            due_date=parse_date(request.form.get("due_date"), date.today()),
            status="Pendente",
        )
        db.session.add(r)
        db.session.commit()
        flash("Conta a receber cadastrada.", "success")
        return redirect(url_for("receivables"))
    status = request.args.get("status", "abertas")
    query = Receivable.query
    if status == "abertas":
        query = query.filter(Receivable.status != "Pago")
    elif status == "pagas":
        query = query.filter(Receivable.status == "Pago")
    items = query.order_by(Receivable.due_date.asc(), Receivable.id.desc()).all()
    open_items = Receivable.query.filter(Receivable.status != "Pago").all()
    total_open = sum((r.balance for r in open_items), Decimal("0.00"))
    overdue = sum((r.balance for r in open_items if r.due_date and r.due_date < date.today()), Decimal("0.00"))
    return render_template("receivables.html", items=items, clients=Client.query.order_by(Client.name).all(), total_open=total_open, overdue=overdue, status=status, today=date.today())


@app.route("/receber/<int:id>/pagar", methods=["POST"])
@login_required
def receivable_pay(id):
    r = Receivable.query.get_or_404(id)
    amount = money(request.form.get("amount"))
    if amount <= 0:
        flash("Informe um valor maior que zero.", "danger")
        return redirect(url_for("receivables"))
    if amount > r.balance:
        flash(f"O valor é maior que o saldo em aberto ({brl(r.balance)}).", "danger")
        return redirect(url_for("receivables"))
    paid_at = parse_date(request.form.get("paid_at"), date.today())
    method = request.form.get("method", "PIX").strip()
    p = ReceivablePayment(receivable_id=r.id, amount=amount, paid_at=paid_at, method=method, note=request.form.get("note", "").strip())
    db.session.add(p)
    r.paid_amount = money(r.paid_amount) + amount
    r.status = "Pago" if r.balance <= 0 else "Parcial"
    order_id = r.order_id
    if r.order:
        r.order.payment_status = "Pago" if r.status == "Pago" else "Parcial"
    db.session.add(FinanceEntry(kind="Receita", description=f"Recebimento - {r.description}", amount=amount, due_date=paid_at, paid=True, order_id=order_id))
    db.session.commit()
    flash("Recebimento registrado.", "success")
    return redirect(url_for("receivables"))


# ---------- financeiro ----------
@app.route("/financeiro", methods=["GET", "POST"])
@login_required
def finance():
    if request.method == "POST":
        e = FinanceEntry(
            kind=request.form["kind"],
            description=request.form["description"].strip(),
            amount=money(request.form["amount"]),
            due_date=parse_date(request.form.get("due_date"), date.today()),
            paid=request.form.get("paid") == "on",
        )
        db.session.add(e)
        db.session.commit()
        flash("Lançamento financeiro salvo.", "success")
        return redirect(url_for("finance"))
    entries = FinanceEntry.query.order_by(FinanceEntry.due_date.desc(), FinanceEntry.id.desc()).limit(300).all()
    income = sum((money(e.amount) for e in entries if e.kind == "Receita" and e.paid), Decimal("0"))
    expense = sum((money(e.amount) for e in entries if e.kind == "Despesa" and e.paid), Decimal("0"))
    open_receivables = Receivable.query.filter(Receivable.status != "Pago").all()
    receive_total = sum((r.balance for r in open_receivables), Decimal("0.00"))
    return render_template("finance.html", entries=entries, income=income, expense=expense, balance=income-expense, receive_total=receive_total)


# ---------- relatórios ----------
@app.route("/relatorios")
@login_required
def reports():
    month = request.args.get("mes") or date.today().strftime("%Y-%m")
    start, end = month_bounds(month)
    entries = FinanceEntry.query.filter(FinanceEntry.due_date >= start, FinanceEntry.due_date < end, FinanceEntry.paid.is_(True)).all()
    revenue = sum((money(e.amount) for e in entries if e.kind == "Receita"), Decimal("0.00"))
    expense = sum((money(e.amount) for e in entries if e.kind == "Despesa"), Decimal("0.00"))
    month_orders = ServiceOrder.query.filter(ServiceOrder.created_at >= datetime.combine(start, datetime.min.time()), ServiceOrder.created_at < datetime.combine(end, datetime.min.time())).all()
    billed = sum((o.total for o in month_orders), Decimal("0.00"))
    completed = sum(1 for o in month_orders if o.status == "Concluída")
    paid = sum(1 for o in month_orders if o.payment_status == "Pago")

    service_totals = {}
    client_totals = {}
    for o in month_orders:
        client_totals[o.client.name] = client_totals.get(o.client.name, Decimal("0.00")) + o.total
        for l in o.lines:
            service_totals[l.description] = service_totals.get(l.description, Decimal("0.00")) + money(l.qty) * money(l.unit_price)
    top_services = sorted(service_totals.items(), key=lambda x: x[1], reverse=True)[:8]
    top_clients = sorted(client_totals.items(), key=lambda x: x[1], reverse=True)[:8]

    day_revenue = {}
    day_expense = {}
    for e in entries:
        key = e.due_date.day
        if e.kind == "Receita":
            day_revenue[key] = day_revenue.get(key, Decimal("0.00")) + money(e.amount)
        else:
            day_expense[key] = day_expense.get(key, Decimal("0.00")) + money(e.amount)
    days = calendar.monthrange(start.year, start.month)[1]
    chart = [{"day": d, "revenue": float(day_revenue.get(d, 0)), "expense": float(day_expense.get(d, 0))} for d in range(1, days + 1)]
    max_chart = max([max(x["revenue"], x["expense"]) for x in chart] + [1])

    return render_template(
        "reports.html",
        month=month,
        start=start,
        revenue=revenue,
        expense=expense,
        profit=revenue-expense,
        billed=billed,
        order_count=len(month_orders),
        completed=completed,
        paid=paid,
        top_services=top_services,
        top_clients=top_clients,
        chart=chart,
        max_chart=max_chart,
    )


@app.route("/relatorios/mensal.csv")
@login_required
def monthly_csv():
    month = request.args.get("mes") or date.today().strftime("%Y-%m")
    start, end = month_bounds(month)
    rows = ["data;tipo;descricao;valor"]
    for e in FinanceEntry.query.filter(FinanceEntry.due_date >= start, FinanceEntry.due_date < end, FinanceEntry.paid.is_(True)).order_by(FinanceEntry.due_date).all():
        vals = [e.due_date.strftime("%d/%m/%Y"), e.kind, e.description, str(money(e.amount)).replace(".", ",")]
        rows.append(";".join('"'+str(v or '').replace('"','""')+'"' for v in vals))
    return Response("\ufeff" + "\n".join(rows), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=relatorio-jvs-{month}.csv"})


# ---------- empresa ----------
@app.route("/empresa", methods=["GET", "POST"])
@login_required
def company():
    c = Company.query.first()
    if request.method == "POST":
        c.name = request.form.get("name", "").strip()
        c.phone = request.form.get("phone", "").strip()
        c.instagram = request.form.get("instagram", "").strip()
        c.pix_key = request.form.get("pix_key", "").strip()
        c.address = request.form.get("address", "").strip()
        db.session.commit()
        flash("Dados da empresa atualizados.", "success")
        return redirect(url_for("company"))
    return render_template("company.html", c=c)


@app.route("/relatorios/clientes.csv")
@login_required
def clients_csv():
    rows = ["nome;telefone;cpf_cnpj;email;endereco"]
    for c in Client.query.order_by(Client.name):
        vals = [c.name, c.phone, c.cpf_cnpj, c.email, c.address]
        rows.append(";".join('"'+str(v or '').replace('"','""')+'"' for v in vals))
    return Response("\ufeff" + "\n".join(rows), mimetype="text/csv", headers={"Content-Disposition":"attachment; filename=clientes-jvs.csv"})


if __name__ == "__main__":
    with app.app_context():
        init_db()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")), debug=os.getenv("FLASK_DEBUG") == "1")
