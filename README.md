<p align="center">
  <a href="https://fastdash.app/"><img src="https://storage.googleapis.com/fast_dash/0.1.8/logo.png" alt="Fast Dash" width=300></a>
</p>
<p align="center">
    <em>Open source, Python-based tool to build prototypes lightning fast ⚡</em>
</p>

<p align="center">
<a href="https://pypi.python.org/pypi/fast_dash">
    <img src="https://img.shields.io/pypi/v/fast_dash?color=%2334D058"
        alt = "Release Status">
</a>

<a href="https://github.com/dkedar7/fast_dash/actions">
    <img src="https://github.com/dkedar7/fast_dash/actions/workflows/release.yml/badge.svg" alt="CI Status">
</a>


<a href="https://github.com/dkedar7/fast_dash/blob/main/LICENSE">
    <img src="https://img.shields.io/github/license/dkedar7/fast_dash" alt="MIT License">
</a>

<a href="https://docs.fastdash.app/">
    <img src="https://img.shields.io/badge/Docs-MkDocs-<COLOR>.svg" alt="Documentation">
</a>

<a href="https://pepy.tech/project/fast-dash">
    <img src="https://static.pepy.tech/personalized-badge/fast-dash?period=total&units=international_system&left_color=grey&right_color=brightgreen&left_text=Downloads" alt="Downloads">
</a>

</p>


---

* **Documentation**: [https://docs.fastdash.app](https://docs.fastdash.app)
* **Source code**: [github.com/dkedar7/fast_dash](https://github.com/dkedar7/fast_dash/)
* **Installation**: `pip install fast-dash`

---

Fast Dash is a Python module that makes the development of web applications fast and easy. It can build web interfaces for Machine Learning models or to showcase any proof of concept without the hassle of developing UI from scratch.

<!-- <p align="center">
  <a href="https://fastdash.app/"><img src="https://raw.githubusercontent.com/dkedar7/fast_dash/main/docs/assets/gallery_4_apps.gif" alt="Fast Dash logo"></a>
</p> -->

## Examples

With Fast Dash's decorator `@fastdash`, it's a breeze to deploy any Python function as a web app. Here's how to use it to write your first Fast Dash app:
```python
from fast_dash import fastdash

@fastdash
def text_to_text_function(input_text):
    return input_text

# * Running on http://127.0.0.1:5000/ (Press CTRL+C to quit)
```

And just like that (🪄), we have a completely functional interactive app!

Output:
![Simple example](https://storage.googleapis.com/fast_dash/0.2.1/Simple%20text%20to%20text.png)
---

Fast Dash can read all the function details, like its name, input and output types, docstring, and uses this information to infer which components to use.

For example, here's how to deploy an app that takes a string and an integer as inputs and returns some text.

```python
from fast_dash import fastdash

@fastdash
def display_selected_text_and_number(text: str, number: int) -> str:
    "Simply display the selected text and number"
    processed_text = f'Selected text is {text} and the number is {number}.'
    return processed_text

# * Running on http://127.0.0.1:5000/ (Press CTRL+C to quit)
```

Output:
![Simple example with multiple inputs](https://storage.googleapis.com/fast_dash/0.2.1/Simple%20example%202.png)

And with just a few more lines, we can add a title icon, subheader and other social branding details.

---

## About

Read different ways to build Fast Dash apps and additional details by navigating to the [project documentation](https://docs.fastdash.app/).

### Key features

- Launch an app by adding a decorator only.
- Use multiple input and output components simultaneously.
- Flask-based backend allows easy scalability and customizability.
- Build fast, share and iterate.

## Community

Fast Dash is built using [Plotly Dash](https://github.com/plotly/dash) and it's completely open-source.

## Citation
Please cite Fast Dash it if you use it in your work.
```
@software{Kedar_Dabhadkar_Fast_Dash,
author = {Kedar Dabhadkar},
title = {{Fast Dash}}
}
```