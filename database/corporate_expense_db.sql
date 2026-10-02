-- Corporate Expense & Reimbursement Management System
-- Run this script in MySQL Workbench for a new installation.

CREATE DATABASE IF NOT EXISTS corporate_expense_db
  CHARACTER SET utf8mb4
  COLLATE utf8mb4_unicode_ci;
USE corporate_expense_db;

CREATE TABLE IF NOT EXISTS departments (
  department_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  department_name VARCHAR(100) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (department_id),
  UNIQUE KEY uq_departments_name (department_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS users (
  user_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  username VARCHAR(50) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role VARCHAR(32) NOT NULL DEFAULT 'Employee',
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_id),
  UNIQUE KEY uq_users_username (username),
  KEY ix_users_role (role)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS employees (
  employee_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  user_id INT UNSIGNED NOT NULL,
  department_id INT UNSIGNED NOT NULL,
  first_name VARCHAR(80) NOT NULL,
  last_name VARCHAR(80) NOT NULL,
  email VARCHAR(254) NULL,
  mobile_no VARCHAR(20) NOT NULL,
  gender VARCHAR(30) NOT NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (employee_id),
  UNIQUE KEY uq_employees_user (user_id),
  KEY ix_employees_department (department_id),
  CONSTRAINT fk_employees_user
    FOREIGN KEY (user_id) REFERENCES users (user_id)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT fk_employees_department
    FOREIGN KEY (department_id) REFERENCES departments (department_id)
    ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS expense_categories (
  category_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  category_name VARCHAR(100) NOT NULL,
  description VARCHAR(255) NULL,
  PRIMARY KEY (category_id),
  UNIQUE KEY uq_expense_categories_name (category_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS expenses (
  expense_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  employee_id INT UNSIGNED NOT NULL,
  category_id INT UNSIGNED NOT NULL,
  expense_date DATE NOT NULL,
  description VARCHAR(500) NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  payment_method VARCHAR(30) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'Pending',
  receipt_reference VARCHAR(255) NULL,
  receipt_file VARCHAR(255) NULL,
  created_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  updated_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
  PRIMARY KEY (expense_id),
  KEY ix_expenses_employee_date (employee_id, expense_date),
  KEY ix_expenses_category (category_id),
  KEY ix_expenses_status_date (status, expense_date),
  CONSTRAINT fk_expenses_employee
    FOREIGN KEY (employee_id) REFERENCES employees (employee_id)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT fk_expenses_category
    FOREIGN KEY (category_id) REFERENCES expense_categories (category_id)
    ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS approvals (
  approval_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  expense_id INT UNSIGNED NOT NULL,
  manager_id INT UNSIGNED NOT NULL,
  decision VARCHAR(20) NOT NULL,
  remarks VARCHAR(500) NULL,
  approval_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (approval_id),
  KEY ix_approvals_expense_date (expense_id, approval_date),
  KEY ix_approvals_manager_date (manager_id, approval_date),
  CONSTRAINT fk_approvals_expense
    FOREIGN KEY (expense_id) REFERENCES expenses (expense_id)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT fk_approvals_manager
    FOREIGN KEY (manager_id) REFERENCES users (user_id)
    ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS reimbursements (
  reimbursement_id INT UNSIGNED NOT NULL AUTO_INCREMENT,
  expense_id INT UNSIGNED NOT NULL,
  processed_by INT UNSIGNED NOT NULL,
  amount DECIMAL(12,2) NOT NULL,
  reimbursement_date TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
  status VARCHAR(30) NOT NULL DEFAULT 'Processed',
  PRIMARY KEY (reimbursement_id),
  UNIQUE KEY uq_reimbursements_expense (expense_id),
  KEY ix_reimbursements_date (reimbursement_date),
  KEY ix_reimbursements_processor (processed_by),
  CONSTRAINT fk_reimbursements_expense
    FOREIGN KEY (expense_id) REFERENCES expenses (expense_id)
    ON UPDATE CASCADE ON DELETE RESTRICT,
  CONSTRAINT fk_reimbursements_processor
    FOREIGN KEY (processed_by) REFERENCES users (user_id)
    ON UPDATE CASCADE ON DELETE RESTRICT
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT IGNORE INTO departments (department_name) VALUES
  ('Engineering'),
  ('Finance'),
  ('Human Resources'),
  ('Marketing'),
  ('Operations');

INSERT IGNORE INTO expense_categories (category_name, description) VALUES
  ('Travel', 'Business travel, fares, and mileage'),
  ('Meals', 'Meals during approved business activities'),
  ('Accommodation', 'Hotel and lodging expenses'),
  ('Transportation', 'Local business transportation'),
  ('Office Supplies', 'Supplies and small office purchases'),
  ('Communication', 'Business phone and internet expenses'),
  ('Training', 'Workshops, courses, and certifications'),
  ('Other', 'Other business-related expenses');

-- Public sign-up creates Employee accounts. To promote a signed-up employee,
-- update the role value to Manager, Finance, or Admin in MySQL Workbench.
-- Example: UPDATE users SET role = 'Manager' WHERE username = 'manager_username';
-- Example: UPDATE users SET role = 'Finance' WHERE username = 'finance_username';
