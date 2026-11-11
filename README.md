# ONScan

## ONScan Observatory — new direction

Start with [OBSERVATORY.md](OBSERVATORY.md): a dependency-free local sensor ledger, unit-aware threshold alerts, visual report and read-only MCP access. Run the included synthetic [demo.jsonl](demo.jsonl) to reproduce the report. Camera/thermal/sensor adapters emit a common observation contract; actual device drivers and AI inference are not bundled yet. The original Laravel application remains below.


Employee-temperature dashboard prototype maintained in the [Stark Fiber Enterprise](https://starkfiber.my) repository portfolio.

## What is here

A Laravel application with authenticated dashboard, reports and employee-temperature routes. The repository contains application source, database migrations and PHPUnit configuration.

## Development status

This is a legacy prototype, not a currently qualified hosted service. The checked-in manifest targets Laravel 8 and PHP 7.3/8.0 and includes a MongoDB integration. A fresh installation and the database configuration have not been verified in this maintenance review. The repository does not currently include an environment-example file; do not assume a copied Laravel quick-start is sufficient.

## Upgrade priorities

1. Document the required environment variables and database schema using placeholder values only.
2. Reproduce the existing application in an isolated development environment using the lockfiles; record a passing baseline.
3. Add tests for login, record ownership, authorised report access and validation of temperature readings.
4. Plan framework and dependency upgrades in reviewable steps, with database backup and migration rollback checks.
5. Define consent, retention and access controls before collecting real employee information.

Use synthetic records during development. Do not upload employee records, credentials or production database exports to issues.

## Contributions and licence

Open an issue with the affected route, expected behaviour and a redacted reproduction. Application changes should include their relevant tests. See [LICENSE](LICENSE); Laravel and other dependencies retain their own licences.

