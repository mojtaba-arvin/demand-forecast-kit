# Stockout and backorder simulation

`simulate_inventory_policy` provides a deterministic single-item periodic-review simulation for comparing replenishment policies against a demand sequence. It models delayed receipts, fixed order quantities, inventory position, stockout days, lost sales, and backorder carry-forward.

Backorders are fulfilled before current-day demand. In lost-sales mode, unmet demand is recorded and discarded. Orders placed on day t arrive at the start of day t + lead_time_days. This intentionally small model does not include stochastic lead times, partial supplier receipts, order costs, holding costs, or multi-echelon allocation; use the inventory evaluation module for cost analysis and the network module for echelon positions.
