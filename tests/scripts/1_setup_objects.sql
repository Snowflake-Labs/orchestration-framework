CREATE DATABASE IF NOT EXISTS CUBE_TESTING;
CREATE WAREHOUSE IF NOT EXISTS CUBE_TESTING 
    WAREHOUSE_SIZE = 'XSMALL'
    AUTO_SUSPEND = 60;
CREATE STAGE IF NOT EXISTS CUBE_TESTING.PUBLIC.ANALYST;
CREATE STAGE IF NOT EXISTS CUBE_TESTING.PUBLIC.DATA;
CREATE TABLE IF NOT EXISTS CUBE_TESTING.PUBLIC.SEC_CHUNK_SEARCH (
    RELATIVE_PATH VARCHAR,
    CHUNK VARCHAR
);
CREATE TABLE IF NOT EXISTS CUBE_TESTING.PUBLIC.SP500 (
	EXCHANGE VARCHAR,
	SYMBOL VARCHAR,
	SHORTNAME VARCHAR,
	LONGNAME VARCHAR,
	SECTOR VARCHAR,
	INDUSTRY VARCHAR,
	CURRENTPRICE NUMBER(38,3),
	MARKETCAP NUMBER(38,0),
	EBITDA NUMBER(38,0),
	REVENUEGROWTH NUMBER(38,3),
	CITY VARCHAR,
	STATE VARCHAR,
	COUNTRY VARCHAR,
	FULLTIMEEMPLOYEES NUMBER(38,0),
	LONGBUSINESSSUMMARY VARCHAR,
	WEIGHT NUMBER(38,20)
);