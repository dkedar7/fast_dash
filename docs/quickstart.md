# Quickstart

## Install Fast Dash

Let's start by installing Fast Dash. Do that by running:
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
  ![Simple example](https://storage.googleapis.com/fast_dash/0.1.7/simple_example.gif)
  <figcaption>Simple example app</figcaption>
</figure>


## Image to image example

Fast Dash makes it very easy to work with different types of data types and components. 
For example, here's the code needed to build an app that receives an uploaded image and returns the same image.

```py linenums="1"
from fast_dash import fastdash, UploadImage, Image

@fastdash
def image_to_image(image: UploadImage) -> Image:
    return image
```

This is how the deployed app looks:

<figure markdown>
  ![Simple example](https://storage.googleapis.com/fast_dash/0.1.7/simple_image_to_image.gif)
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

By tweaking these configurations, you can easily build web applications for a variety of use cases! Here're a selected few:

<figure markdown>
  ![Fast Dash gallery](https://storage.googleapis.com/fast_dash/0.1.7/gallery_4_apps.gif)
  <figcaption>Fast Dash example gallery</figcaption>
</figure>

