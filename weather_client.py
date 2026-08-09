# Talks to the National Weather Service website and bring weather data back to our Python program.

import requests
from datetime import datetime, timezone
BASE_URL = "https://api.weather.gov"

class WeatherClient:

    def __init__(self):
        self._session = requests.Session()

    def get(self, path, params=None):
        response = self._session.get(
            f"{BASE_URL}{path}",
            params=params,
            timeout=30
        )

        response.raise_for_status()

        return response.json()
    
    def get_point(self, latitude, longitude):
        return self.get(
        f"/points/{latitude},{longitude}"
    )

    def get_forecast(self, latitude, longitude):
        point = self.get_point(latitude, longitude)
        forecast_url = point["properties"]["forecast"]
        response = self._session.get(
        forecast_url,
        timeout=30
        )
        response.raise_for_status()
        return response.json()
    
    def get_alerts(self, latitude, longitude):
        data = self.get(
            "/alerts/active",
            params={
            "point": f"{latitude},{longitude}"
            }
        )
        return data.get("features", [])
    
    def get_forecast_discussion(self, latitude, longitude):
        point = self.get_point(latitude, longitude)

        office = point["properties"]["cwa"]

        data = self.get(
            "/products",
            params={
            "type": "AFD",
            "location": office
            }
        )

        discussions = data.get("@graph", [])

        if not discussions:
            return None

        # The API returns multiple AFD products.
        # Pick the most recent one.
        latest = max(
        discussions,
        key=lambda discussion: discussion["issuanceTime"]
        )

        response = self._session.get(
            latest["@id"],
            timeout=30
        )

        response.raise_for_status()

        return response.json()

    def resolve_location(self, latitude, longitude):
        point = self.get_point(latitude, longitude)

        return {
            "latitude": latitude,
            "longitude": longitude,
            "grid_id": point["properties"]["gridId"],
            "grid_x": point["properties"]["gridX"],
            "grid_y": point["properties"]["gridY"],
            "cwa": point["properties"]["cwa"]
        }
    
    def resolve_locations(self, locations):
        results = []

        for latitude, longitude in locations:
            location = self.resolve_location(
            latitude,
            longitude
            )

            results.append(location)

        return results
    def normalize_alert(self, alert, location):
        properties = alert["properties"]
        return {
        "id": alert["id"],
        "location": location,
        "source_type": "alert",
        "headline": properties.get("headline"),
        "event": properties.get("event"),
        "narrative_text": (
            (properties.get("description") or "")
            + "\n"
            + (properties.get("instruction") or "")
        ).strip(),
        "issued_at": properties.get("effective"),
        "effective_at": properties.get("effective"),
        "payload": alert,
        "synced_at": datetime.now(timezone.utc).isoformat()
        }

    def normalize_forecast(self, discussion, location):
        return {
            "id": discussion["id"],
            "location": location,
            "source_type": "forecast",
            "headline": discussion.get("productName"),
            "event": "Area Forecast Discussion",
            "narrative_text": discussion.get("productText", "").strip(),
            "issued_at": discussion.get("issuanceTime"),
            "effective_at": discussion.get("issuanceTime"),
            "payload": discussion,
            "synced_at": datetime.now(timezone.utc).isoformat()
        }

    def fetch_documents(self, locations, limit=50):
        documents = []

        for latitude, longitude in locations:

            # Get alerts
            alerts = self.get_alerts(latitude,longitude)

            for alert in alerts:
                document = self.normalize_alert(
                alert,
                f"{latitude},{longitude}"
                )

                documents.append(document)

            # Get forecast discussion
            discussion = self.get_forecast_discussion(
            latitude,
            longitude
            )

            if discussion:
                document = self.normalize_forecast(
                discussion,
                f"{latitude},{longitude}"
                )

                documents.append(document)

        return documents[:limit]

if __name__ == "__main__":

    client = WeatherClient()

    locations = [
        (41.8781, -87.6298),
        (30.2672, -97.7431)
    ]
    documents = client.fetch_documents(
    locations,
    limit=1
    )

    print("Documents:", len(documents))

    for document in documents:
        print(
        document["source_type"],
        document["location"],
        document["headline"]
        )