from src.providers import OpenRouterProvider, SQLExtractor


def test_sql_extractor_code_fences():
    raw = """Here is the SQL query you asked for:
```sql
SELECT customer_id, first_name FROM customers WHERE city = 'New York';
```
Let me know if you need more help!"""
    sql = SQLExtractor.extract_sql(raw)
    assert "customer_id" in sql
    assert "FROM customers" in sql
    assert "New York" in sql
    assert "```" not in sql


def test_sql_extractor_raw_statement():
    raw = "SELECT product_name, price FROM products WHERE price > 50;"
    sql = SQLExtractor.extract_sql(raw)
    assert "product_name" in sql
    assert "FROM products" in sql
    assert "price > 50" in sql


def test_sql_extractor_clean_formatting():
    raw = "```sql\nSELECT `product_id`, `product_name` FROM `products`;\n```"
    sql = SQLExtractor.clean_sql(raw)
    assert "`" not in sql
    assert sql.endswith("products") or sql.endswith("FROM products")


def test_openrouter_provider_missing_key():
    provider = OpenRouterProvider(api_key="")
    assert provider.is_available() is False
    res = provider.generate_sql("Show all customers")
    assert res.success is False
    assert "api key" in res.error.lower()
