import os
import uuid
import base64
from datetime import datetime
from urllib.parse import urlparse

import requests
import psycopg2
import pandas as pd

from databricks.sdk import WorkspaceClient
from sentence_transformers import SentenceTransformer


# ============================================================
# CONFIG
# ============================================================

WEATHER_EMBEDDINGS_TABLE = "weather_embeddings"

EMBEDDING_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIM = 384

NWS_BASE_URL = "https://api.weather.gov"

# IMPORTANT:
# NWS requires a User-Agent identifying your application.
NWS_USER_AGENT = "weather-embeddings-project"

# Test location
# You can change these later.
LATITUDE = 32.9483
LONGITUDE = -96.7299

LOCATION_NAME = "Richardson, TX"

CHUNK_SIZE = 800
CHUNK_OVERLAP = 100


# ============================================================
# LOAD LAKEBASE CONNECTION
# ============================================================

print("Loading Lakebase connection information...")

w = WorkspaceClient()


def get_lakebase_url() -> str:
    """
    Retrieve the base64-encoded Lakebase PostgreSQL URL
    from the Databricks secret scope.
    """

    secret = w.secrets.get_secret(
        scope="database",
        key="lakebase-url"
    )

    return base64.b64decode(secret.value).decode("utf-8")


lakebase_url = get_lakebase_url()

parsed = urlparse(lakebase_url)

db_host = parsed.hostname
db_port = parsed.port or 5432
db_name = parsed.path.lstrip("/")
db_user = parsed.username
db_password = parsed.password

print("Lakebase connection information loaded.")
print(f"Host: {db_host}")
print(f"Port: {db_port}")
print(f"Database: {db_name}")
print(f"User: {db_user}")


# ============================================================
# TEST LAKEBASE CONNECTION
# ============================================================

print("\nTesting Lakebase connection...")

conn = None
cursor = None

try:
    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=db_password,
        sslmode="require",
        connect_timeout=10
    )

    cursor = conn.cursor()

    cursor.execute(
        f"SELECT COUNT(*) FROM {WEATHER_EMBEDDINGS_TABLE}"
    )

    count = cursor.fetchone()[0]

    print("Lakebase connection successful.")
    print(
        f"{WEATHER_EMBEDDINGS_TABLE} currently contains "
        f"{count} rows."
    )

except Exception as e:
    print(f"Lakebase connection failed: {e}")
    raise

finally:
    if cursor:
        cursor.close()

    if conn:
        conn.close()


# ============================================================
# NWS SESSION
# ============================================================

session = requests.Session()

session.headers.update(
    {
        "User-Agent": NWS_USER_AGENT,
        "Accept": "application/geo+json"
    }
)


# ============================================================
# GET POINT INFORMATION
# ============================================================

def get_point(latitude: float, longitude: float) -> dict:
    """
    Convert latitude/longitude into the NWS forecast grid.

    NWS requires this step because forecast data is organized
    around Weather Forecast Office gridpoints.
    """

    url = f"{NWS_BASE_URL}/points/{latitude},{longitude}"

    print("\nGetting NWS point information...")
    print(f"URL: {url}")

    response = session.get(
        url,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    print("Point lookup successful.")

    return data


# ============================================================
# GET FORECAST
# ============================================================

def get_forecast(point_data: dict) -> dict:
    """
    Use the forecast URL returned by the NWS /points endpoint.
    """

    forecast_url = point_data["properties"]["forecast"]

    print("\nGetting forecast...")
    print(f"Forecast URL: {forecast_url}")

    response = session.get(
        forecast_url,
        timeout=30
    )

    response.raise_for_status()

    data = response.json()

    print("Forecast retrieved successfully.")

    return data


# ============================================================
# CONVERT FORECAST TO TEXT
# ============================================================

def forecast_to_text(
    forecast_data: dict,
    location: str
) -> str:
    """
    Convert the structured NWS forecast JSON into readable
    natural-language text.

    This text is what we will eventually embed.
    """

    properties = forecast_data.get("properties", {})

    periods = properties.get("periods", [])

    lines = []

    lines.append(
        f"Weather forecast for {location}."
    )

    for period in periods:

        name = period.get("name", "")

        detailed_forecast = period.get(
            "detailedForecast",
            ""
        )

        temperature = period.get(
            "temperature"
        )

        temperature_unit = period.get(
            "temperatureUnit",
            ""
        )

        wind_speed = period.get(
            "windSpeed",
            ""
        )

        wind_direction = period.get(
            "windDirection",
            ""
        )

        short_forecast = period.get(
            "shortForecast",
            ""
        )

        lines.append(
            f"\n{name}:"
        )

        if temperature is not None:
            lines.append(
                f"Temperature: "
                f"{temperature}°{temperature_unit}"
            )

        if short_forecast:
            lines.append(
                f"Conditions: {short_forecast}"
            )

        if wind_speed:
            lines.append(
                f"Wind: {wind_speed} "
                f"{wind_direction}"
            )

        if detailed_forecast:
            lines.append(
                f"Details: {detailed_forecast}"
            )

    return "\n".join(lines)


# ============================================================
# CHUNK TEXT
# ============================================================

def chunk_text(
    text: str,
    chunk_size: int,
    overlap: int
) -> list[str]:
    """
    Split the forecast into overlapping chunks.
    """

    if not text:
        return []

    if overlap >= chunk_size:
        raise ValueError(
            "chunk_overlap must be smaller than chunk_size"
        )

    chunks = []

    step = chunk_size - overlap

    for start in range(
        0,
        len(text),
        step
    ):

        chunk = text[
            start:start + chunk_size
        ].strip()

        if chunk:
            chunks.append(chunk)

        if start + chunk_size >= len(text):
            break

    return chunks


# ============================================================
# LOAD EMBEDDING MODEL
# ============================================================

print("\nLoading embedding model...")

os.environ["HF_HOME"] = "/tmp/.cache/huggingface"
os.environ["TRANSFORMERS_CACHE"] = "/tmp/.cache/huggingface"
os.environ["HF_HUB_CACHE"] = "/tmp/.cache/huggingface"

model = SentenceTransformer(
    EMBEDDING_MODEL_NAME,
    cache_folder="/tmp/.cache/huggingface"
)

print(
    f"Embedding model loaded: "
    f"{EMBEDDING_MODEL_NAME}"
)

print(
    f"Embedding dimension: "
    f"{EMBEDDING_DIM}"
)


# ============================================================
# FETCH WEATHER
# ============================================================

point_data = get_point(
    LATITUDE,
    LONGITUDE
)

forecast_data = get_forecast(
    point_data
)


# ============================================================
# CREATE WEATHER DOCUMENT
# ============================================================

weather_text = forecast_to_text(
    forecast_data,
    LOCATION_NAME
)

print("\nWeather document created.")
print("--------------------------------")
print(weather_text[:3000])
print("--------------------------------")


# ============================================================
# CHUNK WEATHER DOCUMENT
# ============================================================

chunks = chunk_text(
    weather_text,
    CHUNK_SIZE,
    CHUNK_OVERLAP
)

print(
    f"\nCreated {len(chunks)} weather chunks."
)

for i, chunk in enumerate(chunks):
    print(
        f"\n--- Chunk {i} ---"
    )
    print(chunk[:500])


# ============================================================
# COMPUTE EMBEDDINGS
# ============================================================

print("\nComputing embeddings...")

embeddings = model.encode(
    chunks,
    show_progress_bar=False
)

print(
    f"Generated {len(embeddings)} embeddings."
)

print(
    f"Each embedding has "
    f"{len(embeddings[0])} dimensions."
)


# ============================================================
# PREPARE DATABASE ROWS
# ============================================================

document_id = str(
    uuid.uuid4()
)

source_type = "nws_forecast"

created_at = datetime.now()

rows = []

for chunk_index, (
    chunk,
    embedding
) in enumerate(
    zip(chunks, embeddings)
):

    row_id = (
        f"{document_id}_{chunk_index}"
    )

    embedding_string = (
        "["
        + ",".join(
            str(float(value))
            for value in embedding
        )
        + "]"
    )

    rows.append(
        (
            row_id,
            document_id,
            LOCATION_NAME,
            source_type,
            chunk_index,
            chunk,
            embedding_string,
            EMBEDDING_MODEL_NAME,
            created_at
        )
    )


# ============================================================
# INSERT INTO LAKEBASE
# ============================================================

print(
    f"\nInserting {len(rows)} rows into "
    f"{WEATHER_EMBEDDINGS_TABLE}..."
)

conn = None
cursor = None

try:

    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=db_password,
        sslmode="require",
        connect_timeout=10
    )

    cursor = conn.cursor()

    insert_sql = f"""
        INSERT INTO {WEATHER_EMBEDDINGS_TABLE} (
            id,
            document_id,
            location,
            source_type,
            chunk_index,
            chunk_text,
            embedding,
            model_name,
            created_at
        )
        VALUES (
            %s,
            %s,
            %s,
            %s,
            %s,
            %s,
            %s::vector,
            %s,
            %s
        )
        ON CONFLICT (id) DO NOTHING
    """

    cursor.executemany(
        insert_sql,
        rows
    )

    conn.commit()

    print(
        f"Successfully inserted "
        f"{cursor.rowcount} weather embeddings."
    )

except Exception as e:

    if conn:
        conn.rollback()

    print(
        f"Failed to insert embeddings: {e}"
    )

    raise

finally:

    if cursor:
        cursor.close()

    if conn:
        conn.close()


# ============================================================
# VERIFY INSERT
# ============================================================

print("\nVerifying inserted data...")

conn = None
cursor = None

try:

    conn = psycopg2.connect(
        host=db_host,
        port=db_port,
        dbname=db_name,
        user=db_user,
        password=db_password,
        sslmode="require"
    )

    cursor = conn.cursor()

    cursor.execute(
        f"""
        SELECT
            id,
            document_id,
            location,
            source_type,
            chunk_index,
            LEFT(chunk_text, 100),
            model_name
        FROM {WEATHER_EMBEDDINGS_TABLE}
        WHERE document_id = %s
        ORDER BY chunk_index
        """,
        (document_id,)
    )

    results = cursor.fetchall()

    print(
        f"\nFound {len(results)} rows "
        f"for document {document_id}"
    )

    for row in results:

        print("\n----------------------------")

        print(f"id: {row[0]}")
        print(f"document_id: {row[1]}")
        print(f"location: {row[2]}")
        print(f"source_type: {row[3]}")
        print(f"chunk_index: {row[4]}")
        print(f"chunk_text: {row[5]}...")
        print(f"model_name: {row[6]}")

    print(
        "\nWeather embedding pipeline completed successfully."
    )

finally:

    if cursor:
        cursor.close()

    if conn:
        conn.close()
