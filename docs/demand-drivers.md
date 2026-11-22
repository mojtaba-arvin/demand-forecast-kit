# Price and promotion diagnostics

`estimate_demand_driver_effects` fits a small ordinary-least-squares diagnostic for demand as a function of price and a promotion indicator. It reports conditional linear associations and R-squared, not causal price elasticity or causal promotion lift. Pricing and promotion are often selected in response to expected demand, and omitted factors such as seasonality, stock availability, and campaigns can confound the coefficients.

Fit only on the training window available at each forecast origin. Evaluate any downstream use on a later temporal holdout, and do not use holdout observations to choose the model or coefficients. This diagnostic is separate from the ForecastAdapter contract; it does not silently inject exogenous variables into existing adapters.
