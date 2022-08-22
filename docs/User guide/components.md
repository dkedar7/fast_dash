# Fast Components

Fast components are the UI components that represent the input and outputs elements in a Fast Dash app. In fact, they are Dash components modified by adding a new `component_property` attribute, in addition to a few other optional properties. Fast Dash provides a `Fastify` function to transform Dash components into Fast components.

Fast Dash borrows the concept of `component_property` from Dash. `component_property` is the answer to the question - __"Which property of a component should be assigned the value returned by the callback function?"__

For example, if the first argument of a Fast Dash callback function is a `str` and we want to represent this input using a component that allows users to enter text. Say we decide to use the `dbc.Input()` Dash component. By reading the documentation of the component [here](https://dash-bootstrap-components.opensource.faculty.ai/docs/components/input/), you'll realize that we must update the `value` property of `dbc.Input()` for it work as expected. And therefore, when defining a Fast component for this input we'd use `component_property="value"`.

We use this design and the fact that Fast Dash allows using Fast components as type hints, in addition of standard Python data types, to write a simple app that takes text entered by users as the first input.

```py hl_lines="3 6"
from fast_dash import Fastify, dbc

text_input_component = Fastify(component=dbc.Input(), component_property="value")

@fastdash
def your_function(input_text: text_input_component, ...):
    ...
```

!!! note

    Note that Fast Dash offers prebuilt Fast Components for common use cases. Some of them are <br>
    - `Text`: To allow entering input text<br>
    - `Slider`: For integer inputs<br>
    - `Upload`: Used to upload documents<br>
    - `UploadImage`: Special case of `Upload` used to upload images<br>
    - `Image`: Used to display image variables returned by callback functions.<br>
    - `Graph`: Display Plotly graphs<br>

    These can be easily imported into your script like this:

    ```py
    from fast_dash import Text, Slider, Upload, UploadImage, Image, Graph
    ```

??? note "Dash components vs Fast components"

    If you have used Dash, you will know that we have to specify a `component_property` to Dash's `Input` and `Output` methods when defining our callback functions (during runtime). In other words, you can develop Dash UI before writing your callback functions.

    On the contrary, Fast Dash **infers** components (when not specified) by studying the underlying callback function, particularly its type hints and default values. For that reason, it becomes essential for us to specify the `component_property` before we define our callback function.

## How are they different from Dash components

## How to transform Dash components into Fast components

## The special acknowledgement (ack) components

## Some examples