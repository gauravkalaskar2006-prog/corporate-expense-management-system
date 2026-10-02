from db import get_db_connection

try:
    connection = get_db_connection()

    if connection.is_connected():
        print("Database connected successfully!")

    connection.close()

except Exception as e:
    print("Database connection failed:")
    print(e)