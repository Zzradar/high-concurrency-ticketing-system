# Phase18 migration016: Layout function resolution audit

Migration013 and migration014 introduce no SQL/PLpgSQL functions. Migration015 introduces exactly the six functions below. All six were SECURITY INVOKER with NULL proconfig, inherited caller search_path, and could resolve permanent tables or helpers through a temporary or preceding ordinary schema. Migration016 replaces their bodies in place; signatures and trigger function OIDs remain unchanged. It does not alter 001–015 or change the revision architecture.

| Function (installed in the application schema) | Permanent references after 016 | Helper binding |
|---|---|---|
| bump_session_layout_revisions(text[]) | installation-schema.session_layout_revisions | none |
| maintain_session_layout_identity() | TG_TABLE_SCHEMA.session_layout_revisions | TG_TABLE_SCHEMA.bump_session_layout_revisions |
| maintain_layout_session_seats() | none; executor transition relations only | TG_TABLE_SCHEMA.bump_session_layout_revisions |
| maintain_layout_seats() | TG_TABLE_SCHEMA.session_seats | TG_TABLE_SCHEMA.bump_session_layout_revisions |
| maintain_layout_venue_zones() | TG_TABLE_SCHEMA.session_seats, TG_TABLE_SCHEMA.seats | TG_TABLE_SCHEMA.bump_session_layout_revisions |
| maintain_layout_inventory_truncate() | TG_TABLE_SCHEMA.session_seats | TG_TABLE_SCHEMA.bump_session_layout_revisions |

All six remain SECURITY INVOKER and have `proconfig = {search_path=pg_catalog}`. Trigger SQL uses `pg_catalog.format` with `%1$I` for the system-provided TG_TABLE_SCHEMA; table/function identifiers are fixed literals. No data value is interpolated into SQL. The helper's affected array remains a PL/pgSQL parameter. The helper body embeds the quoted installation schema resolved once from the existing helper function OID during the trusted migration, not from a later caller or current_schema(). As with prior migrations, installation must explicitly select the intended schema. Renaming that schema requires regenerating the helper body by rerunning016; arbitrary schema renames are not an application migration path.

`new_rows`, `old_rows`, and `changed` are executor transition relations/CTEs, not permanent business objects. Tests create conflicting temporary relations with these names and incompatible columns, proving the executor relations retain precedence. pg_catalog types, catalogs and format/cardinality calls are explicit. There is no SECURITY DEFINER privilege expansion; the business writer needs SELECT and the applicable static UPDATE plus UPDATE(revision), just as revision maintenance already required. Missing revision permission fails and rolls back the content write; it cannot silently skip the revision.

The once-per-Session statement projection, empty-array guard, sorted revision row locking, transaction atomicity and body/revision single-statement read snapshot are unchanged. Dynamic inventory status/version updates execute no revision UPDATE. Runtime dynamic SQL adds parsing/planning work to static content writes; after-v3 must report measured costs without reusing after-v2 numbers.

The old independent counterexample was reproduced on installed015: public revision4, temporary revision5, changed price body with unchanged ETag and304. After016, the same script assertions pass: public revision5, temporary revision4, changed ETag and200. This closes the search_path defect; the old checkpoint and after-v2 remain invalidated historical evidence, not deployable deliveries.

Tests cover installed015 upgrade/OID preservation, fresh nonpublic installation, failed migration rollback, repeat016, temporary and ordinary shadow tables/functions, incompatible temporary structures, actual minimum-role commit, denied permission rollback, late trigger failure, and the existing complete Layout representation/HTTP/bulk publication suite. Installed pg_get_functiondef/proconfig snapshots are retained with the new capability evidence.
