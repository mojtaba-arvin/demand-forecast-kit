# Hierarchical SKU/location history

`build_hierarchical_history` accepts a frame with SKU, location, timestamp, and demand columns. It returns three aligned series levels: SKU-location leaves, SKU totals across locations, and location totals across SKUs. Each leaf references both aggregate parents, so this is a hierarchy DAG; consumers must not sum both aggregate axes together because that would double-count demand. Duplicate leaf observations are rejected and IDs use JSON-encoded key tuples to avoid delimiter collisions.
