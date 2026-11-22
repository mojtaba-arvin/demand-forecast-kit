# Comparing inventory policies

`compare_inventory_policies` evaluates two or more named policies against the same realized lead-time scenarios. Each policy specifies underage/overage costs (which select its newsvendor target quantile), holding/shortage cost rates (which score realized outcomes), and pack size. Compare total cost, fill rate, cycle service, shortages, and ending inventory together; do not select a policy using a holdout set that is also reported as final evaluation evidence.
