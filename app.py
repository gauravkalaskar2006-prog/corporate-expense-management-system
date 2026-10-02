import csv
import hmac
import io
import os
import re
from uuid import uuid4
from datetime import date
from decimal import Decimal, InvalidOperation
from functools import wraps

import mysql.connector
from flask import Flask, Response, abort, flash, redirect, render_template, request, send_from_directory, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from db import get_db_connection

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "change-this-development-key")
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024

# The SQL below expects conventional id/name columns in the existing tables.
STATUSES = ("Pending", "Pending Admin", "Approved", "Rejected", "Reimbursed")
PAYMENT_METHODS = ("Cash", "Debit Card", "Credit Card", "UPI", "Bank Transfer")
LOGIN_ROLES = {
    "employee": "Employee",
    "manager": "Manager",
    "finance": "Finance, Admin",
}
GENDER_OPTIONS = ("Female", "Male", "Non-binary", "Other", "Prefer not to say")
RECEIPT_EXTENSIONS = {"pdf", "png", "jpg", "jpeg"}


class DatabaseUnavailable(Exception):
    pass


def fetch_one(sql, params=()):
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(sql, params)
        return cursor.fetchone()
    except mysql.connector.Error as error:
        print("MySQL query failed:", error)
        raise DatabaseUnavailable from error
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


def fetch_all(sql, params=()):
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(sql, params)
        return cursor.fetchall()
    except mysql.connector.Error as error:
        print("MySQL query failed:", error)
        raise DatabaseUnavailable from error
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()


def role_key(role):
    value = "".join(character for character in str(role).lower() if character.isalnum())
    if "manager" in value or "maneger" in value:
        return "manager"
    if "finance" in value or "admin" in value:
        return "finance"
    if "employee" in value:
        return "employee"
    return None


def table_columns(cursor, table_name):
    """Return column metadata for one of this app's fixed table names."""
    cursor.execute("SHOW COLUMNS FROM `{}`".format(table_name))
    return {column["Field"]: column for column in cursor.fetchall()}


def schema_column_names(table_name):
    """Return columns for one of the fixed tables used by schema compatibility."""
    if table_name not in ("expenses", "reimbursements", "users", "employees"):
        raise ValueError("Unsupported table for schema compatibility lookup.")
    return {
        column["Field"]
        for column in fetch_all("SHOW COLUMNS FROM `{}`".format(table_name))
    }


def expense_receipt_file_expression():
    if "receipt_file" in schema_column_names("expenses"):
        return "e.receipt_file AS receipt_file"
    return "NULL AS receipt_file"


def reimbursement_column_names(cursor=None):
    columns = (
        set(table_columns(cursor, "reimbursements"))
        if cursor is not None
        else schema_column_names("reimbursements")
    )

    # Your database uses reimbursement_amount
    if "reimbursement_amount" in columns:
        amount_column = "reimbursement_amount"
    elif "amount" in columns:
        amount_column = "amount"
    else:
        raise DatabaseUnavailable

    # Your database uses payment_status
    if "payment_status" in columns:
        status_column = "payment_status"
    elif "status" in columns:
        status_column = "status"
    else:
        status_column = None

    return amount_column, status_column


def expense_user_role_predicate(role, cursor=None):
    """Return an expense filter for a role across supported user/profile links."""
    if role not in ("Employee", "Manager"):
        raise ValueError("Unsupported user role for expense lookup.")
    if cursor is not None:
        user_columns = set(table_columns(cursor, "users"))
        employee_columns = set(table_columns(cursor, "employees"))
    else:
        user_columns = schema_column_names("users")
        employee_columns = schema_column_names("employees")

    if "role" not in user_columns:
        return "1 = 0"
    role_match = "IN ('manager', 'maneger')" if role == "Manager" else "= 'employee'"
    predicates = []
    if "employee_id" in user_columns:
        predicates.append(
            "EXISTS (SELECT 1 FROM users expense_user "
            "WHERE expense_user.employee_id = e.employee_id "
            "AND LOWER(expense_user.role) {})".format(role_match)
        )
    user_id_column = next(
        (name for name in ("user_id", "id") if name in user_columns),
        None,
    )
    if "user_id" in employee_columns and user_id_column:
        predicates.append((
            "EXISTS (SELECT 1 FROM employees expense_employee "
            "INNER JOIN users expense_user ON expense_user.`{}` = expense_employee.user_id "
            "WHERE expense_employee.employee_id = e.employee_id "
            "AND LOWER(expense_user.role) {})"
        ).format(user_id_column, role_match))
    return "(" + " OR ".join(predicates) + ")" if predicates else "1 = 0"


def manager_expense_predicate(cursor=None):
    return expense_user_role_predicate("Manager", cursor)


def employee_profile_for_user(user_id, fallback_employee_id=None):
    """Resolve the profile through its direct user link before legacy links."""
    employee_columns = schema_column_names("employees")
    if "user_id" in employee_columns:
        employee = fetch_one(
            "SELECT employee_id, department_id FROM employees WHERE user_id = %s LIMIT 1",
            (user_id,),
        )
        if employee:
            return employee
    if fallback_employee_id is not None:
        return fetch_one(
            "SELECT employee_id, department_id FROM employees WHERE employee_id = %s",
            (fallback_employee_id,),
        )
    return None


def refresh_manager_profile():
    """Keep department scoping aligned with the manager's current employee profile."""
    if session.get("role_key") != "manager":
        return
    employee = employee_profile_for_user(
        session.get("user_id"), session.get("employee_id")
    )
    if employee:
        session["employee_id"] = employee["employee_id"]
        session["department_id"] = employee.get("department_id")


def add_if_present(values, columns, names, value):
    """Add a value under the first matching schema column name."""
    for name in names:
        if name in columns:
            values[name] = value
            return name
    return None


def insert_row(cursor, table_name, values):
    """Insert values using column names obtained from the database schema."""
    columns = list(values)
    names = ", ".join("`{}`".format(name) for name in columns)
    placeholders = ", ".join(["%s"] * len(columns))
    cursor.execute(
        "INSERT INTO `{}` ({}) VALUES ({})".format(table_name, names, placeholders),
        tuple(values[name] for name in columns),
    )


def missing_required_columns(column_metadata, supplied_values):
    missing = []
    for name, column in column_metadata.items():
        if (
            column.get("Null") == "NO"
            and column.get("Default") is None
            and "auto_increment" not in str(column.get("Extra", "")).lower()
            and name not in supplied_values
        ):
            missing.append(name)
    return missing


def first_value(*values):
    return next((value for value in values if value not in (None, "")), None)


def csv_safe_cell(value):
    if isinstance(value, str) and value.lstrip(" \t\r").startswith(("=", "+", "-", "@")):
        return "'" + value
    return value


def password_matches(saved_password, entered_password):
    saved_password = str(saved_password or "")
    if saved_password.startswith(("pbkdf2:", "scrypt:")):
        try:
            return check_password_hash(saved_password, entered_password)
        except (ValueError, TypeError):
            return False
    return hmac.compare_digest(saved_password, entered_password)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped


def role_required(*allowed_roles):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if "user_id" not in session:
                return redirect(url_for("login"))
            if session.get("role_key") not in allowed_roles:
                flash("Your account does not have access to that page.", "error")
                return redirect(url_for("dashboard"))
            return view(*args, **kwargs)
        return wrapped
    return decorate


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            return redirect(url_for("login"))
        role = "".join(
            character
            for character in str(session.get("role", "")).lower()
            if character.isalnum()
        )
        if role != "admin":
            flash("Only an Admin can review manager expenses.", "error")
            return redirect(url_for("dashboard"))
        return view(*args, **kwargs)
    return wrapped


def expense_scope():
    """Return a fixed SQL scope and values for the signed-in user's role."""
    role = session.get("role_key")
    if role == "employee":
        return "e.employee_id = %s", (session.get("employee_id"),)
    if role == "manager":
        refresh_manager_profile()
        if session.get("department_id") is not None:
            return "emp.department_id = %s", (session.get("department_id"),)
    if role == "finance":
        return "1 = 1", ()
    return "1 = 0", ()


def expense_detail_scope():
    if session.get("role_key") == "manager":
        refresh_manager_profile()
        department_id = session.get("department_id")
        if department_id is None:
            return "e.employee_id = %s", (session["employee_id"],)
        return "(e.employee_id = %s OR emp.department_id = %s)", (
            session["employee_id"], department_id,
        )
    return expense_scope()


def expense_joins():
    return """
        FROM expenses e
        INNER JOIN employees emp ON emp.employee_id = e.employee_id
        LEFT JOIN departments dep ON dep.department_id = emp.department_id
        INNER JOIN expense_categories cat ON cat.category_id = e.category_id
    """


def load_charts(year, scope, scope_values):
    monthly = fetch_all(
        """
        SELECT MONTH(e.expense_date) AS month_number,
               DATE_FORMAT(e.expense_date, '%b') AS month_name,
               SUM(e.amount) AS total
        """ + expense_joins() + """
        WHERE YEAR(e.expense_date) = %s AND """ + scope + """
        GROUP BY MONTH(e.expense_date), DATE_FORMAT(e.expense_date, '%b')
        ORDER BY month_number
        """,
        (year,) + scope_values,
    )
    categories = fetch_all(
        """
        SELECT cat.category_name AS label, SUM(e.amount) AS total
        """ + expense_joins() + """
        WHERE YEAR(e.expense_date) = %s AND """ + scope + """
        GROUP BY cat.category_id, cat.category_name
        HAVING SUM(e.amount) > 0
        ORDER BY total DESC
        """,
        (year,) + scope_values,
    )
    return {
        "monthly": {
            "labels": [row["month_name"] for row in monthly],
            "values": [float(row["total"] or 0) for row in monthly],
        },
        "category": {
            "labels": [row["label"] or "Uncategorised" for row in categories],
            "values": [float(row["total"] or 0) for row in categories],
        },
    }


def expense_summary(scope, scope_values):
    return fetch_one(
        """
        SELECT COUNT(e.expense_id) AS total_count,
               COALESCE(SUM(e.amount), 0) AS total_amount,
               COALESCE(SUM(CASE WHEN e.status IN ('Pending', 'Pending Admin') THEN 1 ELSE 0 END), 0) AS pending_count,
               COALESCE(SUM(CASE WHEN e.status IN ('Pending', 'Pending Admin') THEN e.amount ELSE 0 END), 0) AS pending_amount,
               COALESCE(SUM(CASE WHEN e.status = 'Approved' THEN 1 ELSE 0 END), 0) AS approved_count,
               COALESCE(SUM(CASE WHEN e.status = 'Approved' THEN e.amount ELSE 0 END), 0) AS approved_amount,
               COALESCE(SUM(CASE WHEN e.status = 'Rejected' THEN 1 ELSE 0 END), 0) AS rejected_count,
               COALESCE(SUM(CASE WHEN e.status = 'Reimbursed' THEN 1 ELSE 0 END), 0) AS reimbursed_count,
               COALESCE(SUM(CASE WHEN e.status = 'Reimbursed' THEN e.amount ELSE 0 END), 0) AS reimbursed_amount
        """ + expense_joins() + " WHERE " + scope,
        scope_values,
    ) or {}


@app.template_filter("currency")
def currency(value):
    try:
        return "₹{:,.2f}".format(float(value or 0))
    except (TypeError, ValueError):
        return "₹0.00"


def render_login(status=200, selected_role="employee"):
    return render_template(
        "login.html",
        login_roles=LOGIN_ROLES,
        selected_role=selected_role,
    ), status


@app.route("/", methods=["GET", "POST"])
@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        selected_role = request.form.get("role", "").strip().lower()
        if not username or not password or selected_role not in LOGIN_ROLES:
            flash("Enter your username and password, and choose your role.", "error")
            return render_login(400, selected_role)
        user = fetch_one(
            "SELECT * FROM users WHERE username = %s LIMIT 1",
            (username,),
        )
        saved_password = user.get("password") or user.get("password_hash") if user else None
        user_role = role_key(user.get("role")) if user else None
        if (
            not user
            or user_role != selected_role
            or not password_matches(saved_password, password)
        ):
            flash("The username, password, or selected role is incorrect.", "error")
            return render_login(401, selected_role)

        user_id = user.get("user_id", user.get("id"))
        if user_id is None:
            flash("This account is missing its user ID. Contact the system administrator.", "error")
            return render_login(500, selected_role)

        employee_id = user.get("employee_id")
        employee = None
        if user_role in ("employee", "manager"):
            employee = employee_profile_for_user(user_id, employee_id)
        if user_role in ("employee", "manager") and not employee:
            flash("No employee record is linked to this account.", "error")
            return render_login(403, selected_role)

        session.clear()
        session["user_id"] = user_id
        session["username"] = user.get("username", username)
        session["role"] = user.get("role", "")
        session["role_key"] = user_role
        if employee:
            session["employee_id"] = employee["employee_id"]
            session["department_id"] = employee.get("department_id")
        return redirect(url_for("dashboard"))
    return render_login()


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    form = request.form if request.method == "POST" else {}
    departments = fetch_all(
        "SELECT department_id, department_name FROM departments ORDER BY department_name"
    )

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        first_name = request.form.get("first_name", "").strip()
        last_name = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip()
        mobile = request.form.get("mobile", "").strip()
        gender = request.form.get("gender", "").strip()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        department_value = request.form.get("department_id", "").strip()

        valid_mobile = (
            re.fullmatch(r"[0-9+() .-]{7,20}", mobile)
            and sum(character.isdigit() for character in mobile) >= 7
        )
        if not username or len(username) > 50 or len(username) < 3:
            flash("Choose a username between 3 and 50 characters.", "error")
        elif not first_name or not last_name or len(first_name) > 80 or len(last_name) > 80:
            flash("Enter your first and last name (up to 80 characters each).", "error")
        elif not valid_mobile:
            flash("Enter a valid mobile number with 7 to 20 characters.", "error")
        elif gender not in GENDER_OPTIONS:
            flash("Choose one of the listed gender options.", "error")
        elif not email:
            flash("Email address is required.", "error")
        elif len(email) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", email):
            flash("Enter a valid email address.", "error")
        elif departments and not department_value:
            flash("Choose your department.", "error")
        elif len(password) < 8 or len(password) > 128:
            flash("Use a password between 8 and 128 characters.", "error")
        elif password != confirm_password:
            flash("The passwords do not match.", "error")
        else:
            selected_department = None
            if department_value:
                try:
                    department_id = int(department_value)
                except ValueError:
                    department_id = None
                selected_department = next(
                    (item for item in departments if item["department_id"] == department_id),
                    None,
                )
                if selected_department is None:
                    flash("Choose a valid department.", "error")

            if not department_value or selected_department is not None:
                connection = cursor = None
                try:
                    connection = get_db_connection()
                    connection.start_transaction()
                    cursor = connection.cursor(dictionary=True)
                    users_columns = table_columns(cursor, "users")
                    employees_columns = table_columns(cursor, "employees")

                    if not all(name in users_columns for name in ("username", "role")):
                        raise ValueError("The users table needs username and role columns.")
                    if not any(name in users_columns for name in ("user_id", "id")):
                        raise ValueError("The users table needs a user_id or id column.")
                    if "employee_id" not in employees_columns:
                        raise ValueError("The employees table needs an employee_id column.")
                    has_split_name = all(
                        name in employees_columns for name in ("first_name", "last_name")
                    )
                    if "employee_name" not in employees_columns and not has_split_name:
                        raise ValueError(
                            "The employees table needs employee_name or both first_name and last_name columns."
                        )

                    user_values = {"username": username, "role": "Employee"}
                    password_hash = generate_password_hash(password)
                    password_column = add_if_present(
                        user_values, users_columns, ("password_hash", "password"),
                        password_hash,
                    )
                    if password_column is None:
                        raise ValueError("The users table needs a password or password_hash column.")
                    for name in ("password_hash", "password"):
                        if name in users_columns:
                            user_values[name] = password_hash
                    add_if_present(user_values, users_columns, ("first_name",), first_name)
                    add_if_present(user_values, users_columns, ("last_name",), last_name)
                    if email:
                        add_if_present(user_values, users_columns, ("email",), email)
                    phone_columns = (
                        "mobile_no", "mobile_number", "phone", "phone_number",
                        "contact_no", "contact_number", "mobile", "phone_no",
                    )
                    user_phone_column = add_if_present(user_values, users_columns, phone_columns, mobile)
                    user_gender_column = add_if_present(user_values, users_columns, ("gender",), gender)

                    employee_name = f"{first_name} {last_name}".strip()
                    employee_values = {}
                    add_if_present(employee_values, employees_columns, ("employee_name",), employee_name)
                    add_if_present(employee_values, employees_columns, ("first_name",), first_name)
                    add_if_present(employee_values, employees_columns, ("last_name",), last_name)
                    add_if_present(employee_values, employees_columns, ("user_id",), None)
                    add_if_present(employee_values, employees_columns, ("email",), email)
                    employee_mobile_column = add_if_present(
                        employee_values, employees_columns, phone_columns, mobile
                    )
                    employee_gender_column = add_if_present(
                        employee_values, employees_columns, ("gender",), gender
                    )
                    if selected_department:
                        department_column = add_if_present(
                            employee_values, employees_columns, ("department_id",),
                            selected_department["department_id"],
                        )
                        if department_column is None:
                            raise ValueError("The employees table needs a department_id column to use departments.")

                    if employee_mobile_column is None and user_phone_column is None:
                        raise ValueError("Add a mobile number column to users or employees before enabling signup.")
                    if employee_gender_column is None and user_gender_column is None:
                        raise ValueError("Add a gender column to users or employees before enabling signup.")
                    if "user_id" not in employees_columns and "employee_id" not in users_columns:
                        raise ValueError("Link employees to users with employees.user_id or users.employee_id.")

                    if (
                        "employee_id" in users_columns
                        and users_columns["employee_id"].get("Null") == "NO"
                        and users_columns["employee_id"].get("Default") is None
                    ):
                        raise ValueError("The users.employee_id column must allow NULL for employee account creation.")

                    missing_users = missing_required_columns(users_columns, user_values)
                    missing_employees = missing_required_columns(employees_columns, employee_values)
                    if missing_users or missing_employees:
                        raise ValueError(
                            "The database has required signup fields that this form does not collect. "
                            "Check required columns: users {0}; employees {1}.".format(
                                ", ".join(missing_users) or "none",
                                ", ".join(missing_employees) or "none",
                            )
                        )

                    cursor.execute("SELECT 1 FROM users WHERE username = %s LIMIT 1", (username,))
                    if cursor.fetchone():
                        connection.rollback()
                        flash("That username is already in use.", "error")
                    else:
                        insert_row(cursor, "users", user_values)
                        user_id = cursor.lastrowid
                        if "user_id" in employees_columns:
                            employee_values["user_id"] = user_id
                        insert_row(cursor, "employees", employee_values)
                        employee_id = cursor.lastrowid
                        if "employee_id" in users_columns:
                            user_id_column = next(
                                (name for name in ("user_id", "id") if name in users_columns),
                                None,
                            )
                            if user_id_column is None:
                                raise ValueError("The users table needs a user_id or id column.")
                            cursor.execute(
                                "UPDATE users SET employee_id = %s WHERE `{}` = %s".format(user_id_column),
                                (employee_id, user_id),
                            )
                        connection.commit()
                        flash("Your employee account is ready. Sign in to continue.", "success")
                        return redirect(url_for("login"))
                except ValueError as error:
                    if connection:
                        connection.rollback()
                    flash(str(error), "error")
                except mysql.connector.IntegrityError as error:
                    if connection:
                        connection.rollback()
                    print("Signup constraint failed:", error)
                    flash("The username or another account detail is already in use.", "error")
                except mysql.connector.Error as error:
                    if connection:
                        connection.rollback()
                    print("Signup failed:", error)
                    flash("The account could not be created. Check the database signup columns and try again.", "error")
                finally:
                    if cursor:
                        cursor.close()
                    if connection and connection.is_connected():
                        connection.close()

    return render_template(
        "signup.html",
        departments=departments,
        form=form,
        gender_options=GENDER_OPTIONS,
    )


@app.route("/logout")
def logout():
    session.clear()
    flash("You have signed out.", "success")
    return redirect(url_for("login"))


@app.route("/profile")
@role_required("employee", "manager")
def profile():
    connection = cursor = None
    try:
        connection = get_db_connection()
        cursor = connection.cursor(dictionary=True)
        users_columns = table_columns(cursor, "users")
        user_id_column = next((name for name in ("user_id", "id") if name in users_columns), None)
        if user_id_column is None:
            abort(404)
        cursor.execute(
            "SELECT * FROM users WHERE `{}` = %s LIMIT 1".format(user_id_column),
            (session["user_id"],),
        )
        user = cursor.fetchone() or {}
        cursor.execute(
            "SELECT * FROM employees WHERE employee_id = %s LIMIT 1",
            (session["employee_id"],),
        )
        employee = cursor.fetchone() or {}
        department_name = None
        department_id = employee.get("department_id")
        if department_id is not None:
            cursor.execute(
                "SELECT department_name FROM departments WHERE department_id = %s LIMIT 1",
                (department_id,),
            )
            department = cursor.fetchone()
            department_name = department.get("department_name") if department else None
        email = first_value(employee.get("email"), user.get("email"))
        phone_names = (
            "mobile_no", "mobile_number", "phone", "phone_number",
            "contact_no", "contact_number", "mobile", "phone_no",
        )
        mobile = first_value(
            *(employee.get(name) for name in phone_names),
            *(user.get(name) for name in phone_names),
        )
        fields = [
            ("Username", user.get("username", session.get("username"))),
            ("First name", first_value(employee.get("first_name"), user.get("first_name"))),
            ("Last name", first_value(employee.get("last_name"), user.get("last_name"))),
            ("Mobile number", mobile),
            ("Gender", first_value(employee.get("gender"), user.get("gender"))),
            ("Email address", email),
            ("Department", department_name),
            ("Employee ID", employee.get("employee_id")),
        ]
    except mysql.connector.Error as error:
        print("Profile lookup failed:", error)
        raise DatabaseUnavailable from error
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    return render_template("profile.html", fields=fields, active_page="profile")


@app.route("/dashboard")
@role_required("employee", "manager", "finance")
def dashboard():
    role = session["role_key"]
    today = date.today().strftime("%d %b %Y")
    own_scope = "e.employee_id = %s"
    own_values = (session.get("employee_id"),)

    if role == "employee":
        stats = expense_summary(own_scope, own_values)
        recent = fetch_all(
            """
            SELECT e.expense_id, DATE_FORMAT(e.expense_date, '%Y-%m-%d') AS expense_date,
                   cat.category_name, e.amount, e.status
            """ + expense_joins() + " WHERE " + own_scope + """
            ORDER BY e.expense_date DESC, e.expense_id DESC LIMIT 6
            """,
            own_values,
        )
        return render_template(
            "dashboard_employee.html",
            stats=stats,
            recent=recent,
            charts=load_charts(date.today().year, own_scope, own_values),
            today=today,
            dashboard_title="Employee dashboard",
            dashboard_eyebrow="PERSONAL OVERVIEW",
            dashboard_subtitle="Track your expense claims, reimbursements, and spending.",
            active_page="dashboard",
        )

    if role == "manager":
        department_scope, department_values = expense_scope()
        own_stats = expense_summary(own_scope, own_values)
        department_stats = expense_summary(department_scope, department_values)
        recent = fetch_all(
            """
            SELECT e.expense_id, DATE_FORMAT(e.expense_date, '%Y-%m-%d') AS expense_date,
                   cat.category_name, e.amount, e.status
            """ + expense_joins() + " WHERE " + own_scope + """
            ORDER BY e.expense_date DESC, e.expense_id DESC LIMIT 6
            """,
            own_values,
        )
        pending_department = fetch_one(
            """
            SELECT COUNT(e.expense_id) AS pending_count,
                   COALESCE(SUM(e.amount), 0) AS pending_amount
            """ + expense_joins() + """
            WHERE e.status = 'Pending' AND """ + department_scope + " AND e.employee_id <> %s",
            department_values + (session["employee_id"],),
        ) or {}
        return render_template(
            "dashboard_manager.html",
            own_stats=own_stats,
            department_stats=department_stats,
            pending_department=pending_department,
            recent=recent,
            charts=load_charts(date.today().year, own_scope, own_values),
            today=today,
            dashboard_title="Manager dashboard",
            dashboard_eyebrow="PERSONAL AND DEPARTMENT OVERVIEW",
            dashboard_subtitle="Manage your own claims and review expenses from your department.",
            active_page="dashboard",
        )

    scope, values = expense_scope()
    stats = expense_summary(scope, values)
    recent = fetch_all(
        """
        SELECT e.expense_id, DATE_FORMAT(e.expense_date, '%Y-%m-%d') AS expense_date,
               cat.category_name, e.amount, e.status,
               CONCAT_WS(' ', emp.first_name, emp.last_name) AS employee_name,
               dep.department_name
        """ + expense_joins() + " WHERE " + scope + """
        ORDER BY e.expense_date DESC, e.expense_id DESC LIMIT 8
        """,
        values,
    )
    return render_template(
        "dashboard_finance.html",
        stats=stats,
        recent=recent,
        charts=load_charts(date.today().year, scope, values),
        today=today,
        dashboard_title="Finance dashboard",
        dashboard_eyebrow="ORGANIZATION OVERVIEW",
        dashboard_subtitle="Monitor organization expenses and reimbursement processing.",
        active_page="dashboard",
    )


@app.route("/expenses")
@role_required("employee", "manager", "finance")
def expenses():
    scope, values = expense_scope()
    manager_review = session["role_key"] == "manager"
    statuses = STATUSES
    if manager_review:
        # Department expenses is the manager's employee-claim review queue.
        scope = "({}) AND e.status = 'Pending' AND e.employee_id <> %s".format(scope)
        values += (session["employee_id"],)
        statuses = ("Pending",)
    return render_expense_list(
        scope,
        values,
        "expenses",
        statuses=statuses,
        manager_review=manager_review,
    )


@app.route("/my-expenses")
@role_required("employee", "manager")
def my_expenses():
    refresh_manager_profile()
    return render_expense_list(
        "e.employee_id = %s",
        (session["employee_id"],),
        "my_expenses",
    )


def render_expense_list(scope, values, listing_endpoint, statuses=STATUSES, manager_review=False):
    search = request.args.get("q", "").strip()
    selected_status = request.args.get("status", "").strip()
    if selected_status and selected_status not in statuses:
        flash("Choose a valid expense status.", "error")
        return redirect(url_for(listing_endpoint))

    conditions = [scope]
    params = list(values)
    if selected_status:
        conditions.append("e.status = %s")
        params.append(selected_status)
    if search:
        conditions.append(
            "(e.description LIKE %s OR cat.category_name LIKE %s "
            "OR CONCAT_WS(' ', emp.first_name, emp.last_name) LIKE %s)"
        )
        wildcard = "%" + search + "%"
        params.extend((wildcard, wildcard, wildcard))
    rows = fetch_all(
        """
        SELECT e.expense_id, e.employee_id, DATE_FORMAT(e.expense_date, '%Y-%m-%d') AS expense_date,
               cat.category_name, e.description, e.amount, e.payment_method, e.status,
               CONCAT_WS(' ', emp.first_name, emp.last_name) AS employee_name,
               dep.department_name
        """ + expense_joins() + """
        WHERE """ + " AND ".join(conditions) + """
        ORDER BY e.expense_date DESC, e.expense_id DESC
        LIMIT 500
        """,
        tuple(params),
    )
    return render_template(
        "expenses.html",
        expenses=rows,
        statuses=statuses,
        selected_status=selected_status,
        search=search,
        listing_endpoint=listing_endpoint,
        manager_review=manager_review,
        active_page="my_expenses" if listing_endpoint == "my_expenses" else "expenses",
    )


@app.route("/my-reimbursements")
@role_required("employee", "manager")
def my_reimbursements():
    amount_column, status_column = reimbursement_column_names()
    amount_expression = "r.`{}`".format(amount_column)
    status_expression = (
        "r.`{}`".format(status_column) if status_column else "'Processed'"
    )
    history = fetch_all(
        """
        SELECT e.expense_id,
               DATE_FORMAT(e.expense_date, '%Y-%m-%d') AS expense_date,
               DATE_FORMAT(r.reimbursement_date, '%Y-%m-%d') AS reimbursement_date,
               cat.category_name, {amount_expression} AS amount,
               {status_expression} AS reimbursement_status
        FROM reimbursements r
        INNER JOIN expenses e ON e.expense_id = r.expense_id
        INNER JOIN expense_categories cat ON cat.category_id = e.category_id
        WHERE e.employee_id = %s
        ORDER BY r.reimbursement_date DESC, r.reimbursement_id DESC
        LIMIT 500
        """.format(
            amount_expression=amount_expression,
            status_expression=status_expression,
        ),
        (session["employee_id"],),
    )
    return render_template(
        "reimbursement_history.html",
        history=history,
        active_page="my_reimbursements",
    )


@app.route("/expenses/<int:expense_id>")
@role_required("employee", "manager", "finance")
def expense_detail(expense_id):
    scope, values = expense_detail_scope()
    receipt_file_expression = expense_receipt_file_expression()
    expense = fetch_one(
        ("""
        SELECT e.expense_id, DATE_FORMAT(e.expense_date, '%Y-%m-%d') AS expense_date,
               cat.category_name, e.description, e.amount, e.payment_method, e.status,
               CONCAT_WS(' ', emp.first_name, emp.last_name) AS employee_name,
               dep.department_name,
               e.receipt_reference, {receipt_file_expression},
               (SELECT a.remarks FROM approvals a
                WHERE a.expense_id = e.expense_id
                ORDER BY a.approval_date DESC, a.approval_id DESC LIMIT 1) AS approval_remarks,
               (SELECT DATE_FORMAT(r.reimbursement_date, '%Y-%m-%d')
                FROM reimbursements r WHERE r.expense_id = e.expense_id
                ORDER BY r.reimbursement_date DESC LIMIT 1) AS reimbursement_date
        """ + expense_joins() + """
        WHERE e.expense_id = %s AND """ + scope + """
        LIMIT 1
        """).format(receipt_file_expression=receipt_file_expression),
        (expense_id,) + values,
    )
    if not expense:
        abort(404)
    back_endpoint = (
        "my_expenses"
        if session["role_key"] == "manager" and request.args.get("source") == "my_expenses"
        else "expenses"
    )
    return render_template(
        "expense_detail.html",
        expense=expense,
        active_page="my_expenses" if back_endpoint == "my_expenses" else "expenses",
        back_endpoint=back_endpoint,
    )


@app.route("/expenses/<int:expense_id>/receipt")
@role_required("employee", "manager", "finance")
def download_receipt(expense_id):
    scope, values = expense_detail_scope()
    receipt_file_expression = expense_receipt_file_expression()
    receipt = fetch_one(
        ("""
        SELECT {receipt_file_expression}
        FROM expenses e
        INNER JOIN employees emp ON emp.employee_id = e.employee_id
        WHERE e.expense_id = %s AND """ + scope + " LIMIT 1").format(
            receipt_file_expression=receipt_file_expression
        ),
        (expense_id,) + values,
    )
    if not receipt or not receipt.get("receipt_file"):
        abort(404)
    stored_name = receipt["receipt_file"]
    safe_name = secure_filename(stored_name)
    if not safe_name or safe_name != stored_name:
        abort(404)
    extension = safe_name.rsplit(".", 1)[-1].lower()
    if extension not in RECEIPT_EXTENSIONS:
        abort(404)
    return send_from_directory(
        os.path.join(app.instance_path, "receipts"),
        safe_name,
        as_attachment=True,
        download_name="receipt-{0}.{1}".format(expense_id, extension),
    )


@app.route("/expenses/new", methods=["GET", "POST"])
@role_required("employee", "manager")
def submit_expense():
    if request.method == "POST":
        category_id = request.form.get("category_id", "").strip()
        expense_date = request.form.get("expense_date", "").strip()
        description = request.form.get("description", "").strip()
        receipt_reference = request.form.get("receipt_reference", "").strip()
        receipt_upload = request.files.get("receipt_file")
        uploaded_extension = None
        if receipt_upload and receipt_upload.filename:
            safe_original_name = secure_filename(receipt_upload.filename)
            uploaded_extension = safe_original_name.rsplit(".", 1)[-1].lower() if "." in safe_original_name else ""
            if uploaded_extension not in RECEIPT_EXTENSIONS:
                flash("Upload a PDF, PNG, or JPEG receipt file.", "error")
                return redirect(url_for("submit_expense"))
        amount_text = request.form.get("amount", "").strip()
        payment_method = request.form.get("payment_method", "").strip()

        if not all((category_id, expense_date, description, amount_text, payment_method)):
            flash("Complete all required expense fields.", "error")
            return redirect(url_for("submit_expense"))
        if len(receipt_reference) > 255:
            flash("Receipt information must be 255 characters or fewer.", "error")
            return redirect(url_for("submit_expense"))
        try:
            category_id = int(category_id)
            amount = Decimal(amount_text)
            parsed_date = date.fromisoformat(expense_date)
        except (ValueError, InvalidOperation):
            flash("Enter a valid category, date, and amount.", "error")
            return redirect(url_for("submit_expense"))
        if not amount.is_finite() or amount <= 0:
            flash("Expense amount must be greater than zero.", "error")
            return redirect(url_for("submit_expense"))
        if parsed_date > date.today():
            flash("Expense date cannot be in the future.", "error")
            return redirect(url_for("submit_expense"))
        if payment_method not in PAYMENT_METHODS:
            flash("Choose a valid payment method.", "error")
            return redirect(url_for("submit_expense"))

        connection = cursor = None
        receipt_path = None
        receipt_committed = False
        try:
            connection = get_db_connection()
            cursor = connection.cursor(dictionary=True)
            expense_columns = table_columns(cursor, "expenses")
            if receipt_reference and "receipt_reference" not in expense_columns:
                flash("The expenses table is missing the receipt_reference column. Add it in MySQL Workbench to save receipt information.", "error")
                return redirect(url_for("submit_expense"))
            if uploaded_extension and "receipt_file" not in expense_columns:
                flash("The expenses table is missing the receipt_file column. Add it in MySQL Workbench to enable receipt uploads.", "error")
                return redirect(url_for("submit_expense"))
            receipt_filename = None
            if uploaded_extension:
                receipt_filename = uuid4().hex + "." + uploaded_extension
                receipt_folder = os.path.join(app.instance_path, "receipts")
                os.makedirs(receipt_folder, exist_ok=True)
                receipt_path = os.path.join(receipt_folder, receipt_filename)
                receipt_upload.save(receipt_path)
            expense_values = {
                "employee_id": session["employee_id"],
                "category_id": category_id,
                "expense_date": parsed_date,
                "description": description,
                "amount": amount,
                "payment_method": payment_method,
                "status": "Pending Admin" if session["role_key"] == "manager" else "Pending",
            }
            if "receipt_reference" in expense_columns:
                expense_values["receipt_reference"] = receipt_reference or None
            if "receipt_file" in expense_columns:
                expense_values["receipt_file"] = receipt_filename
            insert_row(cursor, "expenses", expense_values)
            connection.commit()
            receipt_committed = True
            if session["role_key"] == "manager":
                flash("Your expense was sent to Admin for review.", "success")
            else:
                flash("Your expense was sent to your manager for review.", "success")
            return redirect(url_for("my_expenses" if session["role_key"] == "manager" else "expenses"))
        except mysql.connector.Error as error:
            if connection:
                connection.rollback()
            print("Expense submission failed:", error)
            flash("The expense could not be saved. Check the selected category and try again.", "error")
        except OSError as error:
            if connection:
                connection.rollback()
            print("Receipt upload failed:", error)
            flash("The receipt file could not be saved. Try again with a smaller file.", "error")
        finally:
            if receipt_path and not receipt_committed and os.path.exists(receipt_path):
                try:
                    os.remove(receipt_path)
                except OSError as error:
                    print("Temporary receipt cleanup failed:", error)
            if cursor:
                cursor.close()
            if connection and connection.is_connected():
                connection.close()

    categories = fetch_all(
        "SELECT category_id, category_name FROM expense_categories ORDER BY category_name"
    )
    return render_template(
        "submit_expense.html",
        categories=categories,
        payment_methods=PAYMENT_METHODS,
        today=date.today().isoformat(),
        active_page="submit_expense",
    )


@app.route("/expenses/<int:expense_id>/delete", methods=["POST"])
@role_required("employee", "manager")
def delete_expense(expense_id):
    return_endpoint = "my_expenses" if session["role_key"] == "manager" else "expenses"
    connection = cursor = None
    try:
        connection = get_db_connection()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT status FROM expenses
            WHERE expense_id = %s AND employee_id = %s
            FOR UPDATE
            """,
            (expense_id, session["employee_id"]),
        )
        expense = cursor.fetchone()
        if not expense:
            connection.rollback()
            flash("Expense not found.", "error")
            return redirect(url_for(return_endpoint))
        allowed_pending_statuses = (
            {"Pending", "Pending Admin"}
            if session["role_key"] == "manager"
            else {"Pending"}
        )
        if expense["status"] not in allowed_pending_statuses:
            connection.rollback()
            flash("Only pending expenses can be cancelled.", "error")
            return redirect(url_for(return_endpoint))
        cursor.execute(
            "DELETE FROM expenses WHERE expense_id = %s AND employee_id = %s",
            (expense_id, session["employee_id"]),
        )
        connection.commit()
        flash("Pending expense was cancelled.", "success")
    except mysql.connector.Error as error:
        if connection:
            connection.rollback()
        print("Expense cancellation failed:", error)
        flash("The expense could not be cancelled. It may be referenced by another record.", "error")
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    return redirect(url_for(return_endpoint))


@app.route("/approvals")
@role_required("manager")
def approvals():
    return redirect(url_for("expenses"))


@app.route("/employee-expenses")
@role_required("manager")
def employee_expenses():
    return redirect(url_for("expenses"))


@app.route("/approvals/<int:expense_id>", methods=["POST"])
@role_required("manager")
def decide_expense(expense_id):
    refresh_manager_profile()
    decision = request.form.get("decision", "").strip()
    remarks = request.form.get("remarks", "").strip()
    return_url = url_for("expenses")
    if decision not in ("Approved", "Rejected"):
        flash("Choose Approve or Reject for this expense.", "error")
        return redirect(return_url)
    if decision == "Rejected" and not remarks:
        flash("Add a short reason before rejecting an expense.", "error")
        return redirect(return_url)

    connection = cursor = None
    try:
        connection = get_db_connection()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            """
            SELECT e.expense_id, e.status
            FROM expenses e
            INNER JOIN employees emp ON emp.employee_id = e.employee_id
            WHERE e.expense_id = %s AND emp.department_id = %s
              AND e.employee_id <> %s
            FOR UPDATE
            """,
            (expense_id, session.get("department_id"), session["employee_id"]),
        )
        expense = cursor.fetchone()
        if not expense:
            connection.rollback()
            flash("Expense not found in your department.", "error")
            return redirect(return_url)
        if expense["status"] != "Pending":
            connection.rollback()
            flash("This expense has already been reviewed.", "warning")
            return redirect(return_url)

        cursor.execute(
            "UPDATE expenses SET status = %s WHERE expense_id = %s",
            (decision, expense_id),
        )
        cursor.execute(
            """
            INSERT INTO approvals (expense_id, manager_id, decision, remarks, approval_date)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            """,
            (expense_id, session["user_id"], decision, remarks or None),
        )
        connection.commit()
        flash("Expense #{0} was {1}.".format(expense_id, decision.lower()), "success")
    except mysql.connector.Error as error:
        if connection:
            connection.rollback()
        print("Expense approval failed:", error)
        flash("The decision could not be saved. Please try again.", "error")
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    return redirect(return_url)


@app.route("/manager-approvals")
@admin_required
def manager_approvals():
    receipt_file_expression = expense_receipt_file_expression()
    manager_expense_condition = manager_expense_predicate()
    pending = fetch_all(
        ("""
        SELECT e.expense_id, DATE_FORMAT(e.expense_date, '%Y-%m-%d') AS expense_date,
               cat.category_name, e.description, e.receipt_reference,
               {receipt_file_expression}, e.amount, e.status,
               CONCAT_WS(' ', emp.first_name, emp.last_name) AS employee_name,
               dep.department_name
        """ + expense_joins() + """
        WHERE (e.status = 'Pending Admin'
               OR (e.status = 'Pending' AND {manager_expense_condition}))
          AND {manager_expense_condition}
        ORDER BY e.expense_date, e.expense_id
        LIMIT 300
        """).format(
            receipt_file_expression=receipt_file_expression,
            manager_expense_condition=manager_expense_condition,
        )
    )
    return render_template(
        "manager_approvals.html",
        pending_expenses=pending,
        active_page="manager_approvals",
    )


@app.route("/manager-approvals/<int:expense_id>", methods=["POST"])
@admin_required
def decide_manager_expense(expense_id):
    decision = request.form.get("decision", "").strip()
    remarks = request.form.get("remarks", "").strip()
    if decision not in ("Approved", "Rejected"):
        flash("Choose Approve or Reject for this expense.", "error")
        return redirect(url_for("manager_approvals"))
    if decision == "Rejected" and not remarks:
        flash("Add a short reason before rejecting an expense.", "error")
        return redirect(url_for("manager_approvals"))

    connection = cursor = None
    try:
        connection = get_db_connection()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)
        manager_expense_condition = manager_expense_predicate(cursor)
        cursor.execute(
            ("SELECT e.expense_id, e.status FROM expenses e "
             "WHERE e.expense_id = %s "
             "AND (e.status = 'Pending Admin' OR e.status = 'Pending') "
             "AND {} FOR UPDATE").format(
                manager_expense_condition
            ),
            (expense_id,),
        )
        expense = cursor.fetchone()
        if not expense:
            connection.rollback()
            flash("Manager expense was not found.", "error")
            return redirect(url_for("manager_approvals"))
        cursor.execute(
            "UPDATE expenses SET status = %s WHERE expense_id = %s",
            (decision, expense_id),
        )
        cursor.execute(
            """
            INSERT INTO approvals (expense_id, manager_id, decision, remarks, approval_date)
            VALUES (%s, %s, %s, %s, CURRENT_TIMESTAMP)
            """,
            (expense_id, session["user_id"], decision, remarks or None),
        )
        connection.commit()
        flash(
            "Manager expense #{0} was {1}.".format(expense_id, decision.lower()),
            "success",
        )
    except mysql.connector.Error as error:
        if connection:
            connection.rollback()
        print("Manager expense approval failed:", error)
        flash("The decision could not be saved. Please try again.", "error")
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    return redirect(url_for("manager_approvals"))


@app.route("/reimbursements")
@role_required("finance")
def reimbursements():
    approved = fetch_all(
        """
        SELECT e.expense_id, DATE_FORMAT(e.expense_date, '%Y-%m-%d') AS expense_date,
               cat.category_name, e.amount,
               CONCAT_WS(' ', emp.first_name, emp.last_name) AS employee_name,
               dep.department_name
        """ + expense_joins() + """
        WHERE e.status = 'Approved'
        ORDER BY e.expense_date, e.expense_id
        LIMIT 500
        """
    )
    amount_column, _ = reimbursement_column_names()
    amount_expression = "r.`{}`".format(amount_column)
    processed = fetch_all(
        """
        SELECT e.expense_id, {amount_expression} AS amount,
               DATE_FORMAT(r.reimbursement_date, '%Y-%m-%d') AS reimbursement_date,
               CONCAT_WS(' ', emp.first_name, emp.last_name) AS employee_name
        FROM reimbursements r
        INNER JOIN expenses e ON e.expense_id = r.expense_id
        INNER JOIN employees emp ON emp.employee_id = e.employee_id
        ORDER BY r.reimbursement_date DESC, r.reimbursement_id DESC
        LIMIT 100
        """.format(amount_expression=amount_expression)
    )
    return render_template(
        "reimbursements.html",
        approved_expenses=approved,
        processed_reimbursements=processed,
        active_page="reimbursements",
    )


@app.route("/reimbursements/<int:expense_id>/process", methods=["POST"])
@role_required("finance")
def process_reimbursement(expense_id):
    connection = cursor = None
    try:
        connection = get_db_connection()
        connection.start_transaction()
        cursor = connection.cursor(dictionary=True)
        cursor.execute(
            "SELECT expense_id, amount, status FROM expenses WHERE expense_id = %s FOR UPDATE",
            (expense_id,),
        )
        expense = cursor.fetchone()
        if not expense:
            connection.rollback()
            flash("Expense not found.", "error")
            return redirect(url_for("reimbursements"))
        if expense["status"] != "Approved":
            connection.rollback()
            flash("Only approved expenses can be reimbursed.", "error")
            return redirect(url_for("reimbursements"))

        reimbursement_schema = table_columns(cursor, "reimbursements")
        amount_column, status_column = reimbursement_column_names(cursor)
        insert_columns = ["expense_id", "processed_by", amount_column]
        insert_values = ["%s", "%s", "%s"]
        insert_parameters = [expense_id, session["user_id"], expense["amount"]]
        if "reimbursement_date" in reimbursement_schema:
            insert_columns.append("reimbursement_date")
            insert_values.append("CURRENT_TIMESTAMP")
        if status_column:
            insert_columns.append(status_column)
            insert_values.append("%s")
            insert_parameters.append("Processed")
        cursor.execute(
            "INSERT INTO reimbursements ({}) VALUES ({})".format(
                ", ".join("`{}`".format(column) for column in insert_columns),
                ", ".join(insert_values),
            ),
            tuple(insert_parameters),
        )
        cursor.execute(
            "UPDATE expenses SET status = 'Reimbursed' WHERE expense_id = %s",
            (expense_id,),
        )
        connection.commit()
        flash("Reimbursement for expense #{0} was processed.".format(expense_id), "success")
    except mysql.connector.Error as error:
        if connection:
            connection.rollback()
        print("Reimbursement transaction failed:", error)
        flash("Reimbursement failed. No changes were committed; please try again.", "error")
    finally:
        if cursor:
            cursor.close()
        if connection and connection.is_connected():
            connection.close()
    return redirect(url_for("reimbursements"))


@app.route("/reports/expenses.csv")
@role_required("finance")
def export_expenses_csv():
    rows = fetch_all(
        """
        SELECT e.expense_id,
               CONCAT_WS(' ', emp.first_name, emp.last_name) AS employee_name,
               dep.department_name, cat.category_name,
               DATE_FORMAT(e.expense_date, '%Y-%m-%d') AS expense_date,
               e.description, e.receipt_reference, e.amount, e.payment_method, e.status
        """ + expense_joins() + " ORDER BY e.expense_date DESC, e.expense_id DESC"
    )
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    writer.writerow((
        "Expense ID", "Employee", "Department", "Category", "Expense date",
        "Description", "Receipt reference", "Amount", "Payment method", "Status",
    ))
    for row in rows:
        writer.writerow(csv_safe_cell(value) for value in (
            row["expense_id"], row["employee_name"], row["department_name"],
            row["category_name"], row["expense_date"], row["description"],
            row["receipt_reference"], row["amount"], row["payment_method"], row["status"],
        ))
    filename = "expense-report-{0}.csv".format(date.today().isoformat())
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename={0}".format(filename)},
    )


@app.route("/analytics")
@role_required("employee", "manager", "finance")
def analytics():
    scope, values = expense_scope()
    title = {
        "employee": "Personal analytics",
        "manager": "Department analytics",
        "finance": "Financial analytics",
    }[session["role_key"]]
    return render_analytics(scope, values, title, "analytics")


@app.route("/my-analytics")
@role_required("manager")
def my_analytics():
    return render_analytics(
        "e.employee_id = %s",
        (session["employee_id"],),
        "Personal analytics",
        "my_analytics",
    )


def render_analytics(scope, values, title, active_page):
    year_rows = fetch_all(
        """
        SELECT DISTINCT YEAR(e.expense_date) AS year
        """ + expense_joins() + """
        WHERE """ + scope + """
        ORDER BY year DESC
        LIMIT 10
        """,
        values,
    )
    available_years = [int(row["year"]) for row in year_rows if row["year"] is not None]
    selected_year = request.args.get("year", "").strip()
    try:
        selected_year = int(selected_year) if selected_year else date.today().year
    except ValueError:
        selected_year = date.today().year
    if selected_year not in available_years:
        available_years.insert(0, selected_year)
    available_years = sorted(set(available_years), reverse=True)

    summary = fetch_one(
        """
        SELECT COUNT(e.expense_id) AS total_count,
               COALESCE(SUM(e.amount), 0) AS total_amount,
               COALESCE(AVG(e.amount), 0) AS average_amount,
               COALESCE(MAX(e.amount), 0) AS highest_amount,
               COALESCE(MIN(e.amount), 0) AS lowest_amount,
               COALESCE(SUM(CASE WHEN e.status IN ('Pending', 'Pending Admin') THEN e.amount ELSE 0 END), 0) AS pending_amount
        """ + expense_joins() + " WHERE " + scope,
        values,
    ) or {}
    reimbursement_amount_column, _ = reimbursement_column_names()
    reimbursement_amount_expression = "r.`{}`".format(
        reimbursement_amount_column
    )
    reimbursed = fetch_one(
        ("""
        SELECT COALESCE(SUM({reimbursement_amount_expression}), 0) AS reimbursed_amount
        FROM reimbursements r
        INNER JOIN expenses e ON e.expense_id = r.expense_id
        INNER JOIN employees emp ON emp.employee_id = e.employee_id
        WHERE """ + scope).format(
            reimbursement_amount_expression=reimbursement_amount_expression
        ),
        values,
    )
    summary["reimbursed_amount"] = reimbursed["reimbursed_amount"] if reimbursed else 0

    categories = fetch_all(
        """
        SELECT cat.category_name AS label, SUM(e.amount) AS total
        """ + expense_joins() + """
        WHERE """ + scope + """
        GROUP BY cat.category_id, cat.category_name
        HAVING COUNT(e.expense_id) > 0
        ORDER BY total DESC
        """,
        values,
    )
    departments = fetch_all(
        """
        SELECT COALESCE(dep.department_name, 'Unassigned') AS label,
               SUM(e.amount) AS total
        """ + expense_joins() + """
        WHERE """ + scope + """
        GROUP BY dep.department_id, dep.department_name
        ORDER BY total DESC
        """,
        values,
    )
    statuses = fetch_all(
        """
        SELECT e.status AS label, COUNT(e.expense_id) AS total
        """ + expense_joins() + """
        WHERE """ + scope + """
        GROUP BY e.status
        ORDER BY e.status
        """,
        values,
    )
    chart_data = load_charts(selected_year, scope, values)
    chart_data["department"] = {
        "labels": [row["label"] for row in departments],
        "values": [float(row["total"] or 0) for row in departments],
    }
    chart_data["status"] = {
        "labels": [row["label"] for row in statuses],
        "values": [int(row["total"] or 0) for row in statuses],
    }
    return render_template(
        "analytics.html",
        summary=summary,
        charts=chart_data,
        available_years=available_years or [date.today().year],
        selected_year=selected_year,
        analytics_title=title,
        active_page=active_page,
    )


@app.errorhandler(DatabaseUnavailable)
def database_unavailable(_error):
    return (
        "<h1>Database unavailable</h1>"
        "<p>Could not complete the request. Check the MySQL connection settings and try again.</p>"
        '<p><a href="/login">Return to sign in</a></p>',
        503,
    )


@app.errorhandler(404)
def not_found(_error):
    return (
        "<h1>Page not found</h1><p>The requested record or page could not be found.</p>"
        '<p><a href="/dashboard">Return to dashboard</a></p>',
        404,
    )


@app.errorhandler(413)
def upload_too_large(_error):
    return (
        "<h1>Upload too large</h1><p>Receipt files must be no larger than 5 MB.</p>"
        '<p><a href="/expenses/new">Return to expense submission</a></p>',
        413,
    )


if __name__ == "__main__":
    app.run(debug=os.getenv("FLASK_DEBUG", "").lower() == "true")
