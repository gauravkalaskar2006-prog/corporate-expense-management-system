USE corporate_expense_db;

SET @receipt_reference_exists = (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'expenses'
      AND COLUMN_NAME = 'receipt_reference'
);
SET @receipt_reference_sql = IF(
    @receipt_reference_exists = 0,
    'ALTER TABLE expenses ADD COLUMN receipt_reference VARCHAR(255) NULL',
    'SELECT 1'
);
PREPARE receipt_reference_stmt FROM @receipt_reference_sql;
EXECUTE receipt_reference_stmt;
DEALLOCATE PREPARE receipt_reference_stmt;

SET @receipt_file_exists = (
    SELECT COUNT(*)
    FROM INFORMATION_SCHEMA.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE()
      AND TABLE_NAME = 'expenses'
      AND COLUMN_NAME = 'receipt_file'
);
SET @receipt_file_sql = IF(
    @receipt_file_exists = 0,
    'ALTER TABLE expenses ADD COLUMN receipt_file VARCHAR(255) NULL',
    'SELECT 1'
);
PREPARE receipt_file_stmt FROM @receipt_file_sql;
EXECUTE receipt_file_stmt;
DEALLOCATE PREPARE receipt_file_stmt;
