use pyo3::{
    prelude::*,
    types::{PyDict, PyString},
};
use reqwest::{
    blocking::Client,
    header::{self, HeaderMap, HeaderValue},
};
use serde_json::Value;

fn is_snowpark(con: &PyObject) -> Result<bool, PyErr> {
    Ok(Python::with_gil(|py| {
        con.getattr(py, "connection")
            .map(|_| true)
            .unwrap_or_else(|_| false)
    }))
}

fn create_authorization_header(con: &PyObject, py: Python) -> Result<HeaderValue, PyErr> {
    let token: String;
    if is_snowpark(con)? {
        token = con
            .getattr(py, "connection")?
            .getattr(py, "rest")?
            .getattr(py, "token")?
            .extract(py)?;
    } else {
        token = con.getattr(py, "rest")?.getattr(py, "token")?.extract(py)?;
    }
    HeaderValue::from_str(&format!("Snowflake Token=\"{}\"", token))
        .map_err(|_| PyErr::new::<pyo3::exceptions::PyValueError, _>("Invalid token format"))
}

fn make_headers(con: &PyObject) -> Result<HeaderMap, PyErr> {
    Python::with_gil(|py| {
        let mut headers = HeaderMap::new();
        headers.insert(header::AUTHORIZATION, create_authorization_header(con, py)?);
        headers.insert(
            header::CONTENT_TYPE,
            HeaderValue::from_static("application/json"),
        );
        headers.insert(
            header::USER_AGENT,
            HeaderValue::from_static("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.3"),
        );

        Ok(headers)
    })
}

fn handle_error<T>(message: &str, err: T) -> PyErr
where
    T: std::fmt::Display,
{
    PyErr::new::<pyo3::exceptions::PyException, _>(format!("{}: {}", message, err))
}

fn is_running_inside_stored_procedure() -> bool {
    Python::with_gil(|py| {
        py.import("platform")
            .and_then(|module| module.getattr("PLATFORM"))
            .and_then(|platform| platform.extract::<String>())
            .map_or(false, |value| value == "XP")
    })
}

fn extract_and_join(json_list: Vec<Value>) -> String {
    json_list
        .into_iter()
        .filter_map(|s| {
            s["choices"][0]["delta"]["content"]
                .as_str()
                .map(|s| s.to_string())
        })
        .collect()
}

fn prepare_endpoint_url(con: PyObject, endpoint_type: &str) -> Result<String, PyErr> {
    Python::with_gil(|py| {
        let inside_snowflake = is_running_inside_stored_procedure();
        let host: String = if is_snowpark(&con)? {
            con.getattr(py, "connection")?
                .getattr(py, "host")?
                .extract(py)?
        } else {
            con.getattr(py, "host")?.extract(py)?
        };
        let endpoint = match endpoint_type {
            "analyst" => "/api/v2/cortex/analyst/message".to_string(),
            "complete" => "/api/v2/cortex/inference:complete".to_string(),
            "search" => {
                let database: String = con.getattr(py, "database")?.extract(py)?;
                let schema: String = con.getattr(py, "schema")?.extract(py)?;
                format!(
                    "/api/v2/databases/{}/schemas/{}/cortex-search-services/",
                    database, schema
                )
            }
            "sql" => "/api/v2/statements".to_string(),
            _ => {
                return Err(PyErr::new::<pyo3::exceptions::PyValueError, _>(format!(
                    "Invalid endpoint: {}",
                    endpoint_type
                )))
            }
        };
        Ok(if inside_snowflake {
            endpoint
        } else {
            format!("https://{}/{}", host, endpoint)
        })
    })
}

fn send_request(url: &str, headers: HeaderMap, data: Value) -> Result<Value, PyErr> {
    if is_running_inside_stored_procedure() {
        Python::with_gil(|py| {
            // Import the Snowflake API module and call the 'send_snow_api_request' function.
            let result = py
                .import("_snowflake")
                .and_then(|module| {
                    module.call_method1(
                        "send_snow_api_request",
                        (
                            "POST",
                            url,
                            {},
                            {},
                            PyString::new(
                                py,
                                &serde_json::to_string(&data)
                                    .map_err(|e| handle_error("Serialization error", e))?,
                            ),
                            {},
                            30000,
                        ),
                    )
                })
                .map_err(|e| handle_error("Error calling Snowflake API", e))?
                .extract::<String>()
                .map_err(|e| handle_error("Error parsing response from Snowflake API", e));

            // Return the result
            result.map(|response| {
                serde_json::from_str(&response)
                    .map_err(|e| handle_error("Failed to parse JSON response", e))
            })?
        })
    } else {
        let client = Client::new();
        let response = client
            .post(url)
            .headers(headers)
            .json(&data)
            .send()
            .map_err(|e| handle_error("Request error", e))?;

        // Parse and return the JSON response
        let json_response: Value = response
            .json()
            .map_err(|e| handle_error("Response parsing error", e))?;

        Ok(json_response)
    }
}

#[pyfunction]
fn analyst(con: PyObject, semantic_model_file: &str, prompt: &str) -> PyResult<Py<PyDict>> {
    Python::with_gil(|py| {
        let url = prepare_endpoint_url(con.clone_ref(py), "analyst")?;
        let headers = make_headers(&con.clone_ref(py))?;

        let data = serde_json::json!({
            "messages": [
                {"role": "user", "content": [{"type": "text", "text": prompt}]}
            ],
            "semantic_model_file": semantic_model_file,
        });

        let response_json: Value = send_request(&url, headers, data)?;

        let py_dict = PyDict::new(py);
        for (key, value) in response_json.as_object().unwrap_or(&serde_json::Map::new()) {
            py_dict.set_item(key, value.to_string()).map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyException, _>(format!(
                    "Dict conversion error: {}",
                    e
                ))
            })?;
        }

        Ok(py_dict.into())
    })
}

#[pyfunction]
fn complete(con: PyObject, model: &str, prompt: &str) -> PyResult<Py<PyString>> {
    Python::with_gil(|py| -> PyResult<Py<PyString>> {
        let url = prepare_endpoint_url(con.clone_ref(py), "complete")?;
        let headers = make_headers(&con)?;
        let data = serde_json::json!({
            "model": model,
            "messages": [{"content": prompt}],
        });

        let client = Client::new();
        let response_text = client
            .post(url)
            .headers(headers)
            .json(&data)
            .send()
            .map_err(|e| handle_error("Request error", e))?
            .text()
            .map_err(|e| handle_error("Request error", e))?;

        let json_list: Vec<Value> = response_text
            .lines()
            .filter_map(|line| line.trim().strip_prefix("data: "))
            .filter_map(|line| serde_json::from_str::<Value>(line).ok())
            .collect();

        let answer = extract_and_join(json_list);
        Ok(PyString::new(py, &answer.trim()).into())
    })
}

#[pyfunction]
fn search(
    con: PyObject,
    service_name: &str,
    prompt: &str,
    columns: Vec<String>,
    limit: u16,
) -> PyResult<Py<PyDict>> {
    Python::with_gil(|py| {
        let url = prepare_endpoint_url(con.clone_ref(py), "search")?;
        let url = format!("{}/{}:query", url, service_name);
        let headers = make_headers(&con.clone_ref(py))?;

        let data = serde_json::json!({
            "query": prompt,
            "columns": columns,
            "limit": limit,
        });

        let response_json = send_request(&url, headers, data)?;

        let py_dict = PyDict::new(py);
        for (key, value) in response_json.as_object().unwrap_or(&serde_json::Map::new()) {
            py_dict.set_item(key, value.to_string()).map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyException, _>(format!(
                    "Dict conversion error: {}",
                    e
                ))
            })?;
        }

        Ok(py_dict.into())
    })
}

#[pyfunction]
fn sql(con: PyObject, statement: &str) -> PyResult<Py<PyDict>> {
    Python::with_gil(|py| {
        let url = prepare_endpoint_url(con.clone_ref(py), "sql")?;
        let mut headers = make_headers(&con.clone_ref(py))?;
        headers.remove("AUTHORIZATION");
        let token: String = con.getattr(py, "rest")?.getattr(py, "token")?.extract(py)?;
        headers.insert(
            header::AUTHORIZATION,
            HeaderValue::from_str(&format!("Bearer {}", token)).map_err(|_| {
                PyErr::new::<pyo3::exceptions::PyValueError, _>("Invalid token format")
            })?,
        );

        let data = serde_json::json!({
            "statement": statement,
        });

        let response_json = send_request(&url, headers, data)?;

        let py_dict = PyDict::new(py);
        for (key, value) in response_json.as_object().unwrap_or(&serde_json::Map::new()) {
            py_dict.set_item(key, value.to_string()).map_err(|e| {
                PyErr::new::<pyo3::exceptions::PyException, _>(format!(
                    "Dict conversion error: {}",
                    e
                ))
            })?;
        }

        Ok(py_dict.into())
    })
}

#[pymodule]
fn xetroc(m: &Bound<'_, PyModule>) -> PyResult<()> {
    m.add_function(wrap_pyfunction!(analyst, m)?)?;
    m.add_function(wrap_pyfunction!(complete, m)?)?;
    m.add_function(wrap_pyfunction!(search, m)?)?;
    m.add_function(wrap_pyfunction!(sql, m)?)?;
    Ok(())
}
