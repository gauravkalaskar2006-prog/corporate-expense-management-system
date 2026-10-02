import os
import mysql.connector


def get_db_connection():
    """Connect to the MySQL database configured outside the source code."""
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        user=os.getenv("MYSQL_USER", "root"),
        password=os.getenv("MYSQL_PASSWORD", "YOUR_PASSWORD"),
        database="corporate_expense_db",
        charset="utf8mb4",
        autocommit=False,
    )
