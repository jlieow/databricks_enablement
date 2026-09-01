from flask import Flask, render_template, request
import psycopg
import os
from databricks import sdk
from psycopg import sql
from psycopg_pool import ConnectionPool

# Database connection setup
workspace_client = sdk.WorkspaceClient()
endpoint = os.getenv("PGENDPOINT", "")
connection_pool = None

# The serving table the batch pipeline writes to. Notebook
# 09_lakebase_change_data_feed_sync.py provisions this table
# (health_analytics.patient_risk_scores) and populates it with the model's
# batch scores. This app reads it as an internal, read-only service for other
# clinical teams; it never runs live inference and never writes clinical data.
SERVING_SCHEMA = os.getenv("SERVING_SCHEMA", "health_analytics")
SERVING_TABLE = os.getenv("SERVING_TABLE", "patient_risk_scores")


class OAuthConnection(psycopg.Connection):
    """Connection subclass that auto-refreshes OAuth credentials."""

    @classmethod
    def connect(cls, conninfo="", **kwargs):
        credential = workspace_client.postgres.generate_database_credential(
            endpoint=endpoint
        )
        kwargs["password"] = credential.token
        return super().connect(conninfo, **kwargs)


def get_connection_pool():
    """Get or create the connection pool."""
    global connection_pool
    if connection_pool is None:
        conn_string = (
            f"dbname={os.getenv('PGDATABASE')} "
            f"user={os.getenv('PGUSER')} "
            f"host={os.getenv('PGHOST')} "
            f"port={os.getenv('PGPORT')} "
            f"sslmode={os.getenv('PGSSLMODE', 'require')} "
            f"application_name={os.getenv('PGAPPNAME')}"
        )
        connection_pool = ConnectionPool(
            conn_string, connection_class=OAuthConnection, min_size=2, max_size=10
        )
    return connection_pool


def get_connection():
    """Get a connection from the pool."""
    return get_connection_pool().connection()


def get_risk_scores(district_filter=None):
    """Read patient risk scores from the serving table.

    The batch pipeline is the only writer. This service is read-only: it
    surfaces the latest scored cohort for the clinical teams that call it.
    """
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                if district_filter:
                    cur.execute(
                        sql.SQL(
                            "SELECT patient_id, district_id, risk_score, risk_category, "
                            "model_version, scored_at, last_updated "
                            "FROM {}.{} WHERE district_id = %s "
                            "ORDER BY risk_score DESC"
                        ).format(
                            sql.Identifier(SERVING_SCHEMA),
                            sql.Identifier(SERVING_TABLE),
                        ),
                        (district_filter,),
                    )
                else:
                    cur.execute(
                        sql.SQL(
                            "SELECT patient_id, district_id, risk_score, risk_category, "
                            "model_version, scored_at, last_updated "
                            "FROM {}.{} ORDER BY risk_score DESC"
                        ).format(
                            sql.Identifier(SERVING_SCHEMA),
                            sql.Identifier(SERVING_TABLE),
                        )
                    )
                return cur.fetchall()
    except Exception as e:
        print(f"Read risk scores error: {e}")
        return []


def get_districts():
    """List the districts present in the serving table, for the filter dropdown."""
    try:
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    sql.SQL("SELECT DISTINCT district_id FROM {}.{} ORDER BY district_id").format(
                        sql.Identifier(SERVING_SCHEMA),
                        sql.Identifier(SERVING_TABLE),
                    )
                )
                return [r[0] for r in cur.fetchall()]
    except Exception as e:
        print(f"List districts error: {e}")
        return []


# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key')


@app.route('/')
def index():
    """Main page showing the batch-scored patient risk cohort."""
    district = request.args.get('district') or None
    scores = get_risk_scores(district)
    districts = get_districts()
    return render_template(
        'index.html',
        scores=scores,
        districts=districts,
        selected_district=district,
    )


if __name__ == '__main__':
    host = os.getenv('FLASK_RUN_HOST', '0.0.0.0')
    port = int(os.getenv('FLASK_RUN_PORT', 8000))

    app.run(debug=True, host=host, port=port)
    print(f"Flask app running on http://{host}:{port}")
