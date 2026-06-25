-- =============================================================================
-- Energy Fraud Detection — raw data export (customers + transactions)
-- Run top-to-bottom in a Databricks SQL Editor (or notebook) on any SQL
-- Warehouse with Unity Catalog. Idempotent (CREATE OR REPLACE).
--
-- Set the target catalog/schema below to one you can write to, then run.
-- =============================================================================

USE CATALOG main;                          -- change to your catalog
CREATE SCHEMA IF NOT EXISTS fraud;         -- change to your schema if you like
USE SCHEMA fraud;


-- customers --------------------------------------------------------------------
CREATE OR REPLACE TABLE customers (
    customer_id               STRING,
    name                      STRING,
    region                    STRING,
    account_age_days          INT,
    meter_trust_score         DECIMAL(2,2),
    past_fraud                BOOLEAN,
    property_type             STRING,
    baseline_consumption_kwh  INT
) USING DELTA;

INSERT INTO customers VALUES
('CUST1001','Alice Johnson'  ,'North'  , 820,0.90,false,'Single Family Home' ,450),
('CUST1002','Rahul Mehta'    ,'East'   ,  45,0.40,true ,'Apartment'          ,280),
('CUST1003','Chen Wei'       ,'West'   , 200,0.60,false,'Townhouse'          ,350),
('CUST1004','Fatima Al-Sayed','South'  ,  10,0.30,false,'Apartment'          ,250),
('CUST1005','Maria Gonzalez' ,'Central', 365,0.80,false,'Single Family Home' ,420),
('CUST1006','John Smith'     ,'North'  ,1500,0.95,false,'Single Family Home' ,480),
('CUST1007','Igor Petrov'    ,'East'   ,  90,0.30,true ,'Industrial Unit'    ,1200),
('CUST1008','Aisha Mohamed'  ,'South'  ,  25,0.20,false,'Apartment'          ,220),
('CUST1009','David Cohen'    ,'West'   , 720,0.88,false,'Townhouse'          ,380),
('CUST1010','Omar Reza'      ,'Central',  12,0.10,true ,'Apartment'          ,260),
('CUST1011','Kim Min-Ji'     ,'North'  , 540,0.70,false,'Townhouse'          ,370),
('CUST1012','Hassan Ali'     ,'East'   ,  30,0.25,true ,'Commercial Building',950),
('CUST1013','Elena Rossi'    ,'South'  ,2000,0.92,false,'Single Family Home' ,410),
('CUST1014','Mohammed Jafar' ,'West'   ,   5,0.15,false,'Apartment'          ,240);


-- transactions -----------------------------------------------------------------
CREATE OR REPLACE TABLE transactions (
    reading_id       STRING,
    customer_id      STRING,
    consumption_kwh  INT,
    meter_id         STRING,
    reading_type     STRING,
    timestamp        TIMESTAMP
) USING DELTA;

INSERT INTO transactions VALUES
('TX1001','CUST1001', 520,'MTR-N-1001','Automated',to_timestamp('2025-09-28T14:33:00Z')),
('TX1002','CUST1002',1500,'MTR-E-1002','Automated',to_timestamp('2025-09-28T18:10:00Z')),
('TX1003','CUST1003', 300,'MTR-W-1003','Automated',to_timestamp('2025-09-28T19:00:00Z')),
('TX1004','CUST1004', 990,'MTR-S-1004','Automated',to_timestamp('2025-09-28T20:22:00Z')),
('TX1005','CUST1005', 400,'MTR-C-1005','Automated',to_timestamp('2025-09-29T10:15:00Z')),
('TX2001','CUST1005', 999,'MTR-C-1005','Automated',to_timestamp('2025-09-29T09:00:00Z')),
('TX2002','CUST1005', 998,'MTR-C-1005','Automated',to_timestamp('2025-09-29T10:30:00Z')),
('TX2003','CUST1005', 997,'MTR-C-1005','Automated',to_timestamp('2025-09-29T12:00:00Z')),
('TX1006','CUST1006', 470,'MTR-N-1006','Automated',to_timestamp('2025-09-29T11:45:00Z')),
('TX1007','CUST1007',1800,'MTR-E-1007','Automated',to_timestamp('2025-09-29T12:30:00Z')),
('TX1008','CUST1008',  40,'MTR-S-1008','Manual'   ,to_timestamp('2025-09-29T14:00:00Z')),
('TX1009','CUST1009', 390,'MTR-W-1009','Automated',to_timestamp('2025-09-29T14:45:00Z')),
('TX1010','CUST1010', 600,'MTR-C-1010','Automated',to_timestamp('2025-09-29T15:30:00Z')),
('TX1011','CUST1011', 320,'MTR-N-1011','Automated',to_timestamp('2025-09-29T16:15:00Z')),
('TX1012','CUST1012',1100,'MTR-E-1012','Manual'   ,to_timestamp('2025-09-29T16:45:00Z')),
('TX1013','CUST1013', 405,'MTR-S-1013','Automated',to_timestamp('2025-09-29T17:20:00Z')),
('TX1014','CUST1014',  25,'MTR-W-1014','Manual'   ,to_timestamp('2025-09-29T17:50:00Z'));


-- verify -----------------------------------------------------------------------
SELECT 'customers' AS table, COUNT(*) AS rows FROM customers
UNION ALL
SELECT 'transactions', COUNT(*) FROM transactions;
