The core package is country- and calendar-agnostic. Community extensions may provide holidays, trading days, retail events, and local fiscal calendars.

Calendar packages must declare jurisdiction, source provenance, license, version, timezone semantics, and update policy. The core library must not silently infer a country's holidays from locale or system settings.
