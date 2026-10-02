USE corporate_expense_db;

-- Add the profile fields only when neither users nor employees already stores them.
SET @signup_mobile_exists = (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME IN ('users', 'employees')
      AND COLUMN_NAME IN (
          'mobile_no', 'mobile_number', 'phone', 'phone_number',
          'contact_no', 'contact_number', 'mobile', 'phone_no'
      )
);
SET @signup_mobile_sql = IF(
    @signup_mobile_exists = 0,
    'ALTER TABLE employees ADD COLUMN mobile_no VARCHAR(20) NULL',
    'SELECT 1'
);
PREPARE signup_mobile_stmt FROM @signup_mobile_sql;
EXECUTE signup_mobile_stmt;
DEALLOCATE PREPARE signup_mobile_stmt;

SET @signup_gender_exists = (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME IN ('users', 'employees')
      AND COLUMN_NAME = 'gender'
);
SET @signup_gender_sql = IF(
    @signup_gender_exists = 0,
    'ALTER TABLE employees ADD COLUMN gender VARCHAR(30) NULL',
    'SELECT 1'
);
PREPARE signup_gender_stmt FROM @signup_gender_sql;
EXECUTE signup_gender_stmt;
DEALLOCATE PREPARE signup_gender_stmt;
