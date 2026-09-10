#!/bin/sh
set -eu
for migration in /migrations/*.sql; do
    psql -v ON_ERROR_STOP=1 --username ticketing --dbname ticketing -f "$migration"
done
psql -v ON_ERROR_STOP=1 --username ticketing --dbname ticketing -c 'GRANT SELECT ON orders TO ticketing_metrics'
