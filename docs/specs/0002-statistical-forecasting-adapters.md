# SPEC 0002: Statistical forecasting adapters

- Status: implemented on `work/statistical-adapters`; real-backend CI validation runs in the dedicated optional-dependency job.
- Scope: optional CPU statistical adapters implementing the existing `ForecastAdapter` protocol.
- Backend: Nixtla StatsForecast 2.1.x, loaded lazily through the `stats` extra.
- Non-goals: automatic model routing, hyperparameter tuning across the full catalogue, model ensembles, GPU execution, external datasets, and accuracy/performance claims.

## Adapters

1. `AutoETSAdapter`: automatic ETS selection with StatsForecast's native prediction intervals.
2. `AutoARIMAAdapter`: stepwise AutoARIMA model selection with native prediction intervals.
3. `ThetaAdapter`: standard Theta model with native prediction intervals. Additive decomposition is the default so demand series containing zeroes are not rejected by a multiplicative decomposition.
4. `CrostonAdapter`: CrostonClassic, CrostonOptimized (default), or CrostonSBA.
5. `TSBAdapter`: Teunter-Syntetos-Babai with configurable demand-size and occurrence-probability smoothing parameters.
6. Existing `SeasonalNaiveAdapter` remains the dependency-free reference baseline.

## Quantile contract

StatsForecast provides a point forecast and symmetric central interval bounds. The adapters map the point forecast to the 0.5 quantile and lower/upper interval bounds to their corresponding marginal quantiles. The mapping is explicit and limited to quantile probabilities that correspond to integer central-interval percentages supported by StatsForecast. Negative lower bounds are clipped to zero because demand is non-negative.

AutoETS, AutoARIMA, and Theta use model-native predictive intervals. Croston and TSB use StatsForecast `ConformalIntervals` with rolling calibration windows because their future intervals require an explicit conformal interval configuration. At least `2 * horizon + 1` training observations are required for two complete conformal windows.

These are marginal demand distributions at each horizon step. They are not joint paths and must not be summed to create cumulative lead-time demand quantiles. The median-as-point-forecast mapping and symmetric intervals are adapter conventions; users should inspect calibration and coverage on their own data before operational use.

## Runtime and dependencies

- The core install remains unchanged; StatsForecast is exposed as an optional `stats` extra.
- Importing the core package does not import StatsForecast.
- Adapters fail with an actionable install message when the optional dependency is absent.
- The integration CI job installs the extra, exercises every adapter against deterministic synthetic histories, audits the resolved dependencies, and creates synthetic-only evaluation artifacts.
- No external data or model weights are downloaded by the test suite.

## Acceptance criteria

- Every adapter implements the common protocol and returns finite, non-negative, monotone quantile forecasts with the requested horizon and quantile levels.
- Tests exercise AutoETS, AutoARIMA, Theta, CrostonClassic, CrostonOptimized, CrostonSBA, and TSB through the installed StatsForecast backend.
- Invalid histories, quantile probabilities, alpha parameters, seasons, and conformal-window sizes fail explicitly.
- Backtesting evaluates the statistical adapters using the same chronological folds as the seasonal-naive baseline.
- Both the base CI job and the optional statistical-adapter integration job pass.
- Synthetic reports are explicitly described as pipeline smoke evidence, not forecast-quality benchmarks.
