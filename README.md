# Overview


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

</p>


<p align="center">
  <a href="https://fastdash.app/"><img src="https://raw.githubusercontent.com/dkedar7/fast_dash/main/docs/assets/logo.png" alt="Fast Dash logo"></a>
</p>
<p align="center">
    <em>Open source, Python-based tool to build prototypes lightning fast ⚡</em>
</p>


---

* Website: <https://fastdash.app/>
* Documentation: <https://docs.fastdash.app/>
* Source code: <https://github.com/dkedar7/fast_dash/>
* Installation: `pip install fast-dash`

---

Fast Dash is a Python module that makes the development of web applications fast and easy. It is built on top of Plotly Dash and can be used to build web interfaces for Machine Learning models or to showcase any proof of concept without the hassle of developing UI from scratch.

<p align="center">
  <a href="https://fastdash.app/"><img src="https://raw.githubusercontent.com/dkedar7/fast_dash/main/docs/assets/gallery_4_apps.gif" alt="Fast Dash logo"></a>
</p>

## Simple example

Use the `fastdash` decorator to write your first Fast Dash app:

```python
from fast_dash import fastdash

@fastdash
def text_to_text_function(input_text):
    return input_text

# * Running on http://127.0.0.1:5000/ (Press CTRL+C to quit)
```

And just like that, we have a completely functional interactive app!

Output:
![Simple example](https://raw.githubusercontent.com/dkedar7/fast_dash/decorate/docs/assets/simple_example.gif)

---

Fast Dash can read additional details about a function, like its name, input and output types, docstring, and uses this information to infer which components to use.

For example, here's how to deploy an app that takes a string and an integer as inputs and return some text.

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

![Simple example with multiple inputs](https://storage.googleapis.com/fast_dash/0.1.7/simple_example_2.gif)

And with just a few more lines, we can add a title icon, subheader and other social branding details.

```python
from fast_dash import fastdash

@fastdash(title_image_path='https://raw.githubusercontent.com/dkedar7/fast_dash/main/docs/assets/favicon.jpg',
        github_url='https://github.com/dkedar7/fast_dash',
        linkedin_url='https://linkedin.com/in/dkedar7',
        twitter_url='https://twitter.com/dkedar')
def display_selected_text_and_number(text: str, number: int) -> str:
    "Simply display the selected text and number"
    processed_text = f'Selected text is {text} and the number is {number}.'
    return processed_text
```

Output:

![Simple example with multiple inputs and details](https://storage.googleapis.com/fast_dash/0.1.7/simple_example_multiple_inputs_details.png)

---
Read different ways to build Fast Dash apps and additional details by navigating to the [project documentation](https://docs.fastdash.app/).

## Key features

- Launch an app only by specifying the types of inputs and outputs.
- Use multiple input and output components simultaneously.
- Flask-based backend allows easy scalability and customizability.
- Build fast, share and iterate.

Some features are coming up in future releases:

- More input and output components.
- Deploy to Heroku and Google Cloud.
- and many more.

## Community

Fast Dash is built on open-source. You are encouraged to share your own projects, which will be highlighted on a common community gallery (coming up).

## Credits

Fast Dash is built using [Plotly Dash](https://github.com/plotly/dash). Dash's Flask-based backend enables Fast Dash apps to scale easily and makes them highly compatibility with other integration services. This project is partially inspired from [gradio](https://github.com/gradio-app/gradio).

The project template was created with [Cookiecutter](https://github.com/audreyr/cookiecutter) and [zillionare/cookiecutter-pypackage](https://github.com/zillionare/cookiecutter-pypackage).