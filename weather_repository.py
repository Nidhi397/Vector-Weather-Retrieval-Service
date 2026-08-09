from lakebase import get_connection
from psycopg2.extras import Json

class WeatherRepository:

    def create_table(self):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS weather_documents (
                        id TEXT PRIMARY KEY,
                        location TEXT NOT NULL,
                        source_type TEXT NOT NULL,
                        headline TEXT,
                        event TEXT,
                        narrative_text TEXT,
                        issued_at TIMESTAMPTZ,
                        effective_at TIMESTAMPTZ,
                        payload JSONB,
                        synced_at TIMESTAMPTZ NOT NULL
                    )
                """)
    
            conn.commit()

    def upsert_document(self, document):
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO weather_documents (
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
                    %(id)s,
                    %(location)s,
                    %(source_type)s,
                    %(headline)s,
                    %(event)s,
                    %(narrative_text)s,
                    %(issued_at)s,
                    %(effective_at)s,
                    %(payload)s,
                    %(synced_at)s
                    )
                    ON CONFLICT (id)
                    DO UPDATE SET
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
                    {
                        **document,
                        "payload": Json(document["payload"])
                    }
                )

            conn.commit()
            
    def upsert_documents(self, documents):
        count = 0

        for document in documents:
            self.upsert_document(document)
            count += 1

        return count
if __name__ == "__main__":

    repository = WeatherRepository()

    repository.create_table()

    print("weather_documents table created")