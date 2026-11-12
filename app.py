import os
import json
import logging
from typing import Any, List, Dict, Optional

import requests
import pymysql

from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from pymysql.cursors import DictCursor
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

logger = logging.getLogger(__name__)


class AbsolutTradeAPI:
    def __init__(self) -> None:
        self.host: str = "https://api.absoluttrade.ru/api"
        self.db_name: str = os.getenv("DB_NAME")
        self.token: Optional[str] = None
        self.headers: Dict[str, str] = {}
        self.retry_total = 5
        self.timeout = int(os.getenv("REQUEST_TIMEOUT", "300"))
        self.session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()

        retry = Retry(
            total=self.retry_total,
            backoff_factor=1,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET","POST"]
        )

        adapter = HTTPAdapter(max_retries=retry)
        session.mount("https://", adapter)

        return session

    @staticmethod
    def get_db_connection(database: Optional[str] = None):
        return pymysql.connect(
            host=os.getenv("DB_HOST"),
            user=os.getenv("DB_USER"),
            password=os.getenv("DB_PASS"),
            database=database,
            charset="utf8mb4",
            cursorclass=DictCursor,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
        )

    @staticmethod
    def clean_int(value: Any) -> int:
        if value is None:
            return 0

        digits = "".join(c for c in str(value) if c.isdigit())
        return int(digits) if digits else 0

    def authenticate(self) -> None:
        logger.info("Get token...\n")

        response = self.session.post(
            f"{self.host}/Token/CreateToken",
            json={
                "username": os.getenv("API_USERNAME"),
                "password": os.getenv("API_PASSWORD"),
            },
            timeout=self.timeout,
        )
        response.raise_for_status()

        self.token = response.text
        self.headers = {"Authorization": f"Bearer {self.token}"}

    def init_db(self) -> None:
        logger.info("Initiate database...")

        connect = self.get_db_connection(None)

        try:
            with connect.cursor() as cursor:
                cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{self.db_name}`")
                cursor.execute(f"USE `{self.db_name}`")

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS categories (
                        categoryName VARCHAR(255),
                        categoryCode VARCHAR(3),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        INDEX(categoryCode)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS vendors (
                        vendorName VARCHAR(255),
                        vendorCode VARCHAR(3),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        INDEX(vendorCode)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS products (
                        productId INT PRIMARY KEY,
                        traceability VARCHAR(50),
                        productName VARCHAR(500),
                        manufacturerCode VARCHAR(255),
                        vendorCode VARCHAR(100),
                        categoryCode VARCHAR(50),
                        catalogTree VARCHAR(1000),
                        paymentTerms VARCHAR(255),
                        paymentTermName VARCHAR(255),
                        lastUpdateDate VARCHAR(50),
                        crossReference VARCHAR(255),
                        warranty VARCHAR(50),
                        isEol BOOLEAN,
                        isKitItem BOOLEAN,
                        events JSON,
                        isNew BOOLEAN,
                        productPrice DECIMAL(15,2),
                        eanCodes VARCHAR(255),
                        rrp DECIMAL(15,2),
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        INDEX(categoryCode)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS products_inventory (
                        productId INT,
                        stock VARCHAR(100),
                        type ENUM('inStock','inTransit'),
                        quantity INT,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        INDEX(productId)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS products_description (
                        productId INT,
                        description JSON,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        INDEX(productId)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

                cursor.execute("""
                    CREATE TABLE IF NOT EXISTS products_media_items (
                        productId INT,
                        mediaLinks JSON,
                        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                        INDEX(productId)
                    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
                """)

            connect.commit()
        finally:
            connect.close()

    def sync_categories(self) -> None:
        logger.info("Get categories...")

        response = self.session.get(
            f"{self.host}/Catalogs/Categories",
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()

        items: List[Dict[str, Any]] = response.json()

        if items:
            rows = [
                (item.get("categoryName"), item.get("categoryCode"))
                for item in items
            ]

            logger.info("Save categories...")

            connect = self.get_db_connection(self.db_name)

            try:
                with connect.cursor() as cursor:
                    cursor.execute("CREATE TEMPORARY TABLE temp_categories LIKE categories")

                    cursor.executemany(
                        "INSERT INTO temp_categories (categoryName, categoryCode) VALUES (%s, %s)",
                        rows,
                    )
                    cursor.execute("TRUNCATE TABLE categories")
                    cursor.execute("INSERT INTO categories (categoryName, categoryCode) SELECT categoryName, categoryCode FROM temp_categories")

                connect.commit()

                logger.info(f"Total categories saved: {len(rows)}\n")
            finally:
                connect.close()

    def sync_vendors(self) -> None:
        logger.info("Get vendors...")

        response = self.session.get(
            f"{self.host}/Catalogs/Vendors",
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()

        items: List[Dict[str, Any]] = response.json()

        if items:
            rows = [
                (item.get("vendorName"), item.get("vendorCode"))
                for item in items
            ]

            logger.info("Save vendors...")

            connect = self.get_db_connection(self.db_name)

            try:
                with connect.cursor() as cursor:
                    cursor.execute("CREATE TEMPORARY TABLE temp_vendors LIKE vendors")

                    cursor.executemany(
                        "INSERT INTO temp_vendors (vendorName, vendorCode) VALUES (%s, %s)",
                        rows,
                    )
                    cursor.execute("TRUNCATE TABLE vendors")
                    cursor.execute("INSERT INTO vendors (vendorName, vendorCode) SELECT vendorName, vendorCode FROM temp_vendors")

                connect.commit()

                logger.info(f"Total vendors saved: {len(rows)}\n")
            finally:
                connect.close()

    def sync_products(self) -> None:
        logger.info("Get products...")

        response = self.session.get(
            f"{self.host}/Catalogs/ProductSearch",
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()

        items: List[Dict[str, Any]] = response.json()

        if items:
            products_rows = []
            inventory_rows = []

            for item in items:
                if not item.get("productId"):
                    continue

                products_rows.append(
                    (
                        item.get("productId"),
                        item.get("traceability"),
                        item.get("productName"),
                        item.get("manufacturerCode"),
                        item.get("vendorCode"),
                        item.get("categoryCode"),
                        item.get("catalogTree"),
                        item.get("paymentTerms"),
                        item.get("paymentTermName"),
                        item.get("lastUpdateDate"),
                        item.get("crossReference"),
                        item.get("warranty"),
                        item.get("isEol"),
                        item.get("isKitItem"),
                        json.dumps(item.get("events", []), ensure_ascii=False),
                        item.get("isNew"),
                        item.get("productPrice"),
                        item.get("eanCodes"),
                        item.get("rrp"),
                    )
                )

                for s in item.get("inStock", []):
                    inventory_rows.append(
                        (
                            item.get("productId"),
                            s.get("stock"),
                            "inStock",
                            self.clean_int(s.get("quantity")),
                        )
                    )

                for t in item.get("inTransit", []):
                    inventory_rows.append(
                        (
                            item.get("productId"),
                            t.get("stock"),
                            "inTransit",
                            self.clean_int(t.get("quantity")),
                        )
                    )

            logger.info("Save products...")

            connect = self.get_db_connection(self.db_name)

            try:
                with connect.cursor() as cursor:
                    cursor.execute("CREATE TEMPORARY TABLE temp_products LIKE products")
                    cursor.execute("CREATE TEMPORARY TABLE temp_inventory LIKE products_inventory")

                    cursor.executemany("""
                        INSERT IGNORE INTO temp_products (
                            productId, traceability, productName, manufacturerCode, vendorCode,
                            categoryCode, catalogTree, paymentTerms, paymentTermName,
                            lastUpdateDate, crossReference, warranty, isEol, isKitItem,
                            events, isNew, productPrice, eanCodes, rrp
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        """,
                        products_rows
                    )

                    cursor.executemany("""
                        INSERT INTO temp_inventory (productId, stock, type, quantity)
                        VALUES (%s, %s, %s, %s)
                        """,
                        inventory_rows
                    )

                    cursor.execute("TRUNCATE TABLE products")
                    cursor.execute("TRUNCATE TABLE products_inventory")

                    cursor.execute("INSERT INTO products SELECT * FROM temp_products")
                    cursor.execute("INSERT INTO products_inventory SELECT * FROM temp_inventory")

                connect.commit()

                logger.info(f"Total products saved: {len(products_rows)}\n")
            finally:
                connect.close()

    def sync_descriptions(self) -> None:
        logger.info("Get descriptions...")

        response = self.session.get(
            f"{self.host}/Catalogs/Products/*/Description",
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()

        items: List[Dict[str, Any]] = response.json()

        if items:
            rows = []
            for item in items:
                if not item.get("productId"):
                    continue

                rows.append((
                    item.get("productId"),
                    json.dumps(item.get("description"), ensure_ascii=False),
                ))

            logger.info("Save descriptions...")

            connect = self.get_db_connection(self.db_name)

            try:
                with connect.cursor() as cursor:
                    cursor.execute("CREATE TEMPORARY TABLE temp_products_description LIKE products_description")

                    cursor.executemany("""
                        INSERT IGNORE INTO temp_products_description (productId, description)
                        VALUES (%s, %s)
                        """,
                        rows
                    )

                    cursor.execute("TRUNCATE TABLE products_description")
                    cursor.execute("INSERT INTO products_description SELECT * FROM temp_products_description")

                connect.commit()

                logger.info(f"Total descriptions saved: {len(rows)}\n")
            finally:
                connect.close()

    def sync_media_items(self) -> None:
        logger.info("Get media items...")

        response = self.session.get(
            f"{self.host}/Catalogs/MediaItems",
            headers=self.headers,
            timeout=self.timeout,
        )
        response.raise_for_status()

        items: List[Dict[str, Any]] = response.json()

        if items:
            rows = []
            for item in items:
                if not item.get("productId"):
                    continue

                rows.append((
                    item.get("productId"),
                    json.dumps(item.get("mediaLinks", []), ensure_ascii=False),
                ))

            logger.info("Save media items...")

            connect = self.get_db_connection(self.db_name)

            try:
                with connect.cursor() as cursor:
                    cursor.execute("CREATE TEMPORARY TABLE temp_products_media_items LIKE products_media_items")

                    cursor.executemany("""
                        INSERT IGNORE INTO temp_products_media_items (productId, mediaLinks)
                        VALUES (%s, %s)
                        """,
                        rows
                    )

                    cursor.execute("TRUNCATE TABLE products_media_items")
                    cursor.execute("INSERT INTO products_media_items SELECT * FROM temp_products_media_items")

                connect.commit()

                logger.info(f"Total media items saved: {len(rows)}\n")
            finally:
                connect.close()


def main() -> None:
    try:
        api = AbsolutTradeAPI()

        api.init_db()
        api.authenticate()

        api.sync_categories()
        api.sync_vendors()
        api.sync_products()
        api.sync_descriptions()
        api.sync_media_items()

        logger.info("Done!")
    except Exception as e:
        print(e)


if __name__ == "__main__":
    main()
