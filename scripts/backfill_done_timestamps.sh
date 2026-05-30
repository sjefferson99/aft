#!/usr/bin/env bash
set -euo pipefail

# Backfill cards.done_datetime from cards.updated_at for cards that match done criteria.
#
# Requirements handled by this script:
# - Reads DB credentials from .env (with local.env fallback)
# - Reads compose.yml to find the db container_name under the db service
# - Verifies the resolved DB container name is aft-db
# - Uses docker exec + mysql to query and (optionally) update data
# - Shows candidate cards grouped by board/column and asks for confirmation

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ROOT_DIR}/.env"
COMPOSE_FILE="${ROOT_DIR}/compose.yml"
EXPECTED_DB_CONTAINER="aft-db"

DONE_SYNONYMS=(
  "done"
  "complete"
  "completed"
  "finished"
  "resolved"
  "closed"
  "shipped"
)

# Prefer .env, but allow local.env fallback for compatibility.
if [[ ! -f "${ENV_FILE}" ]]; then
  if [[ -f "${ROOT_DIR}/local.env" ]]; then
    ENV_FILE="${ROOT_DIR}/local.env"
  else
    echo "ERROR: .env not found at ${ROOT_DIR}/.env" >&2
    echo "Also checked fallback file: ${ROOT_DIR}/local.env" >&2
    exit 1
  fi
fi

if [[ ! -f "${COMPOSE_FILE}" ]]; then
  echo "ERROR: compose.yml not found at ${COMPOSE_FILE}" >&2
  exit 1
fi

read_env_value() {
  local key="$1"
  local file="$2"

  local line
  line="$(grep -E "^[[:space:]]*${key}[[:space:]]*=" "${file}" | tail -n 1 || true)"
  if [[ -z "${line}" ]]; then
    return 1
  fi

  line="${line#*=}"
  line="${line%%#*}"
  line="$(echo "${line}" | sed -E 's/^[[:space:]]+//; s/[[:space:]]+$//')"

  if [[ "${line}" =~ ^\".*\"$ ]]; then
    line="${line:1:${#line}-2}"
  elif [[ "${line}" =~ ^\'.*\'$ ]]; then
    line="${line:1:${#line}-2}"
  fi

  printf '%s' "${line}"
}

DB_NAME="$(read_env_value "AFT_DB_NAME" "${ENV_FILE}" || true)"
DB_USER="$(read_env_value "AFT_DB_USER" "${ENV_FILE}" || true)"
DB_PASS="$(read_env_value "AFT_DB_PASSWORD" "${ENV_FILE}" || true)"

# Fallback to common compose/.env naming used by AFT.
if [[ -z "${DB_NAME}" ]]; then DB_NAME="$(read_env_value "MYSQL_DATABASE" "${ENV_FILE}" || true)"; fi
if [[ -z "${DB_USER}" ]]; then DB_USER="$(read_env_value "MYSQL_USER" "${ENV_FILE}" || true)"; fi
if [[ -z "${DB_PASS}" ]]; then DB_PASS="$(read_env_value "MYSQL_PASSWORD" "${ENV_FILE}" || true)"; fi

if [[ -z "${DB_NAME}" || -z "${DB_USER}" || -z "${DB_PASS}" ]]; then
  echo "ERROR: Could not resolve DB credentials from ${ENV_FILE}." >&2
  echo "Expected either AFT_DB_NAME/AFT_DB_USER/AFT_DB_PASSWORD or MYSQL_DATABASE/MYSQL_USER/MYSQL_PASSWORD." >&2
  exit 1
fi

DB_CONTAINER="$(awk '
  BEGIN { in_services=0; in_db=0; db_indent=-1 }
  /^[[:space:]]*services:[[:space:]]*$/ { in_services=1; next }
  in_services {
    if ($0 ~ /^[^[:space:]]/) { in_services=0; in_db=0 }
    if ($0 ~ /^[[:space:]]{2}db:[[:space:]]*$/) { in_db=1; db_indent=2; next }
    if (in_db) {
      if ($0 ~ /^[[:space:]]{2}[a-zA-Z0-9_-]+:[[:space:]]*$/ && $0 !~ /^[[:space:]]{2}db:[[:space:]]*$/) {
        in_db=0
      }
      if ($0 ~ /^[[:space:]]{4}container_name:[[:space:]]*/) {
        line=$0
        sub(/^[[:space:]]{4}container_name:[[:space:]]*/, "", line)
        gsub(/[[:space:]]+$/, "", line)
        print line
        exit
      }
    }
  }
' "${COMPOSE_FILE}" || true)"

if [[ -z "${DB_CONTAINER}" ]]; then
  echo "ERROR: Could not determine db.container_name from compose.yml" >&2
  exit 1
fi

if [[ "${DB_CONTAINER}" != "${EXPECTED_DB_CONTAINER}" ]]; then
  echo "ERROR: compose.yml db container_name is '${DB_CONTAINER}', expected '${EXPECTED_DB_CONTAINER}'." >&2
  echo "Refusing to continue to avoid writing to the wrong database container." >&2
  exit 1
fi

if ! docker ps --format '{{.Names}}' | grep -Fxq "${DB_CONTAINER}"; then
  echo "ERROR: Container '${DB_CONTAINER}' is not running." >&2
  echo "Start services first: docker compose up -d" >&2
  exit 1
fi

# Build SQL IN list for synonyms.
IN_LIST=""
for s in "${DONE_SYNONYMS[@]}"; do
  if [[ -n "${IN_LIST}" ]]; then IN_LIST+=","; fi
  IN_LIST+="'${s}'"
done

# Normalization mirrors app logic: lower, trim, remove punctuation, collapse spaces.
NORMALIZED_COLUMN_NAME_SQL="TRIM(REGEXP_REPLACE(LOWER(REGEXP_REPLACE(col.name, '[^[:alnum:] ]', ' ')), '[[:space:]]+', ' '))"

# Use a deduplicated working_style view to avoid row multiplication if board_settings has duplicates.
WORKING_STYLE_JOIN="
LEFT JOIN (
  SELECT board_id, MAX(value) AS value
  FROM board_settings
  WHERE \`key\` = 'working_style'
  GROUP BY board_id
) bs ON bs.board_id = b.id
"

DONE_STATE_PREDICATE="
(
  (c.done = 1 AND COALESCE(bs.value, '\"kanban\"') IN ('\"agile\"', 'agile'))
  OR (${NORMALIZED_COLUMN_NAME_SQL} IN (${IN_LIST}))
)
"

COUNTS_SQL="
SELECT
  COUNT(*) AS total_cards_considered,
  SUM(is_done_state) AS cards_in_done_state,
  SUM(is_done_state * done_ts_null) AS done_missing_done_timestamp,
  SUM(is_done_state * done_ts_null * updated_at_present) AS cards_can_be_updated
FROM (
  SELECT
    c.id,
    MAX(CASE WHEN ${DONE_STATE_PREDICATE} THEN 1 ELSE 0 END) AS is_done_state,
    CASE WHEN c.done_datetime IS NULL THEN 1 ELSE 0 END AS done_ts_null,
    CASE WHEN c.updated_at IS NOT NULL THEN 1 ELSE 0 END AS updated_at_present
  FROM cards c
  JOIN columns col ON col.id = c.column_id
  JOIN boards b ON b.id = col.board_id
  ${WORKING_STYLE_JOIN}
  GROUP BY c.id, c.done_datetime, c.updated_at
) t;
"

CANDIDATE_SQL="
SELECT
  b.id AS board_id,
  b.name AS board_name,
  col.id AS column_id,
  col.name AS column_name,
  c.id AS card_id,
  c.title AS card_title,
  c.done,
  c.updated_at,
  c.done_datetime,
  CASE
    WHEN c.done = 1 AND COALESCE(bs.value, '\"kanban\"') IN ('\"agile\"', 'agile') THEN 'agile_done'
    WHEN ${NORMALIZED_COLUMN_NAME_SQL} IN (${IN_LIST}) THEN 'done_column'
    ELSE 'n/a'
  END AS match_reason
FROM cards c
JOIN columns col ON col.id = c.column_id
JOIN boards b ON b.id = col.board_id
${WORKING_STYLE_JOIN}
WHERE c.done_datetime IS NULL
  AND ${DONE_STATE_PREDICATE}
ORDER BY b.name, col.name, c.id;
"

echo "Inspecting done-timestamp candidates in container '${DB_CONTAINER}' (database '${DB_NAME}')..."

COUNTS_RAW="$(docker exec -e MYSQL_PWD="${DB_PASS}" "${DB_CONTAINER}" \
  mysql -N -B -u"${DB_USER}" "${DB_NAME}" -e "${COUNTS_SQL}")"

IFS=$'\t' read -r TOTAL_CARDS_CONSIDERED CARDS_IN_DONE_STATE DONE_MISSING_DONE_TS CARDS_CAN_BE_UPDATED <<< "${COUNTS_RAW}"

TOTAL_CARDS_CONSIDERED="${TOTAL_CARDS_CONSIDERED:-0}"
CARDS_IN_DONE_STATE="${CARDS_IN_DONE_STATE:-0}"
DONE_MISSING_DONE_TS="${DONE_MISSING_DONE_TS:-0}"
CARDS_CAN_BE_UPDATED="${CARDS_CAN_BE_UPDATED:-0}"

echo
echo "Summary:"
echo "  Total cards considered: ${TOTAL_CARDS_CONSIDERED}"
echo "  Cards in a done state: ${CARDS_IN_DONE_STATE}"
echo "  Cards done but missing done timestamp: ${DONE_MISSING_DONE_TS}"
echo "  Cards that can be updated now: ${CARDS_CAN_BE_UPDATED}"

if [[ "${DONE_MISSING_DONE_TS}" -eq 0 ]]; then
  echo
  echo "No cards are missing done timestamps. Nothing to update."
  exit 0
fi

if [[ "${CARDS_CAN_BE_UPDATED}" -eq 0 ]]; then
  echo
  echo "No cards are eligible for update because all done-state cards missing done_datetime also have updated_at IS NULL."
  echo "Nothing will be updated."
  exit 0
fi

CANDIDATES_RAW="$(docker exec -e MYSQL_PWD="${DB_PASS}" "${DB_CONTAINER}" \
  mysql -N -B -u"${DB_USER}" "${DB_NAME}" -e "${CANDIDATE_SQL}")"

if [[ -z "${CANDIDATES_RAW}" ]]; then
  echo "No card rows returned for preview despite summary counts. No update applied."
  exit 0
fi

echo
echo "Candidates grouped by board/column:"
echo "----------------------------------"

echo "${CANDIDATES_RAW}" | awk -F'\t' '
  BEGIN {
    current_group = ""
    total = 0
  }
  {
    board = $2
    column = $4
    group = board "|" column

    if (group != current_group) {
      if (current_group != "") {
        printf("\n")
      }
      printf("Board: %s\n", board)
      printf("  Column: %s\n", column)
      current_group = group
    }

    printf("    - Card #%s: %s [reason=%s, updated_at=%s]\n", $5, $6, $10, $8)
    total += 1
  }
  END {
    printf("\nPreview rows shown (cards done + missing done timestamp): %d\n", total)
  }
'

echo
echo "This update sets: done_datetime = updated_at"
echo "Only for eligible cards listed above (currently done_datetime IS NULL and updated_at IS NOT NULL)."
echo
echo "Pre-update recap:"
echo "  Total cards considered: ${TOTAL_CARDS_CONSIDERED}"
echo "  Cards in a done state: ${CARDS_IN_DONE_STATE}"
echo "  Cards done but missing done timestamp: ${DONE_MISSING_DONE_TS}"
echo "  Cards that can be updated now (updated_at present to copy): ${CARDS_CAN_BE_UPDATED}"
echo "  Expected rows updated after confirmation: ${CARDS_CAN_BE_UPDATED}"
read -r -p "Proceed with update? [y/N]: " CONFIRM

if [[ ! "${CONFIRM}" =~ ^[Yy]$ ]]; then
  echo "Cancelled. No changes were made."
  exit 0
fi

UPDATE_SQL="
UPDATE cards c
JOIN columns col ON col.id = c.column_id
JOIN boards b ON b.id = col.board_id
${WORKING_STYLE_JOIN}
SET c.done_datetime = c.updated_at
WHERE c.done_datetime IS NULL
  AND c.updated_at IS NOT NULL
  AND ${DONE_STATE_PREDICATE};
SELECT ROW_COUNT() AS rows_updated;
"

UPDATE_RESULT="$(docker exec -e MYSQL_PWD="${DB_PASS}" "${DB_CONTAINER}" \
  mysql -N -B -u"${DB_USER}" "${DB_NAME}" -e "${UPDATE_SQL}")"

ROWS_UPDATED="$(echo "${UPDATE_RESULT}" | tail -n 1)"
echo "Update complete. Rows updated: ${ROWS_UPDATED}"

if [[ "${ROWS_UPDATED}" != "${CARDS_CAN_BE_UPDATED}" ]]; then
  echo "WARNING: Expected to update ${CARDS_CAN_BE_UPDATED} card(s), but updated ${ROWS_UPDATED}." >&2
  echo "This indicates data changed between preview and update, or a query mismatch that needs investigation." >&2
else
  echo "Update count matches expected eligible count (${CARDS_CAN_BE_UPDATED})."
fi
