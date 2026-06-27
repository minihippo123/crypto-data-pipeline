def ping(engine) -> bool:
    with engine.connect() as connection:
        return connection.exec_driver_sql("SELECT 1").scalar_one() == 1
