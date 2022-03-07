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

<a href="https://dkedar7.github.io/fast_dash/">
    <img src="https://img.shields.io/badge/Docs-MkDocs-<COLOR>.svg" alt="Documentation">
</a>

</p>


<p align="center">
  <a href="https://dkedar7.github.io/fast_dash/"><img src="https://raw.githubusercontent.com/dkedar7/fast_dash/main/docs/assets/logo.png" alt="Fast Dash logo"></a>
</p>
<p align="center">
    <em>Open source, Python-based tool to develop web applications lightning fast.</em>
</p>


---


* Documentation: <https://dkedar7.github.io/fast_dash/>
* Source code: <https://github.com/dkedar7/fast_dash/>

---

Fast Dash is a Python module that makes the development of web applications fast and easy. It is built on top of Plotly Dash and can be used to build web interfaces for Machine Learning models or to showcase any proof of concept without the hassle of developing UI from scratch.

## Simple example

Run your app with three simple steps:

```python
from fast_dash import FastDash
from fast_dash.Components import Text

# Step 1: Define your model inference
def text_to_text_function(input_text):
    return input_text

# Step 2: Specify the input and output components
app = FastDash(callback_fn=text_to_text_function, 
                inputs=Text, 
                outputs=Text, 
                title='App title')

# Step 3: Run your app!
app.run()

# * Running on http://127.0.0.1:5000/ (Press CTRL+C to quit)
```

And just like that, we have a completely functional interactive app!

Output:

![Simple example](https://raw.githubusercontent.com/dkedar7/fast_dash/main/docs/assets/simple_example.gif)

---

In a similar way, we can add multiple input as well as output components at the same time.

```python
from fast_dash import FastDash
from fast_dash.Components import Text, Slider

# Step 1: Define your model inference
def text_to_text_function(input_text, slider_value):
    processed_text = f'{input_text}. Slider value is {slider_value}.'
    return processed_text

# Step 2: Specify the input and output components
app = FastDash(callback_fn=text_to_text_function, 
                inputs=[Text, Slider], 
                outputs=Text,
                title='App title')

# Step 3: Run your app!
app.run()

# * Running on http://127.0.0.1:5000/ (Press CTRL+C to quit)
```

---

![Simple example with multiple inputs](https://raw.githubusercontent.com/dkedar7/fast_dash/main/docs/assets/simple_example_multiple_inputs.gif)

And with just a few more lines, we can add a title icon, subheader and social details.

```python
...

app = FastDash(callback_fn=text_to_text_function, 
                inputs=[Text, Slider], 
                outputs=Text,
                title='App title',
                title_image_path='https://raw.githubusercontent.com/dkedar7/fast_dash/main/docs/assets/favicon.jpg',
                subheader='Build a proof-of-concept UI for your Python functions lightning fast.',
                github_url='https://github.com/dkedar7/fast_dash',
                linkedin_url='https://linkedin.com/in/dkedar7',
                twitter_url='https://twitter.com/dkedar')

...

```

Output:

![Simple example with multiple inputs and details](https://raw.githubusercontent.com/dkedar7/fast_dash/main/docs/assets/simple_example_multiple_inputs_details.gif.png)

---

## Key features

- Launch an app only by specifying the types of inputs and outputs.
- Multiple input and output components simultaneously.
- Flask-based backend allows easy scalability and customizability.
- Build fast and iterate.

Some features are coming up in future releases:

- More input and output components.
- Deploy to Heroku and Google Cloud.
- and many more.

## Community

Fast Dash is built on open-source. You are encouraged to share your own projects, which will be highlighted on a common community gallery that's upcoming. Join us on [Discord](https://discord.gg/B8nPVfPZ6a).

## Credits

Fast Dash is inspired from [gradio](https://github.com/gradio-app/gradio) and built using [Plotly Dash](https://github.com/plotly/dash). Dash's Flask-based backend enables Fast Dash apps to scale easily and makes them highly compatibility with other integration services.  Many documentation ideas and concepts are borrowed from [FastAPI's docs](https://fastapi.tiangolo.com/) project template.

The project template was created with [Cookiecutter](https://github.com/audreyr/cookiecutter) and [zillionare/cookiecutter-pypackage](https://github.com/zillionare/cookiecutter-pypackage).
