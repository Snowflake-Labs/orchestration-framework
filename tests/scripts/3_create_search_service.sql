CREATE CORTEX SEARCH SERVICE IF NOT EXISTS CUBE_TESTING.PUBLIC.SEC_SEARCH_SERVICE
    ON CHUNK
    attributes RELATIVE_PATH
    warehouse='CUBE_TESTING'
    target_lag='DOWNSTREAM'
    AS (
    SELECT
        RELATIVE_PATH,
        CHUNK
    FROM SEC_CHUNK_SEARCH
);