-- Receipts evidence store: register the exported CSVs in Zetaris.
--
-- Steps:
--   1. Start your Zetaris instance and sign in to its web UI.
--   2. Export the evidence store. The Receipts app writes runs.csv,
--      claims.csv and sources.csv under its data/zetaris/ directory on
--      every /evidence/insights call.
--   3. Replace every <RECEIPTS_EXPORT_DIR> below with the absolute
--      path of that directory AS SEEN BY THE ZETARIS INSTANCE (on a
--      single machine install, the same path the app uses). Forward
--      slashes work on Windows and Linux. This file was generated for
--      the default export directory layout; the Python helper
--      scripts/register_zetaris_sources.py prints the same statements
--      with the real paths filled in.
--   4. Run the statements in the Zetaris SQL Workspace one at a time.
--      On a fresh instance run all four. If the receipts_evidence
--      database already exists, skip the first statement.
--   5. Create an API key in the Zetaris GUI (Management, API Tokens)
--      and note the numeric organisation ID (Management,
--      Organisation). Then set the Receipts app environment and
--      restart the app:
--        ZETARIS_BASE_URL=http://localhost:3000
--        ZETARIS_API_KEY=<the API key>
--        ZETARIS_ORG_ID=<numeric organisation ID>
--        ZETARIS_JDBC_URL=jdbc:zetaris:lightning@localhost:10000
--      The JDBC URL is optional and only used by JDBC tools; the app
--      itself talks to the instance over the REST proxy route.
--
-- Registered tables are queried as receipts_evidence.runs,
-- receipts_evidence.claims and receipts_evidence.sources.

CREATE LIGHTNING DATABASE receipts_evidence DESCRIBE BY "Receipts evidence store";

CREATE LIGHTNING FILESTORE TABLE runs FROM receipts_evidence FORMAT CSV OPTIONS (path "<RECEIPTS_EXPORT_DIR>/runs.csv", header "true", delimiter ",");

CREATE LIGHTNING FILESTORE TABLE claims FROM receipts_evidence FORMAT CSV OPTIONS (path "<RECEIPTS_EXPORT_DIR>/claims.csv", header "true", delimiter ",");

CREATE LIGHTNING FILESTORE TABLE sources FROM receipts_evidence FORMAT CSV OPTIONS (path "<RECEIPTS_EXPORT_DIR>/sources.csv", header "true", delimiter ",");
