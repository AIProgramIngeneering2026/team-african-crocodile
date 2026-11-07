# Требования
- Scenario 1: Convert Celsius to Fahrenheit (Unit Converter: temperature)
- Scenario 2: Request weather of a city. (OpenWeatherMap: API)
- Scenario 3: Convert kilometers to miles (Unit Converter: length)
- Scenario 4: Convert a text to Title-case (text transformer: title)
- Scenario 5: API fetch timeout (error)
- Scenario 6: Incompatible unit categories (error)

# Цель и участник

### Scenario 1: Convert Celsius to Fahrenheit (Unit Converter: temperature)

The Goal:

- To accurately convert temprature units, fast and easy.

Participant:
- Scientific Researchers.

### Scenario 2: Request weather of a city. (OpenWeatherMap: API)

The Goal:

- To accurately measure the current hummidity, temprature, air presure and wind speed in specific city.

Participant:
- Scientific Researchers.

### Scenario 3: Convert kilometers to miles (Unit Converter: length)

The Goal:

- To accurately convert length units 

Participant:
- Civil Engineers


### Scenario 4: Convert a text to Title-case (text transformer: title)

The Goal:

- To format text into required formating format.

Participant:

- Authors

### Scenario 5: API fetch timeout (error)

The Goal:

- To do not wait forever

Participant:

- Scientific Researchers.

### Scenario 6: Incompatible unit categories (error)

The Goal:

- To avoid measurement error

Participant:

- Civil Engineers

# Основной поток по шагам

### Scenario 1: Convert Celsius to Fahrenheit (Unit Converter: temperature)

1. Researcher inputs: value **25 °C**, target unit **°F**, precision **2 decimal places**, optional measurement uncertainty **±0.1 °C**, **experiment/sample id**.
2. Tool validates: target unit is supported.
3. Tool converts using the canonical formula.
4. Tool propagates uncertainty: ±0.1 °C × 9/5 = ±0.18 °F → **77.00 ± 0.18 °F**.
5. Tool saves result and **experiment/sample id** in a history record.
6. Return result: **77.00 ± 0.18  °F**.

### Scenario 2: Request weather of a city. (OpenWeatherMap: API)

1. User requests current weather for **London**, **GB**, **units metric**.
2. Cache for `London+metric` is **empty**.
3. System resolves city → `cityId=2643743`, `lat/lon`.
4. System calls OpenWeatherMap.
5. API returns: **15.2 °C**, **72%**, **1013 hPa**, 4.5 m/s, observed at **14:20**.
6. System validates fields and ranges.
7. System caches the result with **TTL = 10 min**.
8. Return the result:  **15.2 °C**, **72%**, **1013 hPa**

### Scenario 3: Convert kilometers to miles (Unit Converter: length)

1. Civil engineer inputs bridge span **12.345 km**. 
Requests conversion to **miles** with **3 decimal places**. 
2. Tool validates: value is positive, finite, within supported range. 
3. Tool resolves unit pair `km → mi` and looks up the **exact conversion factor** from the unit registry: 1 `km = 0 621371192237334 mi` (derived from `1 mile = 1.609344 km` exactly). 
4. Tool computes raw result: **7 670998... mi.** 
5. Tool applies rounding rule: **half-up to 3 decimals → 7.671 mi**. 
6. Tool records the conversion: input, output, factor id version, rounding rule, timestamp, engineer id. 
7. Result return: **7.671 mi** (rounded), plus raw value and the exact factor used.

### Scenario 4: Convert a text to Title-case (text transformer: title)

1. Author inputs text: `"the quick brown fox jumps over the lazy dog"`.

2. Author selects profile: `title-basic-v1`.

3. Tool validates: text is non-empty, within length limit, profile exists, characters supported.

4. Tool tokenizes the text and applies `title-basic-v1`.

5. Tool saves a transformation record: input, output, profile id/version, timestamp, author id, document id.

6. Return result: “The Quick Brown Fox Jumps Over The Lazy Dog”, profile title-basic-v1, timestamp.


# Критерии приемки  в виде Дано / Когда / Тогда (BDD) или по шаблонам EARS

### Scenario 1: Convert Celsius to Fahrenheit (Unit Converter: temperature)

1. **Ubiquitous — always true: [Subject] shall [Action]**

    **Bad**: “It would be good if the tool converted temperatures accurately.”

    **EARS**: The tool **shall** convert temperature values using the canonical formulas: °F = °C × 9/5 + 32, K = °C + 273.15.

    **EARS**: The tool **shall** support the temperature units °C, °F, and K.

    **EARS**: The tool **shall** save every successful conversion result together with the experiment/sample id in a history record.

2. **Event-driven — triggered by event: WHEN [Event], [Subject] shall [Action]**

    **EARS**: **WHEN** the researcher submits a conversion request with value 25 °C, target unit °F, precision 2, and experiment/sample id EXP-2026-041, the tool **shall** validate that °F is a supported target unit.

    **EARS**: **WHEN** validation succeeds, the tool **shall** convert the value using the canonical formula °F = °C × 9/5 + 32, producing raw result 77.0 °F.

    **EARS**: **WHEN** conversion completes, the tool **shall** apply the requested precision of 2 decimal places, producing 77.00 °F.

    **EARS**: **WHEN** conversion completes, the tool **shall** return the result 77.00 ± 0.18 °F to the researcher.

3. **State-driven — while in a state: WHILE [State], [Subject] shall [Action]**

    **Bad:** “While converting, show something.”

    **EARS: WHILE** a conversion request is being processed, the tool **shall** display a loading state and **shall not** accept a duplicate submission of the same request.

    **EARS: WHILE** the experiment/sample id is associated with a conversion record, the tool **shall** keep that association immutable in the history.

4. **Unwanted behavior — failure handling: IF [Failure/undesired event], THEN [Subject] shall [Action]**

    **Bad:** “If the unit is wrong, tell the user.”

    **EARS: IF** the requested target unit is not one of °C, °F, K, **THEN** the tool **shall** reject the request, produce no result, save error history record, and return an error listing the supported units.

    **EARS: IF** the input value is below absolute zero (−273.15 °C), **THEN** the tool **shall** reject the request, produce no result, save error history record, and return the error “Value is below absolute zero.”

    **EARS: IF** the requested precision is outside 0–6 decimal places, **THEN** the tool **shall** reject the request and return the error “Precision must be between 0 and 6.”

    **EARS: IF** the measurement uncertainty is negative, **THEN** the tool **shall** reject the request and return the error “Uncertainty must be non-negative.”

    **EARS: IF** the experiment/sample id is missing, **THEN** the tool **shall** regenarate experiment/sample id and shall not save a history record without it.

5. **Optional features — only when a condition/resource exists: WHERE [Condition], [Subject] shall [Action]**

    **Bad:** “If there is uncertainty, maybe show it.”

    **EARS: WHERE** the researcher provides a measurement uncertainty of ±0.1 °C, the tool **shall** propagate it through the canonical formula (±0.1 °C × 9/5 = ±0.18 °F) and **shall** include it in the returned result as 77.00 ± 0.18 °F.

    **EARS: WHERE** the researcher provides a measurement uncertainty, the tool **shall** save the propagated uncertainty in the history record alongside the result and experiment/sample id.

    **EARS: WHERE** no measurement uncertainty is provided, the tool **shall** return the result without an uncertainty component and **shall** record in history that uncertainty was not supplied.

### Scenario 2: Request weather of a city. (OpenWeatherMap: API)

1. **Ubiquitous — always true: [Subject] shall [Action]**

    **Bad:** “The system should return weather data.”

    **EARS:** The system **hall** support weather requests for a city identified by name and optional country code, with units metric or imperial.

    **EARS:** The system ** resolve every city request to a unique cityId and geographic coordinates before calling the weather provider.

    **EARS:** The system **shall** display temperature, humidity, and air pressure in the units corresponding to the requested unit system.

    **EARS:** The system **shall** include the observation time (observedAt) in every weather result.

    **EARS:** The system **shall** cache every successful weather response with a time-to-live (TTL) of 10 minutes.

    **EARS:** The system **shall** validate all required fields and plausible ranges before returning or caching a weather response.

2. **Event-driven — triggered by event: WHEN [Event], [Subject] shall [Action]**

    **Bad**: "When the user asks for weather, get it.”

    **EARS: WHEN** the user requests current weather for London, GB with units metric, the system shall resolve the city to cityId=2643743 and its latitude/longitude.

    **EARS: WHEN** the city is resolved, the system shall check the cache using the key cityId + units (e.g., 2643743+metric).

    **EARS: WHEN** the cache entry for London+metric is empty, the system shall call the OpenWeatherMap API with the resolved coordinates and units=metric.

    **EARS: WHEN** the OpenWeatherMap API returns a successful response containing 15.2 °C, 72%, 1013 hPa, 4.5 m/s, and observedAt=14:20, the system shall validate the fields and ranges.

    **EARS: WHEN** validation succeeds, the system shall store the response in the cache with TTL=10 minutes and a storedAt timestamp.

    **EARS: WHEN** the response is cached, the system shall return the result to the user containing 15.2 °C, 72%, 1013 hPa, and the observation time.

3. **State-driven — while in a state: WHILE [State], [Subject] shall [Action]**

    **Bad:** “While cached, use it.”

    **EARS: WHILE** a cache entry for the requested cityId + units exists and its age is less than or equal to the TTL, the system **shall** return the cached weather data without calling the OpenWeatherMap API.

    **EARS: WHILE** a cache entry is fresh, the system **shall** display the cached observation time so the user can judge data age.

    **EARS: WHILE** a weather request is in progress, the system **shall** show a loading state and **shall not** create duplicate cache entries for the same cityId + units.
4. **Unwanted behavior — failure handling: IF [Failure/undesired event], THEN [Subject] shall [Action]**

    **Bad:** “If something goes wrong, show an error.”

    **EARS: IF** the city input `London` resolves to multiple locations, **THEN** the system **shall** ask the user to choose a specific city or country code before calling the API.

    **EARS: IF** the city input does not resolve to any known location, **THEN** the system **shall** return the error `CITY_NOT_FOUND`, **shall not** call OpenWeatherMap, and **shall not** create a cache entry.

    **EARS: IF** the OpenWeatherMap API returns HTTP `404`, **THEN** the system **shall** return `CITY_NOT_FOUND` and **shall not** cache the response.

    **EARS: IF** the OpenWeatherMap API returns HTTP `401`, **THEN** the system **shall** log a configuration error and return `SERVICE_CONFIGURATION_ERROR` to the user.

    **EARS: IF** the OpenWeatherMap API returns HTTP `429`, **THEN** the system **shall** return `RATE_LIMITED` with a retry-after hint if provided, and **shall not** cache the error response.

    **EARS: IF** the OpenWeatherMap API times out or returns HTTP `5xx`, **THEN** the system **shall** return `WEATHER_SERVICE_UNAVAILABLE` and **may** return a stale cache entry with a `stale=true` warning only if the requirement explicitly allows stale fallback.

    **EARS: IF** the API response is missing a required field (temperature, humidity, pressure), **THEN** the system **shall** treat the response as malformed, **shall not** cache it, and **shall** return `MALFORMED_RESPONSE`.

    **EARS: IF** a field value is outside a plausible range (e.g., humidity > 100%, pressure ≤ 0), **THEN** the system **shall** treat the response as invalid, **shall not** cache it, and **shall** return `INVALID_DATA`.

5. **Optional features — only when a condition/resource exists: WHERE [Condition], [Subject] shall [Action]**

    **Bad:** “If units are given, use them.”

    **EARS: WHERE** the user specifies `units=metric`, the system **shall** request metric units from OpenWeatherMap and display temperature in `°C`, wind speed in `m/s`, and pressure in `hPa`.

    **EARS: WHERE** the user specifies `units=imperial`, the system **shall** request imperial units from OpenWeatherMap and display temperature in `°F`, wind speed in `mph`, and pressure in `inHg`.

    **EARS: WHERE** a fresh cache entry exists for the requested `cityId + units`, the system **shall** return the cached data and **shall not** call the OpenWeatherMap API.

    **EARS: WHERE** the OpenWeatherMap API returns a wind speed value, the system **shall** display wind speed in the result; **WHERE** the wind speed field is absent, the system **shall** explicitly mark wind speed as unavailable rather than omitting it silently.

    **EARS: WHERE** the provider requires attribution, the system **shall** display the OpenWeatherMap attribution together with the weather result.

### Scenario 3: Convert kilometers to miles (Unit Converter: length)

 1. **Ubiquitous — always true: [Subject] shall [Action]**

    **Bad:** “The tool should convert kilometers to miles.”

    
    **EARS:** The tool **shall** support length conversion between `km` and `mi`.
    
    **EARS:** The tool **shall** use the exact conversion factor `1 mile = 1.609344 km`, giving `1 km = 0.621371192237334 mi`.
    
    **EARS:** The tool **shall** record every successful conversion with input, output, factor id/version, rounding rule, timestamp, and engineer id.
    
    **EARS:** The tool **shall** return the rounded result, the raw result, and the exact factor used.




2. **Event-driven — triggered by event: WHEN [Event], [Subject] shall [Action]**

    **Bad:** “When the engineer converts, do it.”

    **EARS: WHEN** the civil engineer submits value `12.345 km`, target unit `mi`, and precision `3`, the tool **shall** validate that the value is positive, finite, and within the supported range.
    
    **EARS: WHEN** validation succeeds, the tool **shall** resolve the unit pair `km → mi` and look up the exact conversion factor from the unit registry, including factor id and version.
    
    **EARS: WHEN** the factor is resolved, the tool **shall** compute the raw result using `12.345 × 0.621371192237334 = 7.670827368169888 mi`.
    
    **EARS: WHEN** the raw result is computed, the tool **shall** apply the rounding rule `half-up to 3 decimal places`, producing `7.671 mi`.
    
    **EARS: WHEN** rounding completes, the tool **shall** record the conversion with input, output, factor id/version, rounding rule, timestamp, and engineer id.
    
    **EARS: WHEN** the record is saved, the tool **shall** return `7.671 mi` as the rounded result, plus the raw value and the exact factor used.



3. **State-driven — while in a state: WHILE [State], [Subject] shall [Action]**
    
    **Bad:** “While converting, show something.”

    
    **EARS: WHILE** a conversion request is being processed, the tool **shall** show a loading state and **shall not** create duplicate conversion records for the same request.
    
    **EARS: WHILE** a conversion record exists, the tool **shall** keep its factor id/version and rounding rule immutable in history.



4. **Unwanted behavior — failure handling: IF [Failure/undesired event], THEN [Subject] shall [Action]**

    *Bad:** “If the input is bad, show an error.”

    
    **EARS: IF** the input value is not positive, **THEN** the tool **shall** reject the request, produce no result, save no history record, and return `VALUE_MUST_BE_POSITIVE`.
    
    **EARS: IF** the input value is not finite (NaN or infinity), **THEN** the tool **shall** reject the request and return `VALUE_NOT_FINITE`.
    
    **EARS: IF** the input value is outside the supported range, **THEN** the tool **shall** reject the request and return `VALUE_OUT_OF_RANGE`.
    
    **EARS: IF** the unit pair `km → mi` is not supported by the registry, **THEN** the tool 
    **shall** reject the request and return `UNSUPPORTED_UNIT_PAIR`.
    
    **EARS: IF** the exact conversion factor or its version is missing from the registry, **THEN** the tool **shall** reject the request, save no history record, and return `CONVERSION_FACTOR_UNAVAILABLE`.
    
    **EARS: IF** the requested precision is outside the allowed range, **THEN** the tool **shall** reject the request and return `INVALID_PRECISION`.
    
    **EARS: IF** the engineer id is missing, **THEN** the tool **shall** reject the request and 
    **shall not** save a history record without it.


5. **Optional features — only when a condition/resource exists: WHERE [Condition], [Subject] shall [Action]**

    **Bad:** “If there is extra info, show it.”

    
    **EARS: WHERE** the unit registry provides a factor version, the tool **shall** record that version in the conversion history.
    
    **EARS: WHERE** the raw result differs from the rounded result, the tool **shall** return both the rounded value and the raw value.
    
    **EARS: WHERE** the engineer requests a precision other than the default `3`, the tool 
    **shall** apply the requested precision and record it in the history.
    
    **EARS: WHERE** the conversion factor has been updated in the registry, the tool **shall** use the current factor version for new conversions while preserving the historical factor version in old records.

### Scenario 4: Convert a text to Title-case (text transformer: title)

1. **Ubiquitous — always true: [Subject] shall [Action]**

    **Bad:** “The tool should capitalize the text.”**
    
    **EARS:** The tool **shall** support title-case transformation for input text using a named profile (e.g., `title-basic-v1`).
    
    **EARS:** The tool **shall** validate that the input text is non-empty and within the configured length limit before applying any transformation.
    
    **EARS:** The tool **shall** save every successful transformation record with input text, output text, profile id/version, timestamp, author id, and document id.
    
    **EARS:** The tool **shall** return the transformed text, the profile id/version, and the timestamp.



2. **Event-driven — triggered by event: WHEN [Event], [Subject] shall [Action]**

    
    **Bad:** “When the author converts, do it.”

    **EARS: WHEN** the author submits the text `"the quick brown fox jumps over the lazy dog"` with profile `title-basic-v1`, the tool **shall** validate that the text is non-empty, within the length limit, the profile exists, and the characters are supported.
    
    **EARS: WHEN** validation succeeds, the tool **shall** tokenize the text and apply the `title-basic-v1` profile to produce `"The Quick Brown Fox Jumps Over The Lazy Dog"`.
    
    **EARS: WHEN** the transformation completes, the tool **shall** save a transformation record with input, output, profile id/version, timestamp, author id, and document id.
    
    **EARS: WHEN** the record is saved, the tool **shall** return the result `"The Quick Brown Fox Jumps Over The Lazy Dog"`, the profile `title-basic-v1`, and the timestamp.



3. **State-driven — while in a state: WHILE [State], [Subject] shall [Action]**

    **Bad:** “While transforming, show something.”
    
    **EARS: WHILE** a transformation request is being processed, the tool **shall** show a loading state and **shall not** create duplicate transformation records for the same request.
    
    **EARS: WHILE** a transformation record exists, the tool **shall** keep its profile id/version and timestamp immutable in history.



4. **Unwanted behavior — failure handling: IF [Failure/undesired event], THEN [Subject] shall [Action]**

    **Bad:** “If the input is bad, show an error.”

    **EARS: IF** the input text is empty or consists only of whitespace, **THEN** the tool **shall** reject the request, produce no output, save no history record, and return `TEXT_EMPTY`.
    
    **EARS: IF** the input text exceeds the configured length limit, **THEN** the tool **shall** reject the request and return `TEXT_TOO_LONG`.
    
    **EARS: IF** the specified profile does not exist, **THEN** the tool **shall** reject the request, produce no output, save no history record, and return `PROFILE_NOT_FOUND`.
    
    **EARS: IF** the input text contains characters not supported by the profile, **THEN** the tool **shall** reject the request and return `UNSUPPORTED_CHARACTERS`.
    
    **EARS: IF** the author id or document id is missing, **THEN** the tool **shall** reject the request and **shall not** save a history record without them.


5. **Optional features — only when a condition/resource exists: WHERE [Condition], [Subject] shall [Action]**

    **Bad:** “If there is extra info, show it.”
    
    **EARS: WHERE** the profile defines small-word exceptions (e.g., `the`, `of`, `and`), the tool **shall** apply those exceptions according to the profile rules.
    
    **EARS: WHERE** the input text contains hyphenated compounds, the tool **shall** apply the profile’s hyphenation rule (e.g., capitalize each segment or only the first).
    
    **EARS: WHERE** the input text contains apostrophes (e.g., `o'neill`), the tool **shall** apply the profile’s apostrophe rule (e.g., `O'Neill` or `O'neill`).
    
    **EARS: WHERE** the profile specifies preserving acronyms, the tool **shall** leave all-uppercase tokens unchanged.
    
    **EARS: WHERE** the author requests a profile other than the default, the tool **shall** load that profile and record its id/version in the transformation history.


# Ошибочные сценарии

### Scenario 5: API fetch timeout (error)


1. Scientific researcher requests a dataset from an external scientific API (e.g., climate observations for station GB-LON-01, for current time).

2. Tool sends request with a configured connect timeout 3 s and read timeout 10 s.

3. External API accepts the connection but does not send a response within 10 s.

4. Tool cancels the read, closes the connection, and records the attempt: request id, endpoint, timeout type (read), elapsed time, timestamp, researcher id, dataset id.

5. Return error: “Request timed out after 10 s. No data returned. You can retry.

6. The researcher can retry manually; 

### Scenario 6: Incompatible unit categories (error)

1. Civil engineer inputs a value **12.5**, source unit **meter**, target unit **kilogram.**
2. Tool resolves each unit to a **dimension dictionary**:
`meter` (m) = length = `L¹`;     `kilogram` (kg) = mass = `M¹`.

3. Tool compares dimension vectors → `{L:1}` ≠ `{M:1}` → they are **not equal**.

4. Tool classifies the pair as **incompatible categories** `(length vs mass)` and **refuses conversion** — no numeric result is produced.

5. Tool records the rejected attempt: input=12.5, source=`m`, target=`kg`, detected dimensions `length` vs `mass`, reason code `INCOMPATIBLE_DIMENSIONS`, timestamp, engineer id.

6. Tool suggests compatible alternatives:
for source m (length): `mm`, `cm`, `km`, `in`, `ft`, `yd`, `mi`;
for target `kg` (mass): `g`, `mg`, `t`, `lb`, `oz`.

7. Return error: **“Cannot convert meter to kilogram — length vs mass. Use cm/ft for length or g/lb for mass.”**


# Жизненный цикл Job

# Раздел «Что предложил ИИ»