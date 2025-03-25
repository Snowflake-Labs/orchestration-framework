SQL_RESPONSE = """{'output':                   LONGNAME                  SECTOR  \
 0    Microsoft Corporation              Technology
 1               Apple Inc.              Technology
 2       NVIDIA Corporation              Technology
 3            Alphabet Inc.  Communication Services
 4         Amazon.com, Inc.       Consumer Cyclical
 5     Meta Platforms, Inc.  Communication Services
 6  Berkshire Hathaway Inc.      Financial Services
 7    Eli Lilly and Company              Healthcare
 8            Broadcom Inc.              Technology
 9     JPMorgan Chase & Co.      Financial Services

                          INDUSTRY  CURRENTPRICE      MARKETCAP        EBITDA  \
 0       Software - Infrastructure        423.85  3150184448000  1.259820e+11
 1            Consumer Electronics        196.89  3019131060224  1.296290e+11
 2                  Semiconductors       1208.88  2973639376896  4.927500e+10
 3  Internet Content & Information        174.46  2164350779392  1.097230e+11
 4                 Internet Retail        184.30  1917936336896  9.660900e+10
 5  Internet Content & Information        492.96  1250407743488  6.844700e+10
 6         Insurance - Diversified        413.72   892609101824  1.070460e+11
 7    Drug Manufacturers - General        849.99   807834746880  1.337370e+10
 8                  Semiconductors       1406.64   651866537984  2.040400e+10
 9             Banks - Diversified        199.95   574190387200           NaN

    EBITDA_MARGIN_PERCENTAGE
 0                  3.999194
 1                  4.293587
 2                  1.657060
 3                  5.069557
 4                  5.037133
 5                  5.473974
 6                 11.992484
 7                  1.655499
 8                  3.130089
 9                       NaN  ,
 'sources': {'tool_type': 'SQL', 'tool_name': 'margin_eval', 'metadata': None}}"""
