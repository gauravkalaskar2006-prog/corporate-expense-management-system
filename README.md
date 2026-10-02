# Corporate Expense and Reimbursement Management System

A Flask application for employee expense claims, manager approvals, and finance reimbursements. It uses MySQL, HTML, CSS, JavaScript, and Chart.js.

## Database setup

Create and manage the MySQL database directly in MySQL Workbench. The Flask application does not read SQL files from the project. The table and column requirements, keys, relationships, and account data flow are documented in [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md).

Create the database with the name `corporate_expense_db` and create its seven required tables: `users`, `employees`, `departments`, `expense_categories`, `expenses`, `approvals`, and `reimbursements`. Seed `departments` and `expense_categories` with the values described in the schema report. The application expects the receipt columns `receipt_reference` and `receipt_file` in `expenses`.

## Configure and run

Install packages with `pip install -r requirements.txt`. Configure the current PowerShell terminal, replacing the password and session key with your own values:

```powershell
$env:MYSQL_HOST = "localhost"
$env:MYSQL_USER = "root"
$env:MYSQL_PASSWORD = "your-MySQL-password"
$env:FLASK_SECRET_KEY = "your-private-random-key"
```

Then run `python app.py` from this folder and open http://127.0.0.1:5000.

## Accounts and roles

Signup creates an Employee account. The username, password hash, and role are stored in `users`; profile details and department membership are stored in the linked `employees` row. Sign-in checks the existing `users` row and does not create another database record. Passwords are hashed by the application before storage; never save plain-text passwords.

To provision a manager or finance/admin account, register that person first, then update their `users.role` in Workbench. For example:

```sql
UPDATE users SET role = 'Manager' WHERE username = 'manager_username';
UPDATE users SET role = 'Finance' WHERE username = 'finance_username';
UPDATE users SET role = 'Admin' WHERE username = 'admin_username';
```

Managers need an employee profile assigned to the department they manage. The login selector groups Finance and Admin into one choice; the database stores either role separately.

## Application features

- Employees can manage their profile, submit expenses and receipts, track reimbursements, and view personal analytics.
- Managers can do employee tasks and review, approve, or reject employee expenses in their department with remarks. Their own expense claims are sent to Admin for review.
- Admin users can review, approve, or reject manager expense claims. Finance/Admin users can review all expenses, process reimbursements, view financial analytics, monitor pending payments, and download CSV reports.

Receipt uploads accept PDF, PNG, and JPEG files up to 5 MB. Files are stored in the Flask instance folder and are only served to users allowed to view the expense.
