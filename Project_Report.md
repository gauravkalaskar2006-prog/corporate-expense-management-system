# Corporate Expense and Reimbursement Management System

## Project Report

**Submitted by:** ______________________________  
**Roll number:** ________________________________  
**Course / class:** _____________________________  
**Submitted to:** _______________________________  
**Department / college:** _______________________  
**Academic year:** ______________________________

---

## Abstract

The Corporate Expense and Reimbursement Management System is a web application for recording employee business expenses and managing their review and reimbursement. Employees submit claims with a category, date, description, amount, payment method, and optional receipt information or file. Managers review claims from their department, while an Admin reviews claims submitted by managers. Finance and Admin users can view organization-wide claims, record reimbursements, review financial summaries, and download a CSV report.

The application is built with Python and Flask, uses MySQL for persistent data, and renders pages with HTML templates, CSS, and JavaScript. Chart.js is used for expense charts. Its seven-table relational database separates accounts, employee profiles, departments, categories, expenses, approval decisions, and reimbursement records. This separation supports consistent data, role-based access, and a history of financial actions.

This report describes the project based on the source code, SQL setup, and documentation in the project folder. It does not claim that the application was run against a configured MySQL server.

## Table of Contents

1. Introduction
2. Problem Statement
3. Objectives and Scope
4. System Analysis
5. Architecture and Technologies
6. Functional Modules and Workflows
7. Database Design
8. Security and Data Integrity
9. Interface and Reporting
10. Benefits, Limitations, and Future Enhancements
11. Verification Plan
12. Conclusion
13. Project References

## 1. Introduction

Organizations regularly need to collect employee expense claims, verify that claims are appropriate, and track whether approved expenses have been reimbursed. A manual process based on paper forms, email, or spreadsheets can make it difficult to find receipts, identify the current reviewer, prevent duplicate processing, and prepare consistent summaries.

This project provides a centralized workflow for those tasks. The application records each claim in MySQL and assigns the next action according to the account role and claim status. An employee can track their own claims, a manager can review claims within their department, and finance staff can process approved expenses. Admin accounts also review claims submitted by managers.

## 2. Problem Statement

An organization needs a structured way to collect and review employee expenses while maintaining traceable records. Without a central system, expense details and receipts may be scattered across documents and messages. Review decisions, reasons for rejection, and reimbursement status can be hard to track. Managers and finance staff may also lack a current view of pending claims and spending patterns.

The project addresses these problems by storing claims and workflow records in a relational database and providing web pages for submission, approval, reimbursement tracking, analytics, and CSV export.

## 3. Objectives and Scope

### Objectives

- Provide employee account registration and sign-in.
- Record employee profiles, departments, and account roles.
- Allow employees and managers to submit expense claims and optional receipts.
- Let managers review claims from their own department and record a decision and remarks.
- Route manager-submitted expenses for Admin review.
- Let Finance/Admin users record reimbursements for approved claims.
- Give users access to relevant expense lists, details, reimbursement history, and analytics.
- Maintain relational links and database constraints for important records.
- Provide an organization-wide CSV expense report for Finance/Admin users.

### Scope

The implemented system covers claim submission, review, status tracking, reimbursement record creation, receipt storage, analytics, and report export. Public registration creates an Employee account. Manager, Finance, and Admin roles are assigned to registered accounts by an administrator through the database.

The application records a reimbursement as processed; it does not connect to a bank, payment provider, or payroll platform. The profile page displays account details but does not provide an edit form. Role administration is performed outside the web interface.

## 4. System Analysis

### Users and access levels

| User role | Main capabilities |
| --- | --- |
| Employee | View personal dashboard and expenses, submit claims and receipts, cancel eligible pending claims, view reimbursement history and personal analytics. |
| Manager | Use employee functions, view department claims, review other employees' pending claims in the manager's department, and view department analytics. A manager's own claims are routed to Admin. |
| Finance | View organization-wide expenses, inspect analytics, process approved claims into reimbursement records, and export expenses as CSV. |
| Admin | Use finance capabilities and review manager expense claims. |

The application checks the signed-in role in its Flask routes and scopes expense queries by employee, department, or organization. Admin is treated as a Finance role for organization-wide operations, with a separate Admin-only check for manager-claim review.

### Core workflow

```text
Employee submits a claim
    -> Pending
    -> Manager approves or rejects (with a reason required for rejection)
    -> If approved: Finance/Admin processes reimbursement
    -> Reimbursed

Manager submits a personal claim
    -> Pending Admin
    -> Admin approves or rejects (with a reason required for rejection)
    -> If approved: Finance/Admin processes reimbursement
    -> Reimbursed
```

Rejected claims retain their decision and remarks in the approval history. A claim can be deleted by its owner only while it is in an eligible pending state. Reimbursement processing checks that the claim is approved and updates the expense and reimbursement tables in one database transaction.

### Main inputs and outputs

**Inputs:** registration details, credentials, department selection, expense date, category, description, amount, payment method, receipt reference, receipt file, and approval decision/remarks.

**Outputs:** dashboards, filtered expense lists, expense detail pages, approval queues, reimbursement history, chart summaries, confirmation messages, and downloadable CSV files.

## 5. Architecture and Technologies

The project uses a three-part web application structure:

```text
Web browser
  HTML templates + CSS + JavaScript + Chart.js
             | HTTP requests and rendered pages
Flask application (app.py)
  Authentication, role checks, validation, workflow, SQL queries
             | MySQL Connector/Python
MySQL database (corporate_expense_db)
  Seven related InnoDB tables
```

| Component | Use in the project |
| --- | --- |
| Python | Application logic and database workflow. |
| Flask | Routes, sessions, form handling, and template rendering. |
| MySQL / InnoDB | Persistent relational storage, transactions, foreign keys, and indexes. |
| MySQL Connector/Python | Connects the Flask application to MySQL. |
| HTML/Jinja templates | Login, signup, dashboards, forms, lists, detail pages, and reports. |
| CSS | Page layout and visual styling. |
| JavaScript | Table sorting and chart initialization. |
| Chart.js | Monthly, category, status, and department charts; loaded by the pages from a CDN. |

The main implementation is in `app.py`; database connection settings are in `db.py`; the fresh-install schema is in `database/corporate_expense_db.sql`; and the page templates and static assets are stored in `templates/` and `static/`.

## 6. Functional Modules and Workflows

### 6.1 Registration, login, and sessions

Signup validates basic profile information, verifies that a selected department exists, checks password length and confirmation, hashes the password with Werkzeug, and inserts the user and employee profile in a transaction. The public signup form creates an Employee role. Login checks both credentials and the selected role before storing the user identity and role in the Flask session. Logout clears the session.

### 6.2 Expense submission and receipt handling

An Employee or Manager can select an expense category and payment method, enter an expense date, description, and positive amount, and optionally add a receipt reference or upload a receipt. Future dates are rejected. The accepted file extensions are PDF, PNG, JPG, and JPEG, and Flask limits request uploads to 5 MB. Receipt files are saved in the Flask instance directory under a generated filename. The stored receipt is served through a route that checks the user's access to the related expense.

### 6.3 Expense review

Managers see pending claims belonging to other employees in their own department. They can approve or reject a claim; a reason is required for rejection. The current claim status is updated and an approval row records the reviewer, decision, remarks, and date. Admin users have a separate queue for manager claims.

### 6.4 Reimbursement processing

Finance/Admin users see approved claims and may process them. The application locks the expense row, confirms the current status is Approved, inserts a reimbursement record, changes the expense status to Reimbursed, and commits both changes together. The unique constraint on reimbursement `expense_id` helps prevent more than one reimbursement record for the same claim.

### 6.5 Dashboards and analytics

Dashboards summarize claims according to the user's role. Analytics include counts and monetary summaries, average/highest/lowest expense values, pending and reimbursed amounts, and chart breakdowns by month, category, status, and department. Employee views use the employee's claims; manager views can be personal or department-scoped; Finance/Admin views cover the organization.

The year selector filters monthly and category chart data. The KPI summaries and status/department breakdowns are calculated over the selected user's full accessible record set, rather than being restricted to the selected year.

### 6.6 CSV export

Finance/Admin users can download an organization-wide CSV containing expense ID, employee, department, category, date, description, receipt reference, amount, payment method, and status. The export code prefixes cells that begin with common spreadsheet formula characters to reduce CSV formula-injection risk.

## 7. Database Design

The database is named `corporate_expense_db`. The SQL setup creates seven tables using InnoDB and the `utf8mb4` character set.

### Entity relationship summary

```text
departments 1 ---- many employees
users       1 ---- 1    employees
employees   1 ---- many expenses
expense_categories 1 -- many expenses
expenses    1 ---- many approvals
users       1 ---- many approvals (reviewing account)
expenses    1 ---- 0..1 reimbursements
users       1 ---- many reimbursements (processing account)
```

### Tables and responsibilities

| Table | Purpose and important data |
| --- | --- |
| `users` | Unique username, password hash, role, and account creation time. |
| `employees` | Employee profile and department. A unique `user_id` links each profile to one account. |
| `departments` | Unique department names used for signup and manager scoping. |
| `expense_categories` | Unique category names and optional descriptions. The starter data includes Travel, Meals, Accommodation, Transportation, Office Supplies, Communication, Training, and Other. |
| `expenses` | Claim owner, category, date, description, amount, payment method, status, receipt fields, and timestamps. |
| `approvals` | Approval/rejection event, reviewer account, remarks, and decision timestamp. Multiple rows can preserve decision history. |
| `reimbursements` | Processed expense, processing account, amount, date, and reimbursement status. A unique expense key prevents duplicate reimbursement rows. |

### Keys, constraints, and normalization

Each table has a primary key. Foreign keys connect employees to users and departments, expenses to employees and categories, approvals to expenses and reviewer accounts, and reimbursements to expenses and processing accounts. Foreign keys use `ON UPDATE CASCADE` and `ON DELETE RESTRICT`, protecting referenced financial history from accidental deletion. Useful indexes support role, department, employee/date, category, expense status/date, approval, and reimbursement lookups.

The design separates descriptive reference data (departments and categories) from transaction data (expenses, approvals, and reimbursements). It also stores credentials separately from employee profile details. This organization follows common relational normalization practices by reducing repeated text values and linking related facts with keys. Amounts use `DECIMAL(12,2)`, which is more appropriate for currency than floating-point storage.

## 8. Security and Data Integrity

The source code includes several protective measures:

- Passwords created through signup are hashed; SQL operations generally use parameterized values.
- Route decorators enforce login and role requirements, and expense queries are scoped to an employee, department, or Finance/Admin role.
- Approval and reimbursement updates use database transactions; reimbursement processing locks the selected expense row while checking its status.
- Database foreign keys and unique keys protect references and prevent duplicate usernames and reimbursement rows.
- Receipt uploads have a size limit, allow-listed extensions, generated storage names, and access checks when downloaded.
- Session cookies are configured as HTTP-only and SameSite=Lax.

The source also shows areas to harden before deployment. `db.py` and `app.py` contain development fallback values for the database password and Flask secret key; deployment should require private environment values and remove those fallbacks. The password verification helper retains a plain-text comparison path for legacy records, so stored accounts should use password hashes and legacy plain-text passwords should be migrated. The inspected forms do not show explicit CSRF tokens, and the session cookie is not configured with the Secure flag. Receipt validation is based mainly on filename extension rather than inspecting file content. These are recommendations for a production deployment, not claims that the application currently has those controls.

## 9. Interface and Reporting

The interface is divided by role and task. Templates include sign-in and signup, employee/manager/finance dashboards, expense submission and details, approval queues, reimbursement views, profile display, and analytics. The dashboards present key totals and recent claims. JavaScript enables in-page sorting of supported expense tables and initializes responsive Chart.js charts.

Reports available in the current code include visual analytics on the web pages and a downloadable CSV expense report. No PDF report-generation feature is present in the inspected source.

## 10. Benefits, Limitations, and Future Enhancements

### Benefits

- Centralizes employee expense information and receipt references.
- Makes review ownership and claim status visible.
- Separates employee, manager, and finance responsibilities.
- Preserves approval remarks and reimbursement records.
- Uses database transactions for multi-record account creation and reimbursement processing.
- Gives finance staff searchable records, aggregate analytics, and CSV export.

### Current limitations and suggested enhancements

1. **No integrated payment transfer:** reimbursement processing records the action but does not send money. A future version could integrate an approved payment or payroll service.
2. **Manual role administration:** elevated roles are provisioned through MySQL Workbench. An admin interface with audit logging could make role management safer and easier.
3. **Read-only profile:** users cannot edit their profile through the application. A validated profile update workflow could be added.
4. **Analytics year consistency:** the selected year affects some charts but not all KPI and breakdown queries. Applying the same year condition to every analytics section would make the selector behavior consistent.
5. **Production security controls:** require environment secrets, add CSRF protection, configure secure cookies for HTTPS, inspect uploaded content, and migrate any legacy plain-text passwords.
6. **Approval reviewer naming:** the `approvals.manager_id` field stores the account that made a decision, including an Admin account for manager claims. A clearer name such as `reviewer_user_id` would better represent both reviewer types.
7. **Automated coverage:** the included `test_db.py` is a database connection check rather than a workflow test suite. Automated tests could cover registration, role restrictions, claim submission, approval, and reimbursement behavior.
8. **Documentation alignment:** the README links to `DATABASE_SCHEMA.md`, while the schema report in the project is named `database/schema_report.md`. Updating that link would make setup documentation easier to follow.

## 11. Verification Plan

The project includes `test_db.py`, which attempts to connect to MySQL and prints whether the connection succeeds. It does not test the complete expense workflow. The following checks should be performed with a configured MySQL instance before presenting runtime results:

| Check | Expected result |
| --- | --- |
| Create a valid Employee account | A user row and linked employee row are committed. |
| Submit a valid employee claim | A claim is saved with status Pending. |
| Reject an employee claim without remarks | The decision is refused and the claim remains pending. |
| Manager reviews a claim from another department | The claim is not available for that manager's review. |
| Submit a manager claim | It is assigned status Pending Admin. |
| Process a pending or rejected expense as reimbursement | The request is refused; no reimbursement row is added. |
| Process an approved expense | One reimbursement row is created and the expense becomes Reimbursed. |
| Upload an unsupported or oversized receipt | The upload is rejected. |
| Download a receipt outside the permitted expense scope | The request is denied. |
| Export CSV as Employee or Manager | Access is denied; Finance/Admin can download it. |

**Verification status for this report:** source and schema inspection only. The application was not executed and the database-backed checks above are proposed test cases, not reported results.

## 12. Conclusion

The Corporate Expense and Reimbursement Management System provides a practical database-backed workflow for employee expense claims. Its role-aware pages support submission, department review, Admin review of manager claims, reimbursement recording, analytics, and CSV reporting. The seven-table MySQL schema gives the application a clear separation between user accounts, employee details, reference values, claims, approval history, and reimbursement transactions.

The project demonstrates the use of Flask routes, relational keys, SQL transactions, role-based access, input validation, file uploads, and dashboard reporting. Before production use, the project would benefit from stronger secret management and request protections, broader automated tests, and alignment between the documentation and current application behavior.

## 13. Project References

- `app.py` — Flask routes, validation, sessions, expense workflows, analytics, and CSV export.
- `db.py` — MySQL connection configuration.
- `database/corporate_expense_db.sql` — Fresh-install database schema and starter department/category data.
- `database/schema_report.md` — Detailed schema and relationship documentation.
- `templates/` — HTML/Jinja pages for forms, dashboards, approvals, and reporting.
- `static/css/style.css` — Application styling.
- `static/js/analytics.js` — Chart.js setup.
- `static/js/expenses.js` — Table sorting behavior.
- `requirements.txt` — Python package dependencies.
- `README.md` — Setup instructions and application feature overview.
