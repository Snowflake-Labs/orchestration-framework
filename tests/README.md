# Testing Configuration

This project uses the [pytest](https://docs.pytest.org/en/latest/) framework to
automate testing. To run the tests, you will need a Snowflake account with permission
to create a database and a virtual warehouse.

## Setting up your environment

To connect to Snowflake, create a file named `.env` in the root directory of the
project. Add the following environment variables to the file, adjusting the
authentication details to match your Snowflake account and preference for
connecting.

```bash
SNOWFLAKE_ACCOUNT=<account_name>
SNOWFLAKE_USER=<username>
SNOWFLAKE_PASSWORD=<password>
SNOWFLAKE_WAREHOUSE=<warehouse_name>
SNOWFLAKE_ROLE=<role_name>
```

A database named `CUBE_TESTING` will be automatically created with the necessary
objects to perform the tests.

## Running the tests

```bash
poetry run pytest
```
