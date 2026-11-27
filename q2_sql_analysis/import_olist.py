import argparse
import csv
import os
from pathlib import Path
from getpass import getpass

import mysql.connector


# ============================================================
# 1. 基础配置
# ============================================================

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DATA_DIR = PROJECT_ROOT / "data" / "olist"

DATABASE = "olist"

BATCH_SIZE = 5000


DB_CONFIG = {
    "host": "127.0.0.1",
    "port": 3306,
    "user": "root",
    "password": None,
    "charset": "utf8mb4",
    "autocommit": False
}


# ============================================================
# 2. CSV 文件与 MySQL 表名
#    表名严格使用原始 CSV 文件名
# ============================================================

TABLE_FILES = {
    "olist_customers_dataset.csv":
        "olist_customers_dataset.csv",

    "olist_geolocation_dataset.csv":
        "olist_geolocation_dataset.csv",

    "olist_orders_dataset.csv":
        "olist_orders_dataset.csv",

    "olist_order_items_dataset.csv":
        "olist_order_items_dataset.csv",

    "olist_order_payments_dataset.csv":
        "olist_order_payments_dataset.csv",

    "olist_order_reviews_dataset.csv":
        "olist_order_reviews_dataset.csv",

    "olist_products_dataset.csv":
        "olist_products_dataset.csv",

    "olist_sellers_dataset.csv":
        "olist_sellers_dataset.csv",

    "product_category_name_translation.csv":
        "product_category_name_translation.csv"
}


# ============================================================
# 3. 原始字段结构
# ============================================================

EXPECTED_COLUMNS = {

    "olist_customers_dataset.csv": [
        "customer_id",
        "customer_unique_id",
        "customer_zip_code_prefix",
        "customer_city",
        "customer_state"
    ],

    "olist_geolocation_dataset.csv": [
        "geolocation_zip_code_prefix",
        "geolocation_lat",
        "geolocation_lng",
        "geolocation_city",
        "geolocation_state"
    ],

    "olist_orders_dataset.csv": [
        "order_id",
        "customer_id",
        "order_status",
        "order_purchase_timestamp",
        "order_approved_at",
        "order_delivered_carrier_date",
        "order_delivered_customer_date",
        "order_estimated_delivery_date"
    ],

    "olist_order_items_dataset.csv": [
        "order_id",
        "order_item_id",
        "product_id",
        "seller_id",
        "shipping_limit_date",
        "price",
        "freight_value"
    ],

    "olist_order_payments_dataset.csv": [
        "order_id",
        "payment_sequential",
        "payment_type",
        "payment_installments",
        "payment_value"
    ],

    "olist_order_reviews_dataset.csv": [
        "review_id",
        "order_id",
        "review_score",
        "review_comment_title",
        "review_comment_message",
        "review_creation_date",
        "review_answer_timestamp"
    ],

    "olist_products_dataset.csv": [
        "product_id",
        "product_category_name",
        "product_name_lenght",
        "product_description_lenght",
        "product_photos_qty",
        "product_weight_g",
        "product_length_cm",
        "product_height_cm",
        "product_width_cm"
    ],

    "olist_sellers_dataset.csv": [
        "seller_id",
        "seller_zip_code_prefix",
        "seller_city",
        "seller_state"
    ],

    "product_category_name_translation.csv": [
        "product_category_name",
        "product_category_name_english"
    ]
}


# ============================================================
# 4. 建表 SQL
# ============================================================

CREATE_TABLES = {

    "olist_customers_dataset.csv": """
        CREATE TABLE IF NOT EXISTS
        `olist_customers_dataset.csv` (

            customer_id CHAR(32) PRIMARY KEY,
            customer_unique_id CHAR(32) NOT NULL,
            customer_zip_code_prefix CHAR(5),
            customer_city VARCHAR(255),
            customer_state CHAR(2)

        ) ENGINE=InnoDB
        DEFAULT CHARSET=utf8mb4;
    """,

    "olist_geolocation_dataset.csv": """
        CREATE TABLE IF NOT EXISTS
        `olist_geolocation_dataset.csv` (

            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            geolocation_zip_code_prefix CHAR(5),
            geolocation_lat DOUBLE,
            geolocation_lng DOUBLE,
            geolocation_city VARCHAR(255),
            geolocation_state CHAR(2)

        ) ENGINE=InnoDB
        DEFAULT CHARSET=utf8mb4;
    """,

    "olist_orders_dataset.csv": """
        CREATE TABLE IF NOT EXISTS
        `olist_orders_dataset.csv` (

            order_id CHAR(32) PRIMARY KEY,
            customer_id CHAR(32) NOT NULL,
            order_status VARCHAR(30),
            order_purchase_timestamp DATETIME,
            order_approved_at DATETIME,
            order_delivered_carrier_date DATETIME,
            order_delivered_customer_date DATETIME,
            order_estimated_delivery_date DATETIME

        ) ENGINE=InnoDB
        DEFAULT CHARSET=utf8mb4;
    """,

    "olist_order_items_dataset.csv": """
        CREATE TABLE IF NOT EXISTS
        `olist_order_items_dataset.csv` (

            order_id CHAR(32) NOT NULL,
            order_item_id INT NOT NULL,
            product_id CHAR(32),
            seller_id CHAR(32),
            shipping_limit_date DATETIME,
            price DECIMAL(12,2),
            freight_value DECIMAL(12,2),

            PRIMARY KEY (order_id, order_item_id)

        ) ENGINE=InnoDB
        DEFAULT CHARSET=utf8mb4;
    """,

    "olist_order_payments_dataset.csv": """
        CREATE TABLE IF NOT EXISTS
        `olist_order_payments_dataset.csv` (

            order_id CHAR(32) NOT NULL,
            payment_sequential INT NOT NULL,
            payment_type VARCHAR(50),
            payment_installments INT,
            payment_value DECIMAL(12,2),

            PRIMARY KEY (order_id, payment_sequential)

        ) ENGINE=InnoDB
        DEFAULT CHARSET=utf8mb4;
    """,

    "olist_order_reviews_dataset.csv": """
        CREATE TABLE IF NOT EXISTS
        `olist_order_reviews_dataset.csv` (

            id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
            review_id CHAR(32),
            order_id CHAR(32),
            review_score INT,
            review_comment_title TEXT,
            review_comment_message TEXT,
            review_creation_date DATETIME,
            review_answer_timestamp DATETIME

        ) ENGINE=InnoDB
        DEFAULT CHARSET=utf8mb4;
    """,

    "olist_products_dataset.csv": """
        CREATE TABLE IF NOT EXISTS
        `olist_products_dataset.csv` (

            product_id CHAR(32) PRIMARY KEY,
            product_category_name VARCHAR(255),
            product_name_lenght INT,
            product_description_lenght INT,
            product_photos_qty INT,
            product_weight_g INT,
            product_length_cm INT,
            product_height_cm INT,
            product_width_cm INT

        ) ENGINE=InnoDB
        DEFAULT CHARSET=utf8mb4;
    """,

    "olist_sellers_dataset.csv": """
        CREATE TABLE IF NOT EXISTS
        `olist_sellers_dataset.csv` (

            seller_id CHAR(32) PRIMARY KEY,
            seller_zip_code_prefix CHAR(5),
            seller_city VARCHAR(255),
            seller_state CHAR(2)

        ) ENGINE=InnoDB
        DEFAULT CHARSET=utf8mb4;
    """,

    "product_category_name_translation.csv": """
        CREATE TABLE IF NOT EXISTS
        `product_category_name_translation.csv` (

            product_category_name VARCHAR(255) PRIMARY KEY,
            product_category_name_english VARCHAR(255)

        ) ENGINE=InnoDB
        DEFAULT CHARSET=utf8mb4;
    """
}


# ============================================================
# 5. 检查 CSV 文件及字段
# ============================================================

def validate_files():

    print("\n========== CSV 文件检查 ==========\n")

    for table_name, filename in TABLE_FILES.items():

        file_path = DATA_DIR / filename

        if not file_path.is_file():

            raise FileNotFoundError(
                f"文件不存在: {file_path}"
            )

        with file_path.open(
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as file:

            reader = csv.reader(file)

            header = next(reader)

            if header != EXPECTED_COLUMNS[table_name]:

                raise ValueError(
                    f"\n文件字段不匹配: {filename}\n"
                    f"实际字段: {header}\n"
                    f"预期字段: {EXPECTED_COLUMNS[table_name]}"
                )

        print(f"[文件检查通过] {filename}")

    print("\n9 个 CSV 文件全部检查通过。")


# ============================================================
# 6. 统计 CSV 实际记录数
# ============================================================

def count_csv_rows(file_path):

    total = 0

    with file_path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as file:

        reader = csv.reader(file)

        next(reader)

        for _ in reader:
            total += 1

    return total


# ============================================================
# 7. 空值处理
# ============================================================

def convert_value(value):

    if value == "":
        return None

    return value


# ============================================================
# 8. 创建数据库和数据表
# ============================================================

def create_database_and_tables(cursor, connection):

    cursor.execute(f"""
        CREATE DATABASE IF NOT EXISTS `{DATABASE}`
        CHARACTER SET utf8mb4
        COLLATE utf8mb4_0900_ai_ci
    """)

    cursor.execute(f"USE `{DATABASE}`")

    print("\n========== 数据表创建 ==========\n")

    for table_name, sql in CREATE_TABLES.items():

        cursor.execute(sql)

        print(f"[建表完成] {table_name}")

    connection.commit()


# ============================================================
# 9. 检查已有数据
# ============================================================

def check_existing_data(cursor, table_name, csv_count):

    cursor.execute(
        f"SELECT COUNT(*) FROM `{table_name}`"
    )

    db_count = cursor.fetchone()[0]

    if db_count == csv_count:

        print(
            f"[跳过] {table_name} "
            f"已有完整数据: {db_count:,} 行"
        )

        return True

    if db_count > 0:

        raise RuntimeError(
            f"\n数据不一致，停止导入：{table_name}\n"
            f"CSV 记录数: {csv_count:,}\n"
            f"MySQL 记录数: {db_count:,}\n"
            "请先检查数据，不自动删除或覆盖。"
        )

    return False


# ============================================================
# 10. 分批导入数据
# ============================================================

def import_table(
    connection,
    cursor,
    table_name,
    filename
):

    file_path = DATA_DIR / filename

    csv_count = count_csv_rows(file_path)

    print(f"\n开始检查: {table_name}")

    if check_existing_data(
        cursor,
        table_name,
        csv_count
    ):

        return csv_count

    print(f"[开始导入] 预计记录数: {csv_count:,}")

    total_rows = 0

    batch = []

    try:

        with file_path.open(
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as file:

            reader = csv.reader(file)

            columns = next(reader)

            column_sql = ", ".join(
                f"`{column}`" for column in columns
            )

            placeholders = ", ".join(
                ["%s"] * len(columns)
            )

            insert_sql = f"""
                INSERT INTO `{table_name}`
                ({column_sql})
                VALUES ({placeholders})
            """

            for row in reader:

                if len(row) != len(columns):

                    raise ValueError(
                        f"{filename} 第 {reader.line_num} 行"
                        "字段数量异常"
                    )

                batch.append(
                    tuple(
                        convert_value(value)
                        for value in row
                    )
                )

                if len(batch) >= BATCH_SIZE:

                    cursor.executemany(
                        insert_sql,
                        batch
                    )

                    total_rows += len(batch)

                    batch.clear()

                    print(
                        f"  导入进度: "
                        f"{total_rows:,}/{csv_count:,}",
                        end="\r"
                    )

            if batch:

                cursor.executemany(
                    insert_sql,
                    batch
                )

                total_rows += len(batch)

                batch.clear()

        cursor.execute(
            f"SELECT COUNT(*) FROM `{table_name}`"
        )

        actual_rows = cursor.fetchone()[0]

        if actual_rows != csv_count:

            raise RuntimeError(
                f"记录数不一致: "
                f"CSV={csv_count}, MySQL={actual_rows}"
            )

        connection.commit()

        print(
            f"\n[导入成功] {table_name}: "
            f"{actual_rows:,} 行"
        )

        return actual_rows

    except Exception:

        connection.rollback()

        raise


# ============================================================
# 11. 数据导入汇总
# ============================================================

def print_summary(results):

    print("\n")
    print("=" * 75)
    print("                  Olist 数据导入汇总")
    print("=" * 75)

    total_rows = 0

    for table_name, count in results.items():

        print(
            f"{table_name:<48} {count:>12,}"
        )

        total_rows += count

    print("-" * 75)

    print(f"数据表数量: {len(results)}")

    print(f"总记录数: {total_rows:,}")

    print("=" * 75)


# ============================================================
# 12. 主程序
# ============================================================

def run_final_queries(cursor):
    """只执行每份答题 SQL 标记的最终查询，保留原有探索语句。"""
    filenames = (
        "q2_1_translation_gap.sql",
        "q2_2_monthly_metrics.sql",
        "q2_3_top_sellers.sql",
    )
    for filename in filenames:
        sql = (Path(__file__).resolve().parent / filename).read_text(encoding="utf-8-sig")
        _, marker, query = sql.partition("-- RUN_ALL_QUERY\n")
        if not marker or not query.strip():
            raise ValueError(f"没有找到最终查询：{filename}")
        cursor.execute(query)
        rows = cursor.fetchall()
        print(f"\n[查询结果] {filename}，{len(rows)} 行")
        print("\t".join(cursor.column_names))
        for row in rows:
            print("\t".join("NULL" if value is None else str(value) for value in row))


def main():

    parser = argparse.ArgumentParser(description="导入 Olist 数据，可选执行 Q2 最终查询")
    parser.add_argument("--run-queries", action="store_true", help="导入后执行 Q2.1–Q2.3")
    parser.add_argument("--non-interactive", action="store_true", help="仅从环境变量读取数据库密码")
    args = parser.parse_args()

    connection = None

    cursor = None

    try:

        print("=" * 65)
        print("           Olist MySQL 数据导入程序")
        print("=" * 65)

        print(f"\n项目根目录: {PROJECT_ROOT}")
        print(f"数据目录: {DATA_DIR}")

        if not DATA_DIR.exists():

            raise FileNotFoundError(
                f"数据目录不存在: {DATA_DIR}"
            )

        # 第一步：检查 CSV
        validate_files()

        # 第二步：输入密码
        password = os.environ.get("OLIST_MYSQL_PASSWORD")
        if password is None:
            if args.non_interactive:
                raise RuntimeError("请通过环境变量 OLIST_MYSQL_PASSWORD 配置 MySQL 密码。")
            password = getpass("\n请输入 MySQL 密码: ")
        config = DB_CONFIG | {
            "host": os.environ.get("OLIST_MYSQL_HOST", DB_CONFIG["host"]),
            "port": int(os.environ.get("OLIST_MYSQL_PORT", DB_CONFIG["port"])),
            "user": os.environ.get("OLIST_MYSQL_USER", DB_CONFIG["user"]),
            "password": password,
        }

        # 第三步：连接 MySQL
        connection = mysql.connector.connect(
            **config
        )

        cursor = connection.cursor()

        cursor.execute("SELECT VERSION()")

        version = cursor.fetchone()[0]

        print(f"\nMySQL 服务器版本: {version}")

        if "mariadb" in version.casefold() or int(version.split(".", 1)[0]) < 8:

            raise RuntimeError(
                "当前 MySQL 版本不符合要求，"
                "需要 MySQL 8.0+。"
            )

        # 第四步：创建数据库及数据表
        create_database_and_tables(
            cursor,
            connection
        )

        # 第五步：导入 9 张表
        print("\n========== 数据导入 ==========\n")

        results = {}

        for table_name, filename in TABLE_FILES.items():

            results[table_name] = import_table(
                connection,
                cursor,
                table_name,
                filename
            )

        # 第六步：输出结果
        print_summary(results)

        print("\n[执行成功] 全部 9 张数据表已完成检查。")
        if args.run_queries:
            run_final_queries(cursor)

    except Exception as error:

        if connection is not None:

            connection.rollback()

        print("\n[执行失败]")

        print(error)

        raise

    finally:

        if cursor is not None:
            cursor.close()

        if connection is not None:
            connection.close()


if __name__ == "__main__":

    main()
