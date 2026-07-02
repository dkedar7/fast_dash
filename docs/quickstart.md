# Quickstart

## Install Fast Dash

Let's start by installing Fast Dash:
```
pip install fast-dash
```

## Simple Example

Here's the simple text to text function from the [home page](index.md) again.

```py linenums="1"
from fast_dash import fastdash

@fastdash
def text_to_text_function(input_text):
    return input_text
```

This should spin up your first Fast Dash app!

<figure markdown>
  ![Simple example](https://storage.googleapis.com/fast_dash/0.2.7/Simple%20text%20to%20text.png)
  <figcaption>Simple example app</figcaption>
</figure>

## Chatbot example

Pass `chat=True` and your callback becomes a streaming chat app — a composer
pinned at the bottom, a scrolling transcript, and per-session history — with no
LLM provider baked in. The first parameter must be named `query`; `yield`
strings to stream the reply.

```py linenums="1"
from fast_dash import fastdash

@fastdash(chat=True)
def virtual_assistant(query: str):
    """A helpful assistant."""
    for token in ["I ", "am ", "Groot."]:   # replace with your LLM's stream
        yield token
```

See the [chat guide](User guide/chat.md) for history, sidebar settings, and the
frame grammar (tool calls, reasoning, inline artifacts).

<figure markdown>
  ![Simple example](https://storage.googleapis.com/fast_dash/0.2.7/Simple%20chatbot%20example.png)
  <figcaption>Simple chatbot app</figcaption>
</figure>


## Image to image example

Fast Dash makes it very easy to work with different types of data types and components. 
For example, here's how to build an app that receives an uploaded image and returns the same image.
We can, of course, write any image analysis transformation we want.

```py linenums="1"
from fast_dash import fastdash
from PIL import Image

@fastdash
def image_to_image(image: Image.Image) -> Image.Image:
    "Example of an image to image app with Fast Dash"
    return image
```

This is how the deployed app looks:

<figure markdown>
  ![Simple example](https://storage.googleapis.com/fast_dash/0.2.7/image_to_image_example.png)
  <figcaption>Simple image to image example app</figcaption>
</figure>

## What else is possible

There are many customizations that you can make with your app. These include:

* Choose from different themes
* Use any Dash component in your app
* Add custom branding and social media icons
* Customize pre-built components
* Live reload
* Minimal view
* JupyterLab inline and embedded views

By tweaking these configurations, you can easily build web applications for a variety of use cases!

## Examples

See the [examples](/Examples/01_simple_text_to_text) page for more executable examples.
