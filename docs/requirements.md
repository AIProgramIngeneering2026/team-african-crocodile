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

**Scenario 1**

States: `Created`, `Running`, `Done`, `Error`, `Final Node`.

Transitions:

`start` → `Created`: create task [input payload received] / save task to history, generate task ID.

`Created` → `Running`: start execution [dispatcher routes to Unit Converter] / lock task for execution.

`Running` → `Done`: conversion successful [unit validated, math completed, uncertainty propagated] / save result, precision, and experiment/sample ID to history.

`Running` → `Error`: validation failed [target unit unsupported, precision out of 0–6 bounds, negative uncertainty] / save error history record, return error message.

`Done` → `final`; `Error` → `final`.

**Scenario 2**

States: Created, Running (sub-states: Resolving, Fetching, Validating), Done, Error, Final Node.

**Transitions:**

`start` → `Created`: create task [weather request received] / save task, generate task ID.

`Created` → `Resolving`: start execution [dispatcher routes to Weather Tool] / check cache.

`Resolving` → `Fetching`: cache miss [city not in cache] / resolve city to lat/lon, call OpenWeatherMap API.

`Resolving` → `Done`: cache hit [valid cache entry exists, TTL < 10 min] / skip API, load from cache.

`Fetching` → `Validating`: API response received [HTTP 200 OK] / parse JSON.

`Validating` → `Done`: fields valid [temp, humidity, pressure, wind within expected ranges] / save result to history, update cache with TTL = 10 min.

`Fetching` → `Error`: API failure [timeout, HTTP 4xx/5xx, network unreachable] / record attempt, return error message.

`Validating` → `Error`: invalid payload [missing fields, values out of range, garbage response] / record error, do NOT cache.

`Done` → `final`; `Error` → `final`.

---

**Scenario 3**

**States:** `Created`, `Running`, `Done`, `Error`, `Final Node`.

**Transitions:**

*   `start` → `Created`: **create task** [conversion request received] / *save task, generate task ID.*
*   `Created` → `Running`: **start execution** [dispatcher routes to Unit Converter (length)] / *lock task.*
*   `Running` → `Done`: **conversion successful** [value > 0, finite, within range; source and target units share the same dimension (Length)] / *apply exact factor from registry, round half-up to 3 decimals, save history record (input, output, factor version, engineer ID).*
*   `Running` → `Error`: **validation failed** [value ≤ 0, value = Infinity/NaN, out of supported range, or incompatible dimensions] / *save error record with reason code (e.g., `INVALID_VALUE`, `INCOMPATIBLE_DIMENSIONS`), do not return numeric result.*
*   `Done` → `final`; `Error` → `final`.


**Scenario 4**

States: `Created`, `Running`, `Done`, `Error`, `Final Node`.

**Transitions:**

*   `start` → `Created`: **create task** [transformation request received] / *save task, generate task ID.*
*   `Created` → `Running`: **start execution** [dispatcher routes to Text Transformer] / *lock task.*
*   `Running` → `Done`: **transformation successful** [text is non-empty, length ≤ limit, profile `title-basic-v1` exists, characters supported] / *tokenize, apply profile, save transformation record (input, output, profile id/version, author ID, document ID).*
*   `Running` → `Error`: **validation failed** [text empty, exceeds length limit, unknown profile, unsupported characters] / *save error record with reason code (e.g., `PROFILE_NOT_FOUND`, `TEXT_TOO_LONG`).*
*   `Done` → `final`; `Error` → `final`.

# Раздел «Что предложил ИИ»