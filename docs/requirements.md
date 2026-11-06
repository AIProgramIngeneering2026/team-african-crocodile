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


# Критерии приемки по шаблонам EARS

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