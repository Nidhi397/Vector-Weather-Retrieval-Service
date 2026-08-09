"""
Databricks App:

- Serves a small Flask API
- Reads/writes to Lakebase via lakebase.py
- Pulls weather data from the National Weather Service API
  via weather_client.py
- Syncs normalized weather documents into Lakebase
"""

import json
import logging
import os

from flask import Flask, jsonify, render_template, request

import lakebase
from weather_client import WeatherClient


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("weather-app")

app = Flask(__name__)


WEATHER_TABLE_NAME = os.environ.get(
    "WEATHER_TABLE_NAME",
    "weather_documents"
)


def ensure_weather_table():
    """
    Create the weather_documents table if it does not already exist.
    """

    lakebase.run_write(
        f"""
        CREATE TABLE IF NOT EXISTS {WEATHER_TABLE_NAME} (
            id TEXT PRIMARY KEY,
            location TEXT NOT NULL,
            source_type TEXT NOT NULL,
            headline TEXT,
            event TEXT,
            narrative_text TEXT,
            issued_at TIMESTAMPTZ,
            effective_at TIMESTAMPTZ,
            payload JSONB NOT NULL,
            synced_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


@app.route("/healthz")
def healthz():
    return jsonify({"status": "ok"})


@app.errorhandler(Exception)
def handle_exception(err):
    """
    Ensure errors return JSON instead of Flask's HTML error page.
    """

    logger.exception(
        "Unhandled error while processing request"
    )

    status_code = getattr(err, "code", 500)

    if not isinstance(status_code, int):
        status_code = 500

    return jsonify({"error": str(err)}), status_code


@app.route("/")
def index():
    """
    Simple UI endpoint.
    """

    return render_template("index.html")


@app.route("/weather/sync", methods=["POST"])
def sync_weather():
    """
    Fetch weather documents from the National Weather Service
    and upsert them into Lakebase.

    Expected JSON body:

    {
        "locations": [
            [41.8781, -87.6298],
            [30.2672, -97.7431]
        ],
        "limit": 50
    }
    """

    ensure_weather_table()

    client = WeatherClient()

    body = request.json if request.is_json else {}

    locations = body.get("locations", [])
    limit = int(body.get("limit", 50))

    if not locations:
        return jsonify({
            "error": "locations is required"
        }), 400

    total = 0

    for location in locations:

        if not isinstance(location, list) or len(location) != 2:
            continue

        latitude = location[0]
        longitude = location[1]

        documents = []

        # ---------------------------------------------------------
        # 1. Resolve location
        # ---------------------------------------------------------

        resolved = client.resolve_location(
            latitude,
            longitude
        )

        location_name = f"{latitude},{longitude}"

        # ---------------------------------------------------------
        # 2. Fetch active alerts
        # ---------------------------------------------------------

        alerts = client.get_alerts(
            latitude,
            longitude
        )

        for alert in alerts:

            properties = alert.get("properties", {})

            document = {
                "id": alert.get("id"),
                "location": location_name,
                "source_type": "alert",
                "headline": properties.get("headline"),
                "event": properties.get("event"),
                "narrative_text": (
                    (properties.get("description") or "")
                    + "\n"
                    + (properties.get("instruction") or "")
                ).strip(),
                "issued_at": properties.get("sent"),
                "effective_at": properties.get("effective"),
                "payload": alert,
            }

            documents.append(document)

        # ---------------------------------------------------------
        # 3. Fetch forecast discussions
        # ---------------------------------------------------------

        discussions = client.get_forecast_discussion(
            latitude,
            longitude
        )

        # Respect the requested limit
        discussions = discussions[:limit]

        for product in discussions:

            document = {
                "id": product.get("id"),
                "location": location_name,
                "source_type": "forecast",
                "headline": product.get("productName"),
                "event": "Area Forecast Discussion",
                "narrative_text": product.get("productText", ""),
                "issued_at": product.get("issuanceTime"),
                "effective_at": product.get("issuanceTime"),
                "payload": product,
            }

            documents.append(document)

        # ---------------------------------------------------------
        # 4. Upsert documents into Lakebase
        # ---------------------------------------------------------

        total += _upsert_weather_documents(documents)

    return jsonify({
        "synced": total,
        "locations": locations
    })


@app.route("/weather/documents")
def list_weather_documents():
    """
    Return weather documents already stored in Lakebase.
    """

    ensure_weather_table()

    limit = int(
        request.args.get("limit", 100)
    )

    rows = lakebase.run_query(
        f"""
        SELECT
            id,
            location,
            source_type,
            headline,
            event,
            narrative_text,
            issued_at,
            effective_at,
            synced_at
        FROM {WEATHER_TABLE_NAME}
        ORDER BY synced_at DESC
        LIMIT %s
        """,
        (limit,),
    )

    return jsonify(rows)


def _upsert_weather_documents(
    documents: list[dict]
) -> int:
    """
    Upsert normalized weather documents into Lakebase.
    """

    count = 0

    with lakebase.get_connection() as conn:

        with conn.cursor() as cur:

            for document in documents:

                cur.execute(
                    f"""
                    INSERT INTO {WEATHER_TABLE_NAME} (
                        id,
                        location,
                        source_type,
                        headline,
                        event,
                        narrative_text,
                        issued_at,
                        effective_at,
                        payload,
                        synced_at
                    )
                    VALUES (
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        now()
                    )

                    ON CONFLICT (id) DO UPDATE
                    SET
                        location = EXCLUDED.location,
                        source_type = EXCLUDED.source_type,
                        headline = EXCLUDED.headline,
                        event = EXCLUDED.event,
                        narrative_text = EXCLUDED.narrative_text,
                        issued_at = EXCLUDED.issued_at,
                        effective_at = EXCLUDED.effective_at,
                        payload = EXCLUDED.payload,
                        synced_at = EXCLUDED.synced_at
                    """,
                    (
                        document["id"],
                        document["location"],
                        document["source_type"],
                        document["headline"],
                        document["event"],
                        document["narrative_text"],
                        document["issued_at"],
                        document["effective_at"],
                        json.dumps(document["payload"]),
                    ),
                )

                count += 1

            conn.commit()

    return count


if __name__ == "__main__":

    host = os.getenv(
        "FLASK_RUN_HOST",
        "0.0.0.0"
    )

    port = int(
        os.getenv(
            "FLASK_RUN_PORT",
            8000
        )
    )

    app.run(
        debug=True,
        host=host,
        port=port
    )

    print(
        f"Flask app running on http://{host}:{port}"
    )

