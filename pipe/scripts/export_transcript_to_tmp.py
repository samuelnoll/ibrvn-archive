import argparse
import os
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)

if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from shared.db import fetch_one, initialize_database


def resolve_transcript(preaching_date: str = "", canonical_sermon_id: str = ""):

    params = {}
    filters = []

    if preaching_date:
        params["preaching_date"] = preaching_date
        filters.append("""
            st.canonical_sermon_id IN (
                SELECT canonical_sermon_id
                FROM gold_sermons
                WHERE preaching_date = :preaching_date

                UNION

                SELECT canonical_sermon_id
                FROM silver_sermon_metadata
                WHERE preaching_date = :preaching_date
            )
        """)

    if canonical_sermon_id:
        params["canonical_sermon_id"] = canonical_sermon_id
        filters.append("st.canonical_sermon_id = :canonical_sermon_id")

    where_clause = ""

    if filters:
        where_clause = "WHERE " + " AND ".join(filters)

    return fetch_one(f"""
        SELECT
            st.canonical_sermon_id,
            st.transcript_version,
            st.transcript_text,
            st.model_name,
            st.created_at,
            COALESCE(
                (
                    SELECT gs.preaching_date
                    FROM gold_sermons gs
                    WHERE gs.canonical_sermon_id = st.canonical_sermon_id
                    LIMIT 1
                ),
                (
                    SELECT sm.preaching_date
                    FROM silver_sermon_metadata sm
                    WHERE sm.canonical_sermon_id = st.canonical_sermon_id
                    ORDER BY sm.processed_at DESC
                    LIMIT 1
                )
            ) AS preaching_date
        FROM silver_transcripts st
        {where_clause}
        ORDER BY
            COALESCE(
                (
                    SELECT gs.preaching_date
                    FROM gold_sermons gs
                    WHERE gs.canonical_sermon_id = st.canonical_sermon_id
                    LIMIT 1
                ),
                (
                    SELECT sm.preaching_date
                    FROM silver_sermon_metadata sm
                    WHERE sm.canonical_sermon_id = st.canonical_sermon_id
                    ORDER BY sm.processed_at DESC
                    LIMIT 1
                ),
                st.created_at
            ) DESC,
            st.transcript_version DESC
        LIMIT 1
    """, params)


def build_output_path(row, output: str = ""):

    if output:
        return Path(output)

    sermon_date = (row.get("preaching_date") or row["canonical_sermon_id"]).replace("-", "_")
    filename = f"{sermon_date}.txt"
    return Path(tempfile.gettempdir()) / filename


def run(preaching_date: str = "", canonical_sermon_id: str = "", output: str = ""):

    initialize_database()

    row = resolve_transcript(
        preaching_date=preaching_date.strip(),
        canonical_sermon_id=canonical_sermon_id.strip(),
    )

    if not row:
        raise SystemExit(
            "Nenhuma transcricao encontrada para os filtros informados."
        )

    transcript_text = (row.get("transcript_text") or "").strip()

    if not transcript_text:
        raise SystemExit(
            f"Transcricao vazia para canonical_sermon_id={row['canonical_sermon_id']}"
        )

    output_path = build_output_path(row, output=output.strip())
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(transcript_text, encoding="utf-8")

    print(f"Arquivo salvo em: {output_path}")
    print(f"canonical_sermon_id: {row['canonical_sermon_id']}")
    print(f"preaching_date: {row.get('preaching_date', '')}")
    print(f"transcript_version: {row['transcript_version']}")
    print(f"model_name: {row.get('model_name', '')}")


def main():

    parser = argparse.ArgumentParser(
        description="Exporta uma transcricao da silver_transcripts para um arquivo .txt no tmp."
    )
    parser.add_argument(
        "--preaching-date",
        default="",
        help="Data da pregacao no formato YYYY-MM-DD.",
    )
    parser.add_argument(
        "--canonical-sermon-id",
        default="",
        help="canonical_sermon_id da pregacao.",
    )
    parser.add_argument(
        "--output",
        default="",
        help="Caminho completo opcional do arquivo de saida.",
    )

    args = parser.parse_args()
    run(
        preaching_date=args.preaching_date,
        canonical_sermon_id=args.canonical_sermon_id,
        output=args.output,
    )


if __name__ == "__main__":
    main()
